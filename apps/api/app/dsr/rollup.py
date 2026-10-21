"""Summaries above one person-day: a team's day, and a person's or team's week or month."""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import levels
from app.ai.llm import get_llm
from app.analysis.engine import fmt_hm
from app.models import DayAnalysis, DsrReport, Summary, Team, User


def members(db: Session, team_id: int) -> list[User]:
    return list(db.scalars(select(User).where(User.team_id == team_id, User.active.is_(True)).order_by(User.name)))


def person_brief(db: Session, u: User, day: date) -> dict:
    dsr = db.scalar(select(DsrReport).where(DsrReport.user_id == u.id, DsrReport.day == day))
    an = db.get(DayAnalysis, (u.id, day))
    a = an.data if an else None
    return {
        "name": u.name, "report": dsr.status if dsr else "none",
        "tasks": [{"title": t["title"], "time": fmt_hm(t["seconds"]), "status": t["status"]}
                  for t in (dsr.content["tasks"] if dsr else [])][:8],
        "highlights": dsr.content.get("highlights", []) if dsr else [],
        "blockers": dsr.content.get("blockers", []) if dsr else [],
        "time": ({k: fmt_hm(v) for k, v in a["breakdown"].items() if v} if a else {}),
        "overtime": fmt_hm(a["overtime"]["before_s"] + a["overtime"]["after_s"]) if a else "0m",
        "meeting_pct_of_shift": a["meeting_load"]["pct_of_shift"] if a else 0,
    }


def _tickets(people: list[dict]) -> set[str]:
    import re
    found = set()
    for p in people:
        for t in p.get("tasks", []):
            found |= set(re.findall(r"#0*(\d+)", t["title"]))
    return found


def _save(db: Session, scope: str, scope_id: int, period: str, start: date, content: dict) -> Summary:
    row = db.scalar(select(Summary).where(Summary.scope == scope, Summary.scope_id == scope_id,
                                          Summary.period == period, Summary.start_day == start))
    row = row or Summary(scope=scope, scope_id=scope_id, period=period, start_day=start)
    row.content = content
    db.add(row)
    db.commit()
    return row


def team_day(db: Session, team: Team, day: date) -> Summary:
    llm, model = get_llm(db)
    people = [person_brief(db, u, day) for u in members(db, team.id)]
    working = [p for p in people if p["tasks"] or p["time"]]
    fallback = f"{len(working)} of {len(people)} people have tracked work on {day.isoformat()}. " + " ".join(
        f"{p['name']}: {', '.join(t['title'] for t in p['tasks'][:3]) or 'no report yet'}." for p in working)
    out, status = levels.rollup(db, llm, model, "team", {"team": team.name, "day": day.isoformat(), "people": people},
                                _tickets(people), fallback)
    return _save(db, "team", team.id, "day", day, {**out, "ai_status": status, "people": len(people)})


def period_bounds(period: str, start: date) -> tuple[date, date]:
    if period == "week":
        start = start - timedelta(days=start.weekday())
        return start, start + timedelta(days=7)
    first = start.replace(day=1)
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first, nxt


def period_summary(db: Session, scope: str, scope_id: int, period: str, start: date) -> Summary:
    llm, model = get_llm(db)
    lo, hi = period_bounds(period, start)
    days = []
    if scope == "user":
        u = db.get(User, scope_id)
        d = lo
        while d < hi:
            b = person_brief(db, u, d)
            if b["tasks"] or b["time"]:
                days.append({"day": d.isoformat(), **b})
            d += timedelta(days=1)
        name = u.name
    else:
        team = db.get(Team, scope_id)
        name = team.name
        for s in db.scalars(select(Summary).where(Summary.scope == "team", Summary.scope_id == scope_id,
                                                  Summary.period == "day", Summary.start_day >= lo,
                                                  Summary.start_day < hi).order_by(Summary.start_day)):
            days.append({"day": s.start_day.isoformat(), "summary": s.content.get("summary", ""),
                         "risks": s.content.get("risks", [])})
    fallback = f"{name}: {len(days)} working days recorded from {lo.isoformat()}."
    tickets = _tickets([d for d in days if "tasks" in d])
    out, status = levels.rollup(db, llm, model, "week",
                                {"who": name, "period": period, "from": lo.isoformat(), "days": days}, tickets, fallback)
    return _save(db, scope, scope_id, period, lo, {**out, "ai_status": status, "days": len(days)})
