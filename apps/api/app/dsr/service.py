"""One person-day, end to end: sessions -> analysis -> blocks -> item/section summaries -> DSR draft.

Code computes every fact and number; the AI levels (app.ai.levels) only write text about them.
"""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import levels
from app.ai.llm import get_llm
from app.analysis.engine import MeetingIn, SessionIn, Shift, analyse, compare, fmt_hm
from app.clients.attribution import by_client
from app.clients.resolve import Resolver
from app.dsr.blocks import build_blocks, work_output
from app.models import (ActivitySession, CalendarEvent, Category, DayAnalysis, DsrReport, ManualEntry,
                        SuggestionFeedback, Team, User, WorkAction)
from app.pipeline.rebuild import rebuild_day, user_timezone

SECTION_OF = {"ticket": "tickets", "email_thread": "email", "doc": "docs", "meeting": "meetings", "block": "focus"}


def shift_for(db: Session, user: User) -> Shift:
    team = db.get(Team, user.team_id) if user.team_id else None
    return Shift(team.shift_start, team.shift_end, team.break_minutes) if team else Shift()


def _sessions(db: Session, user: User, day: date, rebuild: bool) -> list[ActivitySession]:
    if rebuild:
        rebuild_day(db, user, day)
    names = dict(db.execute(select(Category.id, Category.name)).all())
    rows = db.scalars(select(ActivitySession).where(ActivitySession.user_id == user.id, ActivitySession.day == day)
                      .order_by(ActivitySession.started_at)).all()
    for r in rows:
        r.category = names.get(r.category_id)  # transient attribute used by blocks and analysis
    return list(rows)


def compute_day(db: Session, user: User, day: date, rebuild: bool = True) -> dict:
    tz = user_timezone(db, user)
    sessions = _sessions(db, user, day, rebuild)
    events = db.scalars(select(CalendarEvent).where(CalendarEvent.user_id == user.id, CalendarEvent.day == day)
                        .order_by(CalendarEvent.started_at)).all()
    actions = db.scalars(select(WorkAction).where(WorkAction.user_id == user.id, WorkAction.day == day)
                         .order_by(WorkAction.at)).all()
    manual = db.scalars(select(ManualEntry).where(ManualEntry.user_id == user.id, ManualEntry.day == day)
                        .order_by(ManualEntry.started_at)).all()
    resolver = Resolver(db)
    # Logged off-PC work counts like tracked activity: calls and meetings as meetings, the rest as productive.
    manual_in = [SessionIn(m.started_at, m.ended_at, "meeting" if m.kind in ("call", "meeting") else "productive",
                           None, None, m.title, "Manual entry") for m in manual]
    analysis = analyse(day, tz,
                       [SessionIn(s.started_at, s.ended_at, s.klass, s.app, s.domain, s.title, s.category) for s in sessions]
                       + manual_in,
                       [MeetingIn(e.id, e.title, e.started_at, e.ended_at, e.attendees, e.has_video, e.attended) for e in events],
                       shift_for(db, user))
    analysis["by_client"] = by_client(resolver, sessions, events, actions, manual, analysis["meetings"])
    output = work_output(actions)
    if output:
        hours = analysis["breakdown"]["productive"] / 3600
        analysis["output_per_productive_hour"] = round(len(actions) / hours, 1) if hours >= 0.5 else None
    analysis["work_output"] = output
    row = db.get(DayAnalysis, (user.id, day)) or DayAnalysis(user_id=user.id, day=day)
    row.data = analysis
    db.add(row)
    db.commit()
    blocks, nonwork = build_blocks(sessions, resolver.names)
    for i, m in enumerate(manual, 1):
        secs = int((m.ended_at - m.started_at).total_seconds())
        blocks.append({"id": f"m{i}", "key": f"manual:{m.id}", "kind": "manual", "label": m.title,
                       "category": "Manual entry", "klass": "meeting" if m.kind in ("call", "meeting") else "productive",
                       "seconds": secs, "minutes": round(secs / 60), "sessions": 1, "first": m.started_at.isoformat(),
                       "last": m.ended_at.isoformat(), "ticket_id": None, "client": resolver.name(m.client_id),
                       "titles": [m.note] if m.note else [], "sections": []})
    return {"tz": tz, "sessions": sessions, "events": events, "actions": actions, "analysis": analysis,
            "blocks": blocks, "nonwork": nonwork, "work_output": output, "manual": manual, "resolver": resolver}


def comparison(db: Session, user: User, day: date, analysis: dict) -> dict:
    hist = db.scalars(select(DayAnalysis.data).where(DayAnalysis.user_id == user.id, DayAnalysis.day < day,
                                                      DayAnalysis.day >= day - timedelta(days=14))
                      .order_by(DayAnalysis.day.desc())).all()
    hist = [h for h in hist if h.get("active_s", 0) >= 3600][:7]  # working days only
    team = []
    if user.team_id:
        mates = select(User.id).where(User.team_id == user.team_id, User.id != user.id, User.active.is_(True))
        team = [t for t in db.scalars(select(DayAnalysis.data).where(DayAnalysis.day == day,
                                                                      DayAnalysis.user_id.in_(mates))) if t.get("active_s", 0) >= 3600]
    return compare(analysis, hist, team)


def _hm_local(at: datetime, tz: str) -> str:
    return at.astimezone(ZoneInfo(tz)).strftime("%H:%M")


def build_items(day_data: dict) -> list[dict]:
    tz, blocks = day_data["tz"], day_data["blocks"]
    ticket_secs = defaultdict(int)
    for b in blocks:
        if b.get("ticket_id"):
            ticket_secs[b["ticket_id"]] += b["seconds"]
    items: list[dict] = []
    by_obj = defaultdict(list)
    for a in day_data["actions"]:
        by_obj[(a.source, a.object_id)].append(a)
    for (source, oid), acts in by_obj.items():
        if source == "mantis":
            items.append({"kind": "ticket", "id": oid, "title": acts[0].object_title,
                          "actions": [{"action": a.action, "at": _hm_local(a.at, tz),
                                       **({"note": a.meta.get("note_text", "")[:600]} if a.meta.get("note_text") else {}),
                                       **({"to": a.meta["to"]} if a.meta.get("to") else {})} for a in acts],
                          "time": fmt_hm(ticket_secs[oid]) if ticket_secs.get(oid) else None})
        elif source == "gmail":
            items.append({"kind": "email_thread", "id": oid, "subject": acts[0].object_title,
                          "sent": len(acts), "replies": sum(1 for a in acts if a.action == "replied"),
                          "to_domains": sorted({d for a in acts for d in a.meta.get("to_domains", [])}),
                          "snippets": [a.meta.get("snippet", "") for a in acts[-2:]]})
        elif source == "drive":
            title = acts[0].object_title
            secs = sum(b["seconds"] for b in blocks if b["kind"] == "doc" and b["label"].lower() == title.lower())
            items.append({"kind": "doc", "id": oid, "title": title, "actions": sorted({a.action for a in acts}),
                          "time": fmt_hm(secs) if secs else None})
    for t, secs in ticket_secs.items():  # tickets viewed in the browser with no recorded action
        if ("mantis", t) not in by_obj:
            b = next(b for b in blocks if b.get("ticket_id") == t)
            items.append({"kind": "ticket", "id": t, "title": b["label"], "actions": [], "time": fmt_hm(secs)})
    for m in day_data["analysis"]["meetings"]:
        if m["status"] in ("confirmed", "attended", "multitasking"):
            items.append({"kind": "meeting", "id": str(m["id"]), "title": m["title"], "duration": fmt_hm(m["duration_s"]),
                          "attendees": m["attendees"], "status": m["status"]})
    for b in blocks:
        if b["kind"] in ("app", "repo", "misc", "doc") and b["klass"] == "productive" and b["seconds"] >= 600:
            items.append({"kind": "block", "id": b["id"], "label": b["label"], "time": fmt_hm(b["seconds"]),
                          "titles": b["titles"][:4]})
    return items


def tickets_of(day_data: dict) -> set[str]:
    out = {a.object_id for a in day_data["actions"] if a.source == "mantis"}
    out |= {b["ticket_id"] for b in day_data["blocks"] if b.get("ticket_id")}
    return {t.lstrip("0") for t in out}


def warm_items(db: Session, user: User, day: date) -> int:
    """Summarise new or changed items during the day, so the end-of-day report only runs the upper levels."""
    llm, model = get_llm(db)
    if llm is None:
        return 0
    d = compute_day(db, user, day, rebuild=False)
    tickets = tickets_of(d)
    items = build_items(d)
    for it in items:
        levels.summarise_item(db, llm, model, it, tickets)  # cached by content, so repeats are free
    return len(items)


def focus_brief(a: dict, tz: str) -> dict:
    f = a["focus"]
    longest = f["longest"]
    return {"deep_focus_blocks": f["deep_blocks"], "deep_focus_time": fmt_hm(f["deep_s"]),
            "longest_focus": ({"time": fmt_hm(longest["seconds"]), "on": longest["main"],
                               "from": _hm_local(datetime.fromisoformat(longest["start"]), tz)} if longest else None)}


def meeting_brief(a: dict) -> dict:
    m = a["meeting_load"]
    return {"count": m["count"], "time": fmt_hm(m["seconds"]), "share_of_shift": f"{m['pct_of_shift']:.0f}%",
            "back_to_back": m["back_to_back"], "short_gaps_between": m["short_gaps"]}


def observations(a: dict, cmp: dict) -> list[dict]:
    """Facts worth acting on, measured by code; the model only chooses among them and words the advice."""
    bd, out = a["breakdown"], []

    def add(metric: str, text: str, advice: str) -> None:
        out.append({"metric": metric, "observation": text, "advice": advice})

    checks = sum(a["communication_checks"].values())
    if checks >= 15:
        add("communication_checks", f"Email and chat were opened {checks} times ({fmt_hm(bd['communication'])} in total).",
            f"Email and chat were opened {checks} times. Checking them at set times (mid-morning, after lunch, "
            "end of day) leaves longer stretches for focused work.")
    f = a["focus"]
    if f["deep_s"] < 3600 and bd["productive"] >= 3600:
        add("deep_focus", f"Only {fmt_hm(f['deep_s'])} of {fmt_hm(bd['productive'])} productive time was in focus "
            "blocks of 25m or more.",
            f"Only {fmt_hm(f['deep_s'])} was in focus blocks of 25m or more. Blocking one quiet hour in the "
            "calendar protects focused work.")
    elif f["longest"] and f["longest"]["seconds"] >= 5400:
        add("deep_focus", f"The longest focus block was {fmt_hm(f['longest']['seconds'])} on {f['longest']['main']}.",
            f"The {fmt_hm(f['longest']['seconds'])} focus block on {f['longest']['main']} worked well; planning the "
            "hardest task for the same time of day can repeat it.")
    m = a["meeting_load"]
    if m["pct_of_shift"] >= 30:
        add("meeting_load", f"Meetings took {m['pct_of_shift']:.0f}% of the shift ({fmt_hm(m['seconds'])}).",
            f"Meetings took {m['pct_of_shift']:.0f}% of the shift. Checking which ones need you, or shortening "
            "recurring ones, frees time for delivery.")
    if m["back_to_back"] >= 2:
        add("meeting_load", f"{m['back_to_back']} meetings ran back to back.",
            f"{m['back_to_back']} meetings ran back to back; a 5m gap between them helps with notes and follow-ups.")
    if m["short_gaps"] >= 2:
        add("meeting_load", f"{m['short_gaps']} gaps of 5m-30m between meetings ({fmt_hm(m['short_gap_s'])} in total).",
            f"{m['short_gaps']} short gaps between meetings added up to {fmt_hm(m['short_gap_s'])}; grouping "
            "meetings together turns that into one usable block.")
    if bd["non_work"] >= 1800:
        top = next((t for t in a["top_targets"] if t["klass"] == "non_work"), None)
        where = f" (most on {top['target']}, {fmt_hm(top['seconds'])})." if top else "."
        add("non_work", f"Non-work sites took {fmt_hm(bd['non_work'])}{where}",
            f"Non-work sites took {fmt_hm(bd['non_work'])} of the shift; keeping them for the break keeps the day on track.")
    ot = a["overtime"]["before_s"] + a["overtime"]["after_s"]
    if ot >= 1800:
        add("overtime", f"{fmt_hm(ot)} of work happened outside the shift.",
            f"{fmt_hm(ot)} of work happened outside the shift. If this is regular, raise the workload with your manager.")
    if bd["idle"] >= 2700:
        add("idle", f"{fmt_hm(bd['idle'])} idle at the desk during the shift.",
            f"{fmt_hm(bd['idle'])} was idle at the desk. If that was reading or calls away from the PC, add a note "
            "to the report.")
    if a["switching"]["per_hour"] >= 20:
        add("switches_per_hour", f"Switched app or site {a['switching']['per_hour']} times per hour.",
            f"Switching {a['switching']['per_hour']} times per hour breaks concentration; closing unused tabs and "
            "notifications during focus time helps.")
    for k, v in cmp.items():
        if v["flag"] and k in ("productive", "meeting", "communication", "non_work") and v["avg_7d"] is not None:
            add(k, f"{k.replace('_', '-').capitalize()} time was {fmt_hm(v['value'])}, {v['flag']['direction']} "
                   f"than usual ({fmt_hm(v['avg_7d'])}).", "")
    if not out:
        add("productive", f"{fmt_hm(bd['productive'])} of the shift was productive work.",
            f"A steady day: {fmt_hm(bd['productive'])} of productive work. Keep the same rhythm tomorrow.")
    return out


STANDARD_MIN_S = 300


def standard_tasks(d: dict, sections: dict) -> list[dict]:
    """Email & chat, meetings, and admin/research as fixed tasks; the AI section summaries describe them."""
    a, out = d["analysis"], []
    by = {k: [b for b in d["blocks"] if b["klass"] == k] for k in ("communication", "meeting", "neutral")}
    meeting_s = max(a["breakdown"]["meeting"], sum(b["seconds"] for b in by["meeting"]))
    if meeting_s >= STANDARD_MIN_S:
        titles = [m["title"] for m in a["meetings"] if m["status"] in ("confirmed", "attended", "multitasking")]
        out.append({"title": "Meetings and calls", "block_ids": [b["id"] for b in by["meeting"]], "seconds": meeting_s,
                    "category": "Meetings/Calls", "status": "done",
                    "summary": sections.get("meetings") or (", ".join(titles) + "." if titles else "Calls.")})
    comm_s = sum(b["seconds"] for b in by["communication"])
    if comm_s >= STANDARD_MIN_S:
        g = d["work_output"].get("gmail", {})
        sent = g.get("replied", 0) + g.get("new_thread", 0)
        code_text = ", ".join(f"{b['label']} {fmt_hm(b['seconds'])}" for b in by["communication"][:4]) + "."
        per_client = [r for r in a.get("by_client", {}).get("rows", []) if r["client_id"] and (r["email_s"] or r["emails_sent"])]
        client_text = "; ".join(f"{r['client']} {fmt_hm(r['email_s'])} ({r['emails_sent']} sent)" for r in per_client[:6])
        summary = sections.get("email") or (f"{sent} emails sent. {code_text}" if sent else code_text)
        out.append({"title": "Email and chat", "block_ids": [b["id"] for b in by["communication"]], "seconds": comm_s,
                    "category": "Email", "status": "done",
                    "summary": (f"By client: {client_text}. " if client_text else "") + summary})
    neutral_s = sum(b["seconds"] for b in by["neutral"])
    if neutral_s >= STANDARD_MIN_S:
        names = ", ".join(b["label"] for b in sorted(by["neutral"], key=lambda b: -b["seconds"])[:4])
        out.append({"title": "Admin and research", "block_ids": [b["id"] for b in by["neutral"]], "seconds": neutral_s,
                    "category": "Admin/Utilities", "status": "done", "summary": f"{names}."})
    return out


def generate(db: Session, user: User, day: date, force: bool = False) -> DsrReport:
    existing = db.scalar(select(DsrReport).where(DsrReport.user_id == user.id, DsrReport.day == day))
    if existing and existing.status != "draft" and not force:
        return existing  # never overwrite what the person submitted
    llm, model = get_llm(db)
    d = compute_day(db, user, day)
    tickets = tickets_of(d)
    statuses = []

    items = build_items(d)
    item_summaries = {}
    for it in items:
        text, st = levels.summarise_item(db, llm, model, it, tickets)
        item_summaries[f"{it['kind']}:{it['id']}"] = text
        statuses.append(st)
    sections = {}
    out = d["work_output"]
    for name in ("tickets", "email", "docs", "meetings", "focus"):
        texts = [item_summaries[f"{it['kind']}:{it['id']}"] for it in items if SECTION_OF[it["kind"]] == name]
        a0 = d["analysis"]
        counts = {"tickets": out.get("mantis", {}), "email": out.get("gmail", {}), "docs": out.get("drive", {}),
                  "meetings": meeting_brief(a0), "focus": focus_brief(a0, d["tz"])}[name]
        sections[name], st = levels.summarise_section(db, llm, model, name, texts, counts, tickets)
        statuses.append(st)

    a = d["analysis"]
    # The model only ever sees durations already written as 1h18m / 45m, so it has nothing to convert.
    analysis_brief = {
        "shift": f"{a['shift']['start']}-{a['shift']['end']}, {a['shift']['break_minutes']}m break",
        "time": {k: fmt_hm(v) for k, v in a["breakdown"].items() if v},
        "overtime": fmt_hm(a["overtime"]["before_s"] + a["overtime"]["after_s"]),
        **focus_brief(a, d["tz"]), "switches_per_hour": a["switching"]["per_hour"], "meetings": meeting_brief(a),
        "top_apps_and_sites": [{"target": t["target"], "time": fmt_hm(t["seconds"])} for t in a["top_targets"][:5]],
    }
    work_blocks = [b for b in d["blocks"] if b["klass"] == "productive"]
    yesterday = db.scalar(select(DsrReport).where(DsrReport.user_id == user.id, DsrReport.day < day)
                          .order_by(DsrReport.day.desc()).limit(1))
    payload = {
        "person": user.name, "day": day.isoformat(),
        "all_block_ids": [b["id"] for b in work_blocks],
        "blocks": [{"id": b["id"], "label": b["label"], "kind": b["kind"], "category": b["category"],
                    "client": b.get("client"), "sections": b.get("sections", [])[:3],
                    "time": fmt_hm(b["seconds"]), "ticket": b["ticket_id"], "titles": b["titles"][:3]} for b in work_blocks],
        "time_by_client": [{"client": r["client"], "time": fmt_hm(r["total_s"])}
                           for r in a.get("by_client", {}).get("rows", [])[:8]],
        "sections": {k: v for k, v in sections.items() if v},
        "meetings": [{"title": m["title"], "duration": fmt_hm(m["duration_s"]), "status": m["status"]} for m in a["meetings"]],
        "work_output": out, "analysis": analysis_brief,
        "yesterday_tomorrow": (yesterday.content.get("tomorrow", []) if yesterday else []),
    }
    report, st = levels.write_dsr(db, llm, model, payload, work_blocks, a, tickets)
    statuses.append(st)

    cmp = comparison(db, user, day, a)
    feedback = db.scalars(select(SuggestionFeedback).where(SuggestionFeedback.user_id == user.id)
                          .order_by(SuggestionFeedback.id.desc()).limit(10)).all()
    obs = observations(a, cmp)
    suggestions, st = levels.suggest(db, llm, model, {
        "observations": obs, "feedback": [{"text": f.text, "useful": f.useful} for f in feedback]}, tickets)
    statuses.append(st)
    # Top up to three with code-written advice on observations the model left out.
    unhelpful = {f.text for f in feedback if not f.useful}
    covered = {s["metric"] for s in suggestions}
    for o in obs:
        if len(suggestions) >= 3:
            break
        if o["advice"] and o["metric"] not in covered and o["advice"] not in unhelpful:
            suggestions.append({"metric": o["metric"], "text": o["advice"]})
            covered.add(o["metric"])

    block_by_id = {b["id"]: b for b in d["blocks"]}
    tasks = []
    for t in report["tasks"] + standard_tasks(d, sections):
        bl = [block_by_id[b] for b in t["block_ids"] if b in block_by_id]
        main = max(bl, key=lambda b: b["seconds"]) if bl else None
        tasks.append({**t, "id": f"t{len(tasks) + 1}",
                      "seconds": t.get("seconds") or sum(b["seconds"] for b in bl),
                      "client": t.get("client") or (main.get("client") if main else None),
                      "category": t.get("category") or (main["category"] if main else None),
                      "refs": sorted({b["ticket_id"] for b in bl if b.get("ticket_id")})})
    content = {
        "time_by_client": a.get("by_client", {}).get("rows", []),
        "tasks": tasks, "highlights": report["highlights"], "blockers": report["blockers"],
        "tomorrow": report["tomorrow"], "insights": report["insights"], "suggestions": suggestions,
        "sections": sections, "items": item_summaries,
        "meetings": [{k: m[k] for k in ("id", "title", "start", "end", "duration_s", "status")} for m in a["meetings"]],
        "work_output": out,
    }
    ran = [s for s in statuses if s != "skip"]  # steps with nothing to summarise don't count either way
    ai_status = "fallback" if llm is None or all(s == "fallback" for s in ran) else (
        "ok" if all(s == "ok" for s in ran) else "partial")
    row = existing or DsrReport(user_id=user.id, day=day)
    row.content, row.original, row.ai_status, row.model = content, content, ai_status, model
    row.facts = {"blocks": d["blocks"], "nonwork": d["nonwork"], "items": items}
    row.status, row.generated_at = "draft", datetime.now(UTC)
    db.add(row)
    db.commit()
    return row
