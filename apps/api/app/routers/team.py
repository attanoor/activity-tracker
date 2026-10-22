from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.access import managed_team_ids, target_user, team_for
from app.audit import audit
from app.db import get_db
from app.deps import current_user
from app.dsr import rollup, service
from app.exports import excel
from app.exports.bundle import gather
from app.models import Device, DsrReport, Summary, Team, User
from app.routers.reports import XLSX

router = APIRouter(tags=["team"])


@router.get("/team/teams")
def my_teams(viewer: User = Depends(current_user), db: Session = Depends(get_db)):
    ids = managed_team_ids(db, viewer)
    return [{"id": t.id, "name": t.name} for t in db.scalars(select(Team).where(Team.id.in_(ids)).order_by(Team.name))]


@router.get("/team/{team_id}/members")
def team_members(team_id: int, viewer: User = Depends(current_user), db: Session = Depends(get_db)):
    team = team_for(db, viewer, team_id)
    return [{"id": u.id, "name": u.name} for u in rollup.members(db, team.id)]


def _summary(db: Session, scope: str, scope_id: int, period: str, start: date) -> dict | None:
    s = db.scalar(select(Summary).where(Summary.scope == scope, Summary.scope_id == scope_id,
                                        Summary.period == period, Summary.start_day == start))
    return {"content": s.content, "generated_at": s.generated_at, "start": s.start_day} if s else None


@router.get("/team/{team_id}/day/{day}")
def team_day(team_id: int, day: date, viewer: User = Depends(current_user), db: Session = Depends(get_db)):
    team = team_for(db, viewer, team_id)
    audit(db, viewer.id, "view.team", f"team:{team.id}", {"day": day.isoformat()})
    db.commit()
    seen = dict(db.execute(select(Device.user_id, func.max(Device.last_seen_at)).where(Device.revoked_at.is_(None))
                           .group_by(Device.user_id)).all())
    rows, team_clients = [], {}
    for u in rollup.members(db, team.id):
        a = service.compute_day(db, u, day)["analysis"]
        dsr = db.scalar(select(DsrReport).where(DsrReport.user_id == u.id, DsrReport.day == day))
        bd, wo = a["breakdown"], a.get("work_output", {})
        clients = [r for r in a.get("by_client", {}).get("rows", []) if r["client_id"] is not None]
        for r in clients:
            t = team_clients.setdefault(r["client"], {"client": r["client"], "total_s": 0, "people": 0, "emails_sent": 0,
                                                      "tickets": 0})
            t["total_s"] += r["total_s"]
            t["people"] += 1
            t["emails_sent"] += r["emails_sent"]
            t["tickets"] += r["tickets"]
        rows.append({"id": u.id, "name": u.name, "email": u.email, "breakdown": bd,
                     "clients": [{"client": r["client"], "total_s": r["total_s"]} for r in clients[:3]],
                     "worked_s": sum(bd[k] for k in ("productive", "meeting", "communication", "neutral", "non_work")),
                     "overtime_s": a["overtime"]["before_s"] + a["overtime"]["after_s"],
                     "deep_focus_s": a["focus"]["deep_s"], "meeting_pct": a["meeting_load"]["pct_of_shift"],
                     "tickets": wo.get("mantis", {}).get("tickets", 0),
                     "emails": wo.get("gmail", {}).get("replied", 0) + wo.get("gmail", {}).get("new_thread", 0),
                     "dsr": dsr.status if dsr else None, "ai_status": dsr.ai_status if dsr else None,
                     "last_upload": seen.get(u.id)})
    return {"team": {"id": team.id, "name": team.name, "shift_start": team.shift_start, "shift_end": team.shift_end,
                     "break_minutes": team.break_minutes},
            "day": day, "rows": rows, "summary": _summary(db, "team", team.id, "day", day),
            "by_client": sorted(team_clients.values(), key=lambda x: -x["total_s"])}


@router.post("/team/{team_id}/day/{day}/summary")
def team_day_summary(team_id: int, day: date, viewer: User = Depends(current_user), db: Session = Depends(get_db)):
    team = team_for(db, viewer, team_id)
    s = rollup.team_day(db, team, day)
    return {"content": s.content, "generated_at": s.generated_at, "start": s.start_day}


def _period(period: str) -> str:
    if period not in ("week", "month"):
        raise HTTPException(404, "Period must be week or month")
    return period


@router.get("/team/{team_id}/period/{period}/{start}")
def team_period(team_id: int, period: str, start: date, viewer: User = Depends(current_user), db: Session = Depends(get_db)):
    team = team_for(db, viewer, team_id)
    lo, _ = rollup.period_bounds(_period(period), start)
    return _summary(db, "team", team.id, period, lo)


@router.post("/team/{team_id}/period/{period}/{start}")
def team_period_generate(team_id: int, period: str, start: date, viewer: User = Depends(current_user),
                         db: Session = Depends(get_db)):
    team = team_for(db, viewer, team_id)
    s = rollup.period_summary(db, "team", team.id, _period(period), start)
    return {"content": s.content, "generated_at": s.generated_at, "start": s.start_day}


@router.get("/people/{user_id}/period/{period}/{start}")
def person_period(user_id: int, period: str, start: date, viewer: User = Depends(current_user), db: Session = Depends(get_db)):
    u = target_user(db, viewer, user_id, "period")
    lo, _ = rollup.period_bounds(_period(period), start)
    return _summary(db, "user", u.id, period, lo)


@router.post("/people/{user_id}/period/{period}/{start}")
def person_period_generate(user_id: int, period: str, start: date, viewer: User = Depends(current_user),
                           db: Session = Depends(get_db)):
    u = target_user(db, viewer, user_id, "period")
    s = rollup.period_summary(db, "user", u.id, _period(period), start)
    return {"content": s.content, "generated_at": s.generated_at, "start": s.start_day}


@router.get("/team/{team_id}/day/{day}/export/xlsx")
def team_export(team_id: int, day: date, viewer: User = Depends(current_user), db: Session = Depends(get_db)):
    team = team_for(db, viewer, team_id)
    audit(db, viewer.id, "view.team_export", f"team:{team.id}", {"day": day.isoformat()})
    db.commit()
    bundles = [gather(db, u, day) for u in rollup.members(db, team.id)]
    return Response(excel.dsr_workbook(bundles, team_name=team.name), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="Team-{team.name.replace(" ", "-")}-{day}.xlsx"'})
