"""Where a person's day went. Pure code: every number in reports and AI text comes from here.

The day is labelled second by second (86 400 slots). Each slot gets exactly one bucket, so the shift breakdown
always adds up to exactly the shift length, and nothing is counted twice.

Order of precedence for a slot:
  1. a counted calendar meeting  -> "meeting"
  2. the session covering it     -> its class (productive, communication, meeting, neutral, non_work, idle,
                                    away for locked, private for private/paused)
  3. nothing recorded            -> "away"
Inside the shift, up to `break_minutes` of away (then idle) time becomes "break", longest stretches first.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

BUCKETS = ["productive", "meeting", "communication", "neutral", "non_work", "idle", "private", "break", "away"]
ACTIVE = {"productive", "meeting", "communication", "neutral", "non_work"}
OTHER_ACTIVE = {"productive", "communication", "neutral", "non_work"}
PASSIVE = {"idle", "away", "private"}
KLASS_TO_BUCKET = {"productive": "productive", "communication": "communication", "meeting": "meeting",
                   "neutral": "neutral", "non_work": "non_work", "idle": "idle", "away": "away",
                   "private": "private", "paused": "private"}
DAY_S = 86_400
FOCUS_MIN_S = 25 * 60
FOCUS_GAP_S = 60
BACK_TO_BACK_S = 5 * 60
SHORT_GAP_S = 30 * 60


@dataclass
class SessionIn:
    started_at: datetime
    ended_at: datetime
    klass: str
    app: str | None = None
    domain: str | None = None
    title: str | None = None
    category: str | None = None


@dataclass
class MeetingIn:
    id: int
    title: str
    started_at: datetime
    ended_at: datetime
    attendees: int = 0
    has_video: bool = False
    attended: bool | None = None  # the person's own answer, if given


@dataclass
class Shift:
    start: time = time(9, 0)
    end: time = time(18, 0)
    break_minutes: int = 60


@dataclass
class _Day:
    lo: datetime
    labels: list = field(default_factory=lambda: ["none"] * DAY_S)

    def idx(self, t: datetime) -> int:
        return max(0, min(DAY_S, int((t - self.lo).total_seconds())))


def _label(s: SessionIn) -> str:
    return KLASS_TO_BUCKET.get(s.klass, "neutral")


def _key(s: SessionIn) -> str:
    return (s.domain or s.app or "unknown").lower()


def fmt_hm(seconds: int) -> str:
    h, m = divmod(round(seconds / 60), 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


def analyse(day: date, tz: str, sessions: list[SessionIn], meetings: list[MeetingIn], shift: Shift) -> dict:
    zone = ZoneInfo(tz)
    d = _Day(datetime.combine(day, time.min, zone))
    sessions = sorted(sessions, key=lambda s: s.started_at)
    for s in sessions:
        a, b = d.idx(s.started_at), d.idx(s.ended_at)
        d.labels[a:b] = [_label(s)] * (b - a)
    session_labels = list(d.labels)  # before meetings overwrite anything

    # --- meetings ------------------------------------------------------------------------------------
    meeting_rows, counted = [], []
    for m in sorted(meetings, key=lambda m: m.started_at):
        a, b = d.idx(m.started_at), d.idx(m.ended_at)
        dur = b - a
        if dur <= 0:
            continue
        c = Counter(session_labels[a:b])
        meet, passive = c["meeting"], sum(c[k] for k in PASSIVE) + c["none"]
        other = sum(c[k] for k in OTHER_ACTIVE)
        if m.attended is True:
            status = "confirmed"
        elif m.attended is False:
            status = "not_attended"
        elif meet >= 0.3 * dur or meet + passive >= 0.5 * dur:
            status = "attended"
        elif other >= 0.8 * dur:
            status = "unclear"  # busy with other work the whole time: ask the person
        else:
            status = "multitasking"
        alongside = Counter()
        for i in range(a, b):
            if session_labels[i] in OTHER_ACTIVE:
                alongside[session_labels[i]] += 1
        row = {"id": m.id, "title": m.title, "start": m.started_at.isoformat(), "end": m.ended_at.isoformat(),
               "duration_s": dur, "attendees": m.attendees, "has_video": m.has_video, "status": status,
               "alongside": dict(alongside)}
        meeting_rows.append(row)
        if status in ("confirmed", "attended", "multitasking"):
            d.labels[a:b] = ["meeting"] * dur
            counted.append((a, b, row))

    # Calls with no calendar event: meeting-class sessions (Meet/Zoom/Teams) outside every counted meeting.
    adhoc, i = [], 0
    while i < DAY_S:
        if session_labels[i] == "meeting" and not any(a <= i < b for a, b, _ in counted):
            j = i
            while j < DAY_S and session_labels[j] == "meeting" and not any(a <= j < b for a, b, _ in counted):
                j += 1
            if j - i >= 120:
                adhoc.append({"start": (d.lo + timedelta(seconds=i)).isoformat(),
                              "end": (d.lo + timedelta(seconds=j)).isoformat(), "duration_s": j - i})
            i = j
        else:
            i += 1

    # --- shift window and break ----------------------------------------------------------------------
    s_lo = d.idx(datetime.combine(day, shift.start, zone))
    s_hi = d.idx(datetime.combine(day, shift.end, zone))
    for i in range(s_lo, s_hi):
        if d.labels[i] == "none":
            d.labels[i] = "away"
    quota = shift.break_minutes * 60
    for kind in ("away", "idle"):
        runs, i = [], s_lo
        while i < s_hi:
            if d.labels[i] == kind:
                j = i
                while j < s_hi and d.labels[j] == kind:
                    j += 1
                runs.append((j - i, i, j))
                i = j
            else:
                i += 1
        for length, a, b in sorted(runs, reverse=True):
            if quota <= 0:
                break
            take = min(length, quota)
            d.labels[a:a + take] = ["break"] * take
            quota -= take

    shift_counts = Counter(d.labels[s_lo:s_hi])
    breakdown = {k: shift_counts.get(k, 0) for k in BUCKETS}
    shift_s = s_hi - s_lo
    before = sum(1 for x in d.labels[:s_lo] if x in ACTIVE)
    after = sum(1 for x in d.labels[s_hi:] if x in ACTIVE)

    # --- hour by hour --------------------------------------------------------------------------------
    hours = []
    for h in range(24):
        c = Counter(d.labels[h * 3600:(h + 1) * 3600])
        in_shift = s_lo < (h + 1) * 3600 and h * 3600 < s_hi
        if in_shift or any(c[k] for k in ACTIVE):
            hours.append({"hour": h, "in_shift": in_shift, **{k: c.get(k, 0) for k in BUCKETS}})

    # --- time sinks ----------------------------------------------------------------------------------
    by_target: dict[str, dict] = {}
    for s in sessions:
        if _label(s) not in ACTIVE:
            continue
        t = by_target.setdefault(_key(s), {"target": _key(s), "app": s.app, "domain": s.domain, "seconds": 0,
                                           "klass": s.klass, "category": s.category, "sessions": 0})
        t["seconds"] += int((s.ended_at - s.started_at).total_seconds())
        t["sessions"] += 1
    top_targets = sorted(by_target.values(), key=lambda t: -t["seconds"])[:10]
    long_low = sorted(
        ({"target": _key(s), "title": s.title, "klass": s.klass, "start": s.started_at.isoformat(),
          "seconds": int((s.ended_at - s.started_at).total_seconds())}
         for s in sessions if s.klass in ("non_work", "neutral")),
        key=lambda x: -x["seconds"])
    long_low = [x for x in long_low if x["seconds"] >= 300][:5]

    # --- focus and switching -------------------------------------------------------------------------
    blocks: list[list] = []
    for s in sessions:
        if s.klass != "productive":
            continue
        if blocks and (s.started_at - blocks[-1][1]).total_seconds() <= FOCUS_GAP_S:
            blocks[-1][1] = max(blocks[-1][1], s.ended_at)
            blocks[-1][2][_key(s)] += int((s.ended_at - s.started_at).total_seconds())
        else:
            blocks.append([s.started_at, s.ended_at, Counter({_key(s): int((s.ended_at - s.started_at).total_seconds())})])
    focus = [{"start": a.isoformat(), "end": b.isoformat(), "seconds": int((b - a).total_seconds()),
              "main": c.most_common(1)[0][0]} for a, b, c in blocks]
    deep = [f for f in focus if f["seconds"] >= FOCUS_MIN_S]
    active_sessions = [s for s in sessions if _label(s) in ACTIVE]
    switches = sum(1 for p, q in zip(active_sessions, active_sessions[1:]) if _key(p) != _key(q))
    active_s = sum(1 for x in session_labels if x in ACTIVE)
    comm = Counter((s.category or "Communication") for s in sessions if s.klass == "communication")

    # --- meeting load --------------------------------------------------------------------------------
    counted.sort()
    b2b = sum(1 for (_, b1, _), (a2, _, _) in zip(counted, counted[1:]) if a2 - b1 <= BACK_TO_BACK_S)
    short_gaps = [a2 - b1 for (_, b1, _), (a2, _, _) in zip(counted, counted[1:]) if BACK_TO_BACK_S < a2 - b1 <= SHORT_GAP_S]
    meeting_s = breakdown["meeting"]

    return {
        "day": day.isoformat(), "timezone": tz,
        "shift": {"start": shift.start.strftime("%H:%M"), "end": shift.end.strftime("%H:%M"),
                  "break_minutes": shift.break_minutes, "seconds": shift_s},
        "breakdown": breakdown,
        "expected_work_s": max(0, shift_s - shift.break_minutes * 60),
        "worked_in_shift_s": sum(breakdown[k] for k in ACTIVE),
        "overtime": {"before_s": before, "after_s": after},
        "active_s": active_s,
        "hours": hours,
        "top_targets": top_targets,
        "long_low_value": long_low,
        "focus": {"blocks": focus, "deep_blocks": len(deep), "deep_s": sum(f["seconds"] for f in deep),
                  "longest": max(focus, key=lambda f: f["seconds"]) if focus else None},
        "switching": {"switches": switches,
                      "per_hour": round(switches / (active_s / 3600), 1) if active_s >= 600 else 0.0},
        "communication_checks": dict(comm),
        "meetings": meeting_rows,
        "adhoc_calls": adhoc,
        "meeting_load": {"count": len(counted), "seconds": meeting_s,
                         "pct_of_shift": round(100 * meeting_s / shift_s, 1) if shift_s else 0.0,
                         "back_to_back": b2b, "short_gaps": len(short_gaps), "short_gap_s": sum(short_gaps)},
    }


COMPARE_KEYS = {
    "productive": lambda a: a["breakdown"]["productive"],
    "meeting": lambda a: a["breakdown"]["meeting"],
    "communication": lambda a: a["breakdown"]["communication"],
    "non_work": lambda a: a["breakdown"]["non_work"],
    "idle": lambda a: a["breakdown"]["idle"],
    "deep_focus": lambda a: a["focus"]["deep_s"],
    "switches_per_hour": lambda a: a["switching"]["per_hour"],
}


def compare(today: dict, history: list[dict], team: list[dict]) -> dict:
    """Today against the person's recent days and the team's same day. Flags differences that matter:
    at least 15 minutes and 25 % for time, or 25 % for rates."""
    out = {}
    for k, f in COMPARE_KEYS.items():
        v = f(today)
        avg7 = round(sum(f(h) for h in history) / len(history), 1) if history else None
        team_avg = round(sum(f(t) for t in team) / len(team), 1) if team else None
        flag = None
        for ref, name in ((avg7, "usual"), (team_avg, "team")):
            if ref is None:
                continue
            diff = v - ref
            big = abs(diff) >= 0.25 * max(ref, 1) and (k == "switches_per_hour" or abs(diff) >= 900)
            if big and flag is None:
                flag = {"vs": name, "direction": "higher" if diff > 0 else "lower", "diff": round(diff, 1)}
        out[k] = {"value": v, "avg_7d": avg7, "team_avg": team_avg, "flag": flag}
    return out
