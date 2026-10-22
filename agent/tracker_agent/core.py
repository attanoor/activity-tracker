"""Platform-free agent logic: turning samples into spans. Unit-tested without Windows APIs.

A sample is what the agent saw at one instant. Consecutive equal samples grow one span; a span is closed when
the activity changes, when it reaches `max_span_s` (so data reaches the server within about a minute), or
when samples stop arriving for a while (sleep, hibernate, a crash), in which case the gap is not counted.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from fnmatch import fnmatchcase
from urllib.parse import urlsplit

BROWSERS = {"chrome.exe", "msedge.exe"}
DETAIL_FREE = {"private", "paused", "idle", "locked"}


@dataclass(frozen=True)
class Sample:
    at: datetime  # timezone-aware
    kind: str     # active | idle | locked | private | paused
    app: str | None = None
    title: str | None = None
    url: str | None = None
    domain: str | None = None
    context: dict | None = None  # page headings / menu / club name from the extension

    def same_activity(self, other: "Sample") -> bool:
        return ((self.kind, self.app, self.title, self.url, self.context) ==
                (other.kind, other.app, other.title, other.url, other.context))


@dataclass
class Tab:
    url: str
    title: str
    context: dict | None = None


@dataclass
class State:
    private: bool = False
    paused_until: datetime | None = None
    idle_threshold_s: int = 300
    # Sites recorded by domain only: no path, and the domain stands in for the page title.
    domain_only: list[str] = field(default_factory=list)


def _domain_only(domain: str, patterns: list[str]) -> bool:
    for p in patterns:
        p = p.lower().strip()
        if p and (fnmatchcase(domain, p) or domain == p or domain.endswith("." + p)):
            return True
    return False


def build_sample(now: datetime, state: State, app: str | None, title: str | None, idle_s: float, locked: bool,
                 tabs: dict[str, Tab]) -> Sample:
    """`tabs` maps a browser process name to its active tab, as last reported by the extension."""
    if state.paused_until and now < state.paused_until:
        return Sample(now, "paused")
    if state.private:
        return Sample(now, "private")
    if locked:
        return Sample(now, "locked")
    if idle_s >= state.idle_threshold_s:
        return Sample(now, "idle")
    app = app.lower() if app else None
    url = domain = context = None
    tab = tabs.get(app) if app in BROWSERS else None
    if tab and tab.url.startswith(("http://", "https://")):
        parts = urlsplit(tab.url)
        domain = (parts.hostname or "").lower() or None
        url, title, context = tab.url, tab.title or title, tab.context
        if domain and _domain_only(domain, state.domain_only):
            url, title, context = f"{parts.scheme}://{domain}/", domain, None
    return Sample(now, "active", app, (title or None), url, domain, context or None)


@dataclass
class Span:
    started_at: datetime
    ended_at: datetime
    sample: Sample

    def to_event(self) -> dict:
        s = self.sample
        detail = s.kind not in DETAIL_FREE
        return {
            # Start time in ms is unique per device (spans never overlap) and survives a lost local queue,
            # so a resend after reinstalling cannot clash with or duplicate earlier data.
            "seq": int(self.started_at.timestamp() * 1000),
            "started_at": self.started_at.isoformat(),
            "duration_s": max(1, round((self.ended_at - self.started_at).total_seconds())),
            "kind": s.kind,
            "app": s.app if detail else None,
            "title": s.title if detail else None,
            "url": s.url if detail else None,
            "domain": s.domain if detail else None,
            "context": s.context if detail else None,
        }


class Coalescer:
    def __init__(self, interval_s: float = 5, max_span_s: float = 60, max_gap_s: float = 20):
        self.interval = timedelta(seconds=interval_s)
        self.max_span = timedelta(seconds=max_span_s)
        self.max_gap = timedelta(seconds=max_gap_s)
        self.cur: Span | None = None

    def add(self, s: Sample) -> list[dict]:
        """Feed one sample; returns the events of any spans that closed."""
        out: list[dict] = []
        cur = self.cur
        if cur:
            gap = s.at - cur.ended_at
            if gap > self.max_gap or gap < timedelta(0):
                # Machine slept or the clock jumped: close the span where the last sample's time ended.
                out += self._close()
                cur = None
            elif not cur.sample.same_activity(s) or s.at - cur.started_at >= self.max_span:
                cur.ended_at = s.at  # the old activity lasted until this sample
                out += self._close()
                cur = None
        if cur is None:
            self.cur = Span(s.at, s.at + self.interval, s)
        else:
            cur.ended_at = s.at + self.interval
        return out

    def flush(self) -> list[dict]:
        return self._close()

    def _close(self) -> list[dict]:
        cur, self.cur = self.cur, None
        if not cur or cur.ended_at - cur.started_at < timedelta(seconds=1):
            return []
        return [cur.to_event()]
