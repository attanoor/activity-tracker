"""My Day and DSR endpoints. `/people/{id}/...` serves the same views to that person's manager or an admin."""

import copy
import hashlib
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import settings_store
from app.access import target_user
from app.audit import audit
from app.db import get_db
from app.deps import current_user
from app.dsr import generation, service
from app.exports import excel, pdf
from app.exports.bundle import gather
from app.models import CalendarEvent, DayAnalysis, DsrReport, ExcelTemplate, SuggestionFeedback, User
from app.pipeline.rebuild import user_timezone

router = APIRouter(tags=["reports"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _dsr_out(r: DsrReport | None, db: Session | None = None, user: User | None = None) -> dict | None:
    if not r:
        return None
    lock = {}
    if db is not None and user is not None:
        from app.routers.clients import can_edit_day, edit_deadline
        ok, why = can_edit_day(db, user, r.day)
        lock = {"editable": ok, "locked_reason": why, "edit_deadline": edit_deadline(db, user, r.day),
                "reopened": r.reopened_by is not None}
    return {**lock,"id": r.id, "day": r.day, "status": r.status, "ai_status": r.ai_status, "model": r.model,
            "content": copy.deepcopy(r.content), "edited": r.content != r.original, "generated_at": r.generated_at,
            "submitted_at": r.submitted_at, "sent_at": r.sent_at, "reviewed": r.reviewed}


def _for_manager(db: Session, out: dict) -> dict:
    """Hide email subjects and personal suggestions from managers unless the admin allowed subjects."""
    if not settings_store.get(db, "google")["show_subjects_to_managers"]:
        c = out["content"]
        c["items"] = {k: v for k, v in c.get("items", {}).items() if not k.startswith("email_thread:")}
        if c.get("sections", {}).get("email"):
            g = c.get("work_output", {}).get("gmail", {})
            c["sections"]["email"] = (f"{g.get('replied', 0) + g.get('new_thread', 0)} emails sent "
                                      f"in {g.get('threads', 0)} threads.")
    out["content"].pop("suggestions", None)
    return out


def overview(db: Session, user: User, day: date, viewer: User) -> dict:
    d = service.compute_day(db, user, day)
    dsr = db.scalar(select(DsrReport).where(DsrReport.user_id == user.id, DsrReport.day == day))
    dsr_out = _dsr_out(dsr, db, user)
    if dsr_out and viewer.id != user.id:
        dsr_out = _for_manager(db, dsr_out)
    hide_subjects = viewer.id != user.id and not settings_store.get(db, "google")["show_subjects_to_managers"]
    return {
        "user": {"id": user.id, "name": user.name}, "day": day, "tz": d["tz"],
        "sessions": [{"id": s.id, "start": s.started_at, "end": s.ended_at, "seconds": s.duration_s, "kind": s.kind,
                      "klass": s.klass, "category": s.category, "app": s.app, "domain": s.domain, "title": s.title}
                     for s in d["sessions"]],
        "analysis": d["analysis"], "compare": service.comparison(db, user, day, d["analysis"]),
        "blocks": d["blocks"], "nonwork": d["nonwork"],
        "actions": [{"source": a.source, "action": a.action, "object_id": a.object_id, "at": a.at,
                     "title": "(email)" if hide_subjects and a.source == "gmail" else a.object_title}
                    for a in d["actions"]],
        "work_output": d["work_output"], "dsr": dsr_out,
        "generating": generation.running(user.id, day), "generation_error": generation.error(user.id, day),
    }


@router.get("/me/overview/{day}")
def my_overview(day: date, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return overview(db, user, day, user)


@router.get("/people/{user_id}/overview/{day}")
def person_overview(user_id: int, day: date, viewer: User = Depends(current_user), db: Session = Depends(get_db)):
    return overview(db, target_user(db, viewer, user_id, "day"), day, viewer)


@router.post("/me/dsr/{day}/generate")
def generate(day: date, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Starts writing the report in the background (the model takes about a minute) and returns at once.
    The page polls the overview, whose `generating` flag is true until the draft is saved."""
    from app.routers.clients import can_edit_day
    ok, why = can_edit_day(db, user, day)
    if not ok:
        raise HTTPException(409, why)
    return {"generating": generation.start(user.id, day)}


class TaskEdit(BaseModel):
    id: str
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field("", max_length=600)
    status: str = Field(pattern="^(done|in_progress|blocked)$")


class DsrEdit(BaseModel):
    tasks: list[TaskEdit]
    highlights: list[str] = Field(default_factory=list, max_length=10)
    blockers: list[str] = Field(default_factory=list, max_length=10)
    tomorrow: list[str] = Field(default_factory=list, max_length=10)
    insights: str = Field("", max_length=2000)


def _own_draft(db: Session, user: User, day: date) -> DsrReport:
    from app.routers.clients import can_edit_day
    r = db.scalar(select(DsrReport).where(DsrReport.user_id == user.id, DsrReport.day == day))
    if not r:
        raise HTTPException(404, "No report for this day yet; generate it first")
    ok, why = can_edit_day(db, user, day)
    if not ok:
        raise HTTPException(409, why)
    return r


@router.put("/me/dsr/{day}")
def edit(day: date, body: DsrEdit, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The person may reword, re-status or remove tasks; time and blocks always stay as computed."""
    r = _own_draft(db, user, day)
    by_id = {t["id"]: t for t in r.content["tasks"]}
    if any(t.id not in by_id for t in body.tasks):
        raise HTTPException(422, "Unknown task id; tasks can be edited or removed, not added")
    tasks = [{**by_id[t.id], "title": t.title.strip(), "summary": t.summary.strip(), "status": t.status} for t in body.tasks]
    clean = lambda xs: [x.strip()[:400] for x in xs if x.strip()]  # noqa: E731
    r.content = {**r.content, "tasks": tasks, "highlights": clean(body.highlights), "blockers": clean(body.blockers),
                 "tomorrow": clean(body.tomorrow), "insights": body.insights.strip()}
    db.commit()
    return _dsr_out(r)


@router.post("/me/dsr/{day}/submit")
def submit(day: date, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = _own_draft(db, user, day)
    r.status, r.submitted_at, r.reviewed, r.reopened_by = "submitted", datetime.now(UTC), True, None
    audit(db, user.id, "dsr.submit", f"dsr:{r.id}", {"edited": r.content != r.original})
    db.commit()
    return _dsr_out(r)


@router.post("/people/{user_id}/dsr/{day}/reopen")
def reopen(user_id: int, day: date, viewer: User = Depends(current_user), db: Session = Depends(get_db)):
    """A manager (or admin) reopens a submitted or closed day so the person can correct it."""
    if viewer.role not in ("manager", "admin"):
        raise HTTPException(403, "Only managers can reopen a report")
    u = target_user(db, viewer, user_id, "reopen")
    r = db.scalar(select(DsrReport).where(DsrReport.user_id == u.id, DsrReport.day == day))
    if not r:
        empty = {"tasks": [], "highlights": [], "blockers": [], "tomorrow": [], "insights": "", "suggestions": [],
                 "sections": {}, "items": {}, "meetings": [], "work_output": {}, "time_by_client": []}
        r = DsrReport(user_id=u.id, day=day, content=empty, original=empty, ai_status="fallback")
        db.add(r)
    r.status, r.reopened_by = "draft", viewer.id
    audit(db, viewer.id, "dsr.reopen", f"user:{u.id}", {"day": day.isoformat()})
    db.commit()
    return _dsr_out(r, db, u)


class Attendance(BaseModel):
    attended: bool | None


@router.post("/me/meetings/{event_id}/attendance")
def attendance(event_id: int, body: Attendance, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ev = db.get(CalendarEvent, event_id)
    if not ev or ev.user_id != user.id:
        raise HTTPException(404, "Unknown meeting")
    ev.attended = body.attended
    db.commit()
    return {"id": ev.id, "attended": ev.attended}


class Feedback(BaseModel):
    day: date
    text: str = Field(min_length=1, max_length=600)
    useful: bool


@router.post("/me/suggestions/feedback", status_code=204)
def feedback(body: Feedback, user: User = Depends(current_user), db: Session = Depends(get_db)):
    h = hashlib.sha256(body.text.encode()).hexdigest()
    row = db.scalar(select(SuggestionFeedback).where(SuggestionFeedback.user_id == user.id,
                                                     SuggestionFeedback.day == body.day,
                                                     SuggestionFeedback.text_hash == h))
    row = row or SuggestionFeedback(user_id=user.id, day=body.day, text_hash=h, text=body.text)
    row.useful = body.useful
    db.add(row)
    db.commit()


def _trend(db: Session, user: User, end: date, days: int) -> list[dict]:
    """Per-day breakdowns for the range; days not analysed yet are computed (without forcing a session rebuild
    for days long past, which would only repeat work)."""
    today = datetime.now(UTC).date()
    out = []
    for i in range(days - 1, -1, -1):
        d = end - timedelta(days=i)
        row = db.get(DayAnalysis, (user.id, d))
        if row is None or d >= today - timedelta(days=1):
            data = service.compute_day(db, user, d, rebuild=d >= today - timedelta(days=1) or row is None)["analysis"]
        else:
            data = row.data
        dsr = db.scalar(select(DsrReport.status).where(DsrReport.user_id == user.id, DsrReport.day == d))
        out.append({"day": d, "breakdown": data["breakdown"], "active_s": data["active_s"],
                    "overtime_s": data["overtime"]["before_s"] + data["overtime"]["after_s"],
                    "deep_focus_s": data["focus"]["deep_s"], "switches_per_hour": data["switching"]["per_hour"],
                    "meeting_pct": data["meeting_load"]["pct_of_shift"], "hours": data["hours"],
                    "work_output": data.get("work_output", {}), "dsr": dsr})
    return out


@router.get("/me/trend")
def my_trend(end: date, days: int = 7, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"tz": user_timezone(db, user), "days": _trend(db, user, end, min(max(days, 1), 31))}


@router.get("/people/{user_id}/trend")
def person_trend(user_id: int, end: date, days: int = 7, viewer: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    u = target_user(db, viewer, user_id, "trend")
    return {"tz": user_timezone(db, u), "days": _trend(db, u, end, min(max(days, 1), 31))}


# --- exports -------------------------------------------------------------------------------------------
def _export(db: Session, u: User, day: date, fmt: str, for_manager: bool) -> Response:
    b = gather(db, u, day)
    stem = f"DSR-{u.name.replace(' ', '-')}-{day}"
    if fmt == "pdf":
        return Response(pdf.dsr_pdf(b, for_manager), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{stem}.pdf"'})
    if fmt == "xlsx":
        return Response(excel.dsr_workbook([b]), media_type=XLSX,
                        headers={"Content-Disposition": f'attachment; filename="{stem}.xlsx"'})
    if fmt == "template":
        tpl = db.scalar(select(ExcelTemplate).where(ExcelTemplate.active.is_(True)))
        if not tpl:
            raise HTTPException(404, "No company template is set up (Admin → Excel template)")
        from app.routers.admin_settings import template_path
        data = excel.fill_template(template_path(tpl).read_bytes(), tpl.mapping, [b])
        return Response(data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{stem}-template.xlsx"'})
    raise HTTPException(404, "Unknown format")


@router.get("/me/dsr/{day}/export/{fmt}")
def my_export(day: date, fmt: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _export(db, user, day, fmt, False)


@router.get("/people/{user_id}/dsr/{day}/export/{fmt}")
def person_export(user_id: int, day: date, fmt: str, viewer: User = Depends(current_user), db: Session = Depends(get_db)):
    u = target_user(db, viewer, user_id, "export")
    return _export(db, u, day, fmt, viewer.id != u.id)
