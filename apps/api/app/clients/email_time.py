"""Time spent on each email thread, from Gmail tab titles ('<subject> - <account> - Gmail')."""

import re

PREFIX = re.compile(r"^\s*((re|fw|fwd|aw|wg|sv|tr)\s*(\[\d+\])?\s*:|\[external\])\s*", re.IGNORECASE)
LIST_VIEWS = ("inbox", "sent", "starred", "snoozed", "drafts", "spam", "trash", "all mail", "important",
              "scheduled", "search results", "chats", "outbox", "archive")


def normalize_subject(subject: str | None) -> str:
    s = (subject or "").strip()
    while True:
        new = PREFIX.sub("", s)
        if new == s:
            break
        s = new
    return re.sub(r"\s+", " ", s).strip().lower()


def subject_from_title(title: str | None) -> str | None:
    """The open thread's subject from a Gmail tab title, or None for list views and other pages."""
    t = (title or "").strip()
    if not t.endswith("- Gmail"):
        return None
    parts = t[: -len("- Gmail")].rstrip(" -").rsplit(" - ", 1)
    if len(parts) < 2:
        return None
    subject = parts[0].strip()
    head = re.sub(r"\s*\(\d+\)$", "", subject).strip().lower()
    if not subject or head in LIST_VIEWS or head.startswith(("search results", "label:", "in:")):
        return None
    return normalize_subject(subject)


def thread_participants(actions) -> dict[str, list[str]]:
    """normalized subject -> participant addresses, from gmail work actions (sent and received)."""
    out: dict[str, set] = {}
    for a in actions:
        if a.source != "gmail":
            continue
        key = normalize_subject(a.object_title)
        if not key:
            continue
        people = out.setdefault(key, set())
        for field in ("from", "to", "cc"):
            for p in a.meta.get(field, []) or []:
                if isinstance(p, dict) and p.get("email"):
                    people.add(p["email"].lower())
    return {k: sorted(v) for k, v in out.items()}
