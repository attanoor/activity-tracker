"""Groups a day's sessions into work blocks: one per ticket, document, repository, or app/site.

Blocks are what the AI turns into tasks. Their minutes come from here, so a task's time is always the sum of
its blocks and the AI cannot invent or lose time.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

TASK_KLASSES = {"productive", "communication", "neutral", "meeting"}
MIN_BLOCK_S = 120

MANTIS_TITLE = re.compile(r"^\s*0*(\d{1,8}):\s")
MANTIS_PATH = re.compile(r"view\.php\?(?:.*&)?id=0*(\d{1,8})")
DOC_SUFFIX = re.compile(r"\s+-\s+Google (Docs|Sheets|Slides|Drive)$|\s+-\s+(Word|Excel|PowerPoint)$")
GITHUB_REPO = re.compile(r"^/([\w.-]+)/([\w.-]+)")
APP_NAMES = {"code.exe": "VS Code", "code - insiders.exe": "VS Code", "devenv.exe": "Visual Studio",
             "windowsterminal.exe": "Terminal", "powershell.exe": "PowerShell", "cmd.exe": "Command Prompt",
             "excel.exe": "Excel", "winword.exe": "Word", "powerpnt.exe": "PowerPoint", "outlook.exe": "Outlook",
             "explorer.exe": "File Explorer", "chrome.exe": "Chrome", "msedge.exe": "Edge", "slack.exe": "Slack",
             "ms-teams.exe": "Teams", "zoom.exe": "Zoom", "idea64.exe": "IntelliJ IDEA", "pycharm64.exe": "PyCharm",
             "notepad.exe": "Notepad", "notepad++.exe": "Notepad++", "figma.exe": "Figma"}
BROWSER_SUFFIX = re.compile(r"\s+-\s+(Google Chrome|Microsoft​? Edge|Personal - Microsoft​? Edge)$")


@dataclass
class Block:
    id: str
    key: str
    kind: str          # ticket | doc | repo | app | misc
    label: str
    category: str | None
    klass: str
    seconds: int = 0
    sessions: int = 0
    first: str | None = None
    last: str | None = None
    ticket_id: str | None = None
    titles: Counter = field(default_factory=Counter)

    def as_dict(self) -> dict:
        return {"id": self.id, "key": self.key, "kind": self.kind, "label": self.label, "category": self.category,
                "klass": self.klass, "seconds": self.seconds, "minutes": round(self.seconds / 60),
                "sessions": self.sessions, "first": self.first, "last": self.last, "ticket_id": self.ticket_id,
                "titles": [t for t, _ in self.titles.most_common(5)]}


def clean_title(title: str | None) -> str:
    return BROWSER_SUFFIX.sub("", (title or "").strip())


def ticket_of(title: str | None, paths: list, domain: str | None) -> str | None:
    t = clean_title(title)
    if "mantis" in t.lower() or (domain and "mantis" in domain):
        m = MANTIS_TITLE.match(t)
        if m:
            return m.group(1)
    for p, _ in paths or []:
        m = MANTIS_PATH.search(p)
        if m:
            return m.group(1)
    return None


def block_key(s) -> tuple[str, str, str, str | None]:
    """(key, kind, label, ticket_id) for one session."""
    title = clean_title(s.title)
    tid = ticket_of(s.title, s.paths, s.domain)
    if tid:
        return f"ticket:{tid}", "ticket", re.sub(r"\s+-\s+MantisBT$", "", MANTIS_TITLE.sub("", title)) or f"Ticket {tid}", tid
    if s.domain in ("docs.google.com",) or (s.app or "").lower() in ("winword.exe", "excel.exe", "powerpnt.exe"):
        name = DOC_SUFFIX.sub("", title) or (s.domain or s.app)
        return f"doc:{name.lower()}", "doc", name, None
    if s.domain == "github.com" and s.paths:
        m = GITHUB_REPO.match(s.paths[0][0])
        if m:
            repo = f"{m.group(1)}/{m.group(2)}"
            return f"repo:{repo.lower()}", "repo", repo, None
    target = s.domain or s.app or "unknown"
    label = s.domain or APP_NAMES.get((s.app or "").lower(), (s.app or "unknown").removesuffix(".exe"))
    return f"app:{target.lower()}", "app", label, None


def build_blocks(sessions) -> tuple[list[dict], list[dict]]:
    """Returns (task blocks, non-work blocks). `sessions` are ActivitySession-like rows with a `category` name."""
    blocks: dict[str, Block] = {}
    for s in sessions:
        if s.klass not in TASK_KLASSES and s.klass != "non_work":
            continue
        key, kind, label, tid = block_key(s)
        if s.klass == "non_work":
            key = f"nonwork:{(s.domain or s.app or 'unknown').lower()}"
            kind, label = "app", s.domain or s.app or "unknown"
        b = blocks.get(key)
        if not b:
            b = blocks[key] = Block("", key, kind, label, s.category, s.klass, ticket_id=tid)
        b.seconds += s.duration_s
        b.sessions += 1
        b.first = min(filter(None, [b.first, s.started_at.isoformat()]))
        b.last = max(filter(None, [b.last, s.ended_at.isoformat()]))
        for t, secs in (s.titles or []):
            b.titles[clean_title(t)] += secs

    task, misc, nonwork = [], {}, []
    for b in sorted(blocks.values(), key=lambda b: b.first or ""):
        if b.key.startswith("nonwork:"):
            nonwork.append(b)
        elif b.seconds >= MIN_BLOCK_S or b.kind == "ticket":
            task.append(b)
        else:
            # Many tiny visits are one block per category, e.g. "Other Search/Reference".
            cat = b.category or "Other"
            m = misc.get(cat)
            if not m:
                m = misc[cat] = Block("", f"misc:{cat.lower()}", "misc", f"Other {cat}", b.category, b.klass)
                task.append(m)
            m.seconds += b.seconds
            m.sessions += b.sessions
            m.first = min(filter(None, [m.first, b.first]))
            m.last = max(filter(None, [m.last, b.last]))
            m.titles.update(b.titles)
    for i, b in enumerate(task, 1):
        b.id = f"b{i}"
    for i, b in enumerate(nonwork, 1):
        b.id = f"n{i}"
    return [b.as_dict() for b in task], [b.as_dict() for b in nonwork]


def work_output(actions) -> dict:
    """Counts per source and action from WorkAction-like rows, plus distinct objects touched."""
    counts: dict[str, Counter] = {}
    objects: dict[str, set] = {}
    for a in actions:
        counts.setdefault(a.source, Counter())[a.action] += 1
        objects.setdefault(a.source, set()).add(a.object_id)
    out = {src: {**dict(c), "objects": len(objects[src])} for src, c in counts.items()}
    if "gmail" in out:
        out["gmail"]["threads"] = out["gmail"].pop("objects")
    if "mantis" in out:
        out["mantis"]["tickets"] = out["mantis"].pop("objects")
    if "drive" in out:
        out["drive"]["files"] = out["drive"].pop("objects")
    return out
