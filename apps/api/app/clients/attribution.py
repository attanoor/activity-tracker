"""Time and work output per client for one person-day. Code only; the AI just writes about the result.

Each active session gets one client and one channel:
  channel  meetings (calls) | email | tickets | web (websites, backoffice, apps) | manual (logged off-PC work)
  client   the session's own client (domain / club on page / ticket); for email, the open thread's participants;
           for time inside a counted calendar meeting, the meeting's attendees.
Counted calendar meeting time with no PC activity (a room or phone meeting) is added to that meeting's client.
"""

from collections import Counter, defaultdict
from datetime import datetime

from app.clients.email_time import subject_from_title, thread_participants
from app.clients.resolve import Resolver
from app.dsr.blocks import ticket_of

ACTIVE = {"productive", "meeting", "communication", "neutral", "non_work"}
CHANNELS = ("web", "email", "tickets", "meetings", "manual")
COUNTED = {"confirmed", "attended", "multitasking"}


def _overlap(a1: datetime, a2: datetime, b1: datetime, b2: datetime) -> float:
    return max(0.0, (min(a2, b2) - max(a1, b1)).total_seconds())


def _channel(s) -> str:
    if s.klass == "meeting":
        return "meetings"
    if s.domain in ("mail.google.com", "outlook.office.com", "outlook.live.com") or (s.app or "").lower() == "outlook.exe":
        return "email"
    if ticket_of(s.title, s.paths, s.domain):
        return "tickets"
    return "web"


def by_client(resolver: Resolver, sessions, events, actions, manual, meetings_analysis: list[dict]) -> dict:
    threads = thread_participants(actions)
    counted = {m["id"] for m in meetings_analysis if m["status"] in COUNTED}
    meeting_rows = [e for e in events if e.id in counted]
    meeting_client = {e.id: resolver.by_domains(list(e.attendee_domains or [])) for e in meeting_rows}

    rows: dict = defaultdict(lambda: {**{c: 0 for c in CHANNELS}, "emails_sent": 0, "emails_received": 0,
                                       "ticket_actions": Counter(), "issue_types": Counter(), "ticket_ids": set(),
                                       "sections": Counter()})
    covered: dict[int, float] = defaultdict(float)  # meeting id -> seconds already covered by sessions

    for s in sessions:
        if s.klass not in ACTIVE:
            continue
        channel, client = _channel(s), s.client_id
        if channel == "email" and not client:
            subj = subject_from_title(s.title)
            if subj and subj in threads:
                client = resolver.by_emails(threads[subj])
        for e in meeting_rows:
            ov = _overlap(s.started_at, s.ended_at, e.started_at, e.ended_at)
            if ov:
                covered[e.id] += ov
                if ov >= 0.5 * s.duration_s and channel != "email":
                    # A meeting with a client's people is that client's time, whatever page was open.
                    channel, client = "meetings", meeting_client[e.id] or client
        r = rows[client]
        r[channel] += s.duration_s
        if getattr(s, "section", None):
            r["sections"][s.section] += s.duration_s

    for e in meeting_rows:  # meeting time without PC activity (room or phone)
        rest = (e.ended_at - e.started_at).total_seconds() - covered[e.id]
        if rest > 60:
            rows[meeting_client[e.id]]["meetings"] += int(rest)

    for m in manual:
        rows[m.client_id]["manual"] += int((m.ended_at - m.started_at).total_seconds())

    for a in actions:
        if a.source == "mantis":
            client = resolver.by_project(a.meta.get("project")) or resolver.by_ticket(a.object_id)
            r = rows[client]
            r["ticket_actions"][a.action] += 1
            r["ticket_ids"].add(a.object_id)
            if a.action == "reported":
                r["issue_types"][a.meta.get("category") or "Uncategorised"] += 1
        elif a.source == "gmail":
            people = [p.get("email", "") for f in ("from", "to", "cc") for p in (a.meta.get(f) or []) if isinstance(p, dict)]
            client = resolver.by_emails(people)
            rows[client]["emails_received" if a.action == "received" else "emails_sent"] += 1

    out = []
    for cid, r in rows.items():
        total = sum(r[c] for c in CHANNELS)
        if not total and not r["ticket_actions"] and not r["emails_sent"] and not r["emails_received"]:
            continue
        out.append({"client_id": cid, "client": resolver.name(cid) or "No client", "total_s": total,
                    **{f"{c}_s": r[c] for c in CHANNELS},
                    "emails_sent": r["emails_sent"], "emails_received": r["emails_received"],
                    "ticket_actions": dict(r["ticket_actions"]), "tickets": len(r["ticket_ids"]),
                    "issue_types": dict(r["issue_types"]),
                    "top_sections": [s for s, _ in r["sections"].most_common(3)]})
    out.sort(key=lambda x: (x["client_id"] is None, -x["total_s"]))
    return {"rows": out, "total_s": sum(x["total_s"] for x in out),
            "client_s": sum(x["total_s"] for x in out if x["client_id"] is not None)}
