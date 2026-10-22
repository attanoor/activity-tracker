"""Turns raw device spans into sessions for one user's local day.

Rules:
- Spans are clipped to the requested local day, so a span crossing midnight lands in both days.
- Overlapping spans (two devices, or a late duplicate) are clipped: time is never counted twice.
- Consecutive spans with the same key merge when the gap between them is at most `merge_gap_s`.
  Active spans key on (app, domain, club), plus the thread title in webmail; idle/locked/private/paused key on
  the kind alone.
- Private and paused spans never carry details, even if a device sent them.
- Page context (club name and section read by the extension) is kept per session; the club is part of the
  merge key, so switching club inside one backoffice starts a new session.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

DETAIL_FREE_KINDS = {"private", "paused"}
TOP_N = 5


@dataclass
class Span:
    started_at: datetime
    duration_s: int
    kind: str
    app: str | None = None
    title: str | None = None
    url: str | None = None
    domain: str | None = None
    context: dict | None = None

    @property
    def ended_at(self) -> datetime:
        return self.started_at + timedelta(seconds=self.duration_s)


@dataclass
class SessionDraft:
    started_at: datetime
    ended_at: datetime
    kind: str
    app: str | None
    domain: str | None
    key: tuple = ()
    title_secs: Counter = field(default_factory=Counter)
    path_secs: Counter = field(default_factory=Counter)
    context_secs: Counter = field(default_factory=Counter)  # (section, club) -> seconds

    @property
    def duration_s(self) -> int:
        return int((self.ended_at - self.started_at).total_seconds())

    @property
    def title(self) -> str | None:
        return self.title_secs.most_common(1)[0][0] if self.title_secs else None

    @property
    def titles(self) -> list[list]:
        return [[t, s] for t, s in self.title_secs.most_common(TOP_N)]

    @property
    def paths(self) -> list[list]:
        return [[p, s] for p, s in self.path_secs.most_common(TOP_N)]

    @property
    def contexts(self) -> list[list]:
        return [[sec, club, s] for (sec, club), s in self.context_secs.most_common(TOP_N)]

    @property
    def club(self) -> str | None:
        clubs = Counter()
        for (_, club), s in self.context_secs.items():
            if club:
                clubs[club] += s
        return clubs.most_common(1)[0][0] if clubs else None

    @property
    def section(self) -> str | None:
        secs = Counter()
        for (sec, _), s in self.context_secs.items():
            if sec:
                secs[sec] += s
        return secs.most_common(1)[0][0] if secs else None


def _clip(v, n: int = 200) -> str:
    return " ".join(str(v or "").split())[:n]


def context_summary(ctx: dict | None) -> tuple[str | None, str | None]:
    """(club, section) from the extension's page context. The section is the breadcrumb path, else the active
    menu item, form heading or h1."""
    if not ctx:
        return None, None
    clubs = [c for c in (ctx.get("clubs") or []) if isinstance(c, str) and c.strip()]
    crumbs = [_clip(c, 60) for c in (ctx.get("crumbs") or []) if isinstance(c, str) and c.strip()]
    section = " \u203a ".join(crumbs[:5]) if crumbs else (ctx.get("menu") or ctx.get("heading") or ctx.get("h1"))
    return (_clip(clubs[0], 120) if clubs else None), (_clip(section) or None)


def day_bounds(day: date, tz: str) -> tuple[datetime, datetime]:
    zone = ZoneInfo(tz)
    start = datetime.combine(day, time.min, zone)
    end = datetime.combine(day + timedelta(days=1), time.min, zone)
    return start, end


# In webmail each thread is its own piece of work (time per email/client), so the title splits sessions there.
MAIL_DOMAINS = {"mail.google.com", "outlook.office.com", "outlook.live.com", "outlook.office365.com"}


def _key(s: Span) -> tuple:
    if s.kind == "active":
        club, _ = context_summary(s.context)
        thread = (s.title or "") if (s.domain or "").lower() in MAIL_DOMAINS else ""
        return ("active", (s.app or "").lower(), (s.domain or "").lower(), (club or "").lower(), thread)
    return (s.kind,)


def _clean(s: Span) -> Span:
    if s.kind in DETAIL_FREE_KINDS:
        return Span(s.started_at, s.duration_s, s.kind)
    domain = s.domain
    if s.url and not domain:
        domain = urlsplit(s.url).hostname
    return Span(s.started_at, s.duration_s, s.kind, s.app, s.title, s.url, domain.lower() if domain else None,
                s.context)


def sessionise(spans: list[Span], day: date, tz: str, merge_gap_s: int = 30) -> list[SessionDraft]:
    lo, hi = day_bounds(day, tz)
    out: list[SessionDraft] = []
    cursor = lo  # end of time already accounted for
    for raw in sorted(spans, key=lambda s: s.started_at):
        s = _clean(raw)
        start = max(s.started_at, cursor)
        end = min(s.ended_at, hi)
        if end <= start:
            continue
        secs = int((end - start).total_seconds())
        cur = out[-1] if out else None
        key = _key(s)
        if cur and cur.key == key and (start - cur.ended_at).total_seconds() <= merge_gap_s:
            cur.ended_at = end
        else:
            active = s.kind == "active"
            cur = SessionDraft(start, end, s.kind, s.app if active else None, s.domain if active else None, key)
            out.append(cur)
        if s.title:
            cur.title_secs[s.title] += secs
        if s.url:
            parts = urlsplit(s.url)
            # The query is kept (trimmed) because it often names the object, e.g. view.php?id=12345.
            path = ((parts.path or "/") + (f"?{parts.query}" if parts.query else ""))[:300]
            cur.path_secs[path] += secs
        if s.context:
            club, section = context_summary(s.context)
            if club or section:
                cur.context_secs[(section, club)] += secs
        cursor = end
    return out
