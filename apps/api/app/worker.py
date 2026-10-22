"""Background jobs:  python -m app.worker

Every minute it checks what is due. Each job has a key in `job_runs`, so it runs once even across restarts:
  refresh   every 5 min    rebuild today's sessions and analysis for people with a linked PC
  sync      every 30 min   Google (calendar, gmail, drive) per person; Mantis for everyone; warm item summaries
  dsr       after shift    final sync, then the AI draft of each person's DSR
  team      after DSRs     the team's day summary
  mail      send time      each DSR to the manager (submitted, or the draft marked not reviewed), team digest,
                           master workbook / shared folder
  nightly   02:00          raw-event retention, AI category suggestions for unknown sites
  weekly    Mon / 1st      week and month summaries for people and teams
"""

import logging
import shutil
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import settings_store
from app.ai import levels
from app.ai.llm import get_llm
from app.config import ROOT, settings
from app.db import SessionLocal
from app.dsr import rollup, service
from app.exports import excel, mailer, pdf
from app.exports.bundle import gather
from app.integrations import runner
from app.models import (ActivitySession, Category, Device, DsrReport, JobRun, RawEvent, RuleSuggestion, Team, User)
from app.pipeline.rebuild import user_timezone

log = logging.getLogger("worker")
TICK_S = 60
EXPORTS = ROOT / ".local" / "exports"


def once(db: Session, key: str, detail: dict | None = None) -> bool:
    """True the first time a key is claimed."""
    res = db.execute(insert(JobRun).values(key=key, detail=detail or {}).on_conflict_do_nothing().returning(JobRun.key))
    db.commit()
    return bool(res.all())


def tracked_users(db: Session) -> list[User]:
    ids = select(Device.user_id).where(Device.revoked_at.is_(None))
    return list(db.scalars(select(User).where(User.active.is_(True), User.id.in_(ids))))


def local_now(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz))


def shift_end_local(db: Session, u: User, day: date, tz: str) -> datetime:
    return datetime.combine(day, service.shift_for(db, u).end, ZoneInfo(tz))


def job_refresh(db: Session, now: datetime) -> None:
    if not once(db, f"refresh:{now:%Y%m%d%H}{now.minute // 5}"):
        return
    for u in tracked_users(db):
        service.compute_day(db, u, local_now(user_timezone(db, u)).date())


def job_sync(db: Session, now: datetime) -> None:
    if not once(db, f"sync:{now:%Y%m%d%H}{now.minute // 30}"):
        return
    m = runner.sync_mantis(db, now - timedelta(hours=2))
    if m.get("error"):
        log.warning("mantis: %s", m["error"])
    for u in tracked_users(db):
        day = local_now(user_timezone(db, u)).date()
        g = runner.sync_google(db, u, day)
        if g.get("error"):
            log.info("google %s: %s", u.email, g["error"])
        try:
            service.warm_items(db, u, day)
        except Exception:
            log.exception("warming summaries for %s", u.email)


def job_dsr(db: Session, now: datetime) -> None:
    after = timedelta(minutes=settings_store.get(db, "tracking")["generate_after_shift_minutes"])
    for u in tracked_users(db):
        tz = user_timezone(db, u)
        day = local_now(tz).date()
        if local_now(tz) < shift_end_local(db, u, day, tz) + after:
            continue
        if not once(db, f"dsr:{day}:{u.id}"):
            continue
        runner.sync_mantis(db, datetime.combine(day, datetime.min.time(), ZoneInfo(tz)))
        runner.sync_google(db, u, day)
        d = service.compute_day(db, u, day)
        if d["analysis"]["active_s"] < 1800:
            log.info("dsr %s %s: under 30 min tracked, skipped", u.email, day)
            continue
        r = service.generate(db, u, day)
        log.info("dsr %s %s: %s (%s)", u.email, day, r.status, r.ai_status)


def job_team(db: Session, now: datetime) -> None:
    after = timedelta(minutes=settings_store.get(db, "tracking")["generate_after_shift_minutes"] + 30)
    for team in db.scalars(select(Team)):
        tz = team.timezone
        day = local_now(tz).date()
        if local_now(tz) < datetime.combine(day, team.shift_end, ZoneInfo(tz)) + after:
            continue
        if once(db, f"team:{day}:{team.id}"):
            rollup.team_day(db, team, day)


def _deliver_files(db: Session, b, xlsx: bytes) -> None:
    cfg = settings_store.get(db, "excel")
    if cfg["master_enabled"]:
        team = b.team or "No team"
        excel.append_master(EXPORTS / f"master-{team.replace(' ', '-')}.xlsx", b)
    if cfg["shared_folder"]:
        folder = Path(cfg["shared_folder"]) / b.day.isoformat()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"DSR-{b.user.name.replace(' ', '-')}-{b.day}.xlsx").write_bytes(xlsx)
            if cfg["master_enabled"]:
                for f in EXPORTS.glob("master-*.xlsx"):
                    shutil.copy2(f, Path(cfg["shared_folder"]) / f.name)
        except OSError as e:
            log.warning("shared folder %s: %s", cfg["shared_folder"], e)


def job_mail(db: Session, now: datetime) -> None:
    cfg = settings_store.get(db, "email")
    hh, mm = (int(x) for x in cfg["send_time"].split(":"))
    for team in db.scalars(select(Team)):
        tz = team.timezone
        today = local_now(tz).date()
        if local_now(tz) < datetime.combine(today, datetime.min.time(), ZoneInfo(tz)).replace(hour=hh, minute=mm):
            continue
        manager = db.get(User, team.manager_id) if team.manager_id else None
        for u in rollup.members(db, team.id):
            r = db.scalar(select(DsrReport).where(DsrReport.user_id == u.id, DsrReport.day == today))
            if not r or not once(db, f"mail:{today}:{u.id}"):
                continue
            b = gather(db, u, today)
            xlsx = excel.dsr_workbook([b])
            _deliver_files(db, b, xlsx)
            reviewed = r.status == "submitted"
            if not cfg["enabled"] or not manager or (not reviewed and not cfg["send_unreviewed"]):
                continue
            subject, text, html = mailer.dsr_message(b, reviewed)
            files = []
            if cfg["attach_excel"]:
                files.append((f"DSR-{u.name}-{today}.xlsx", xlsx, excel_mime()))
            if cfg["attach_pdf"]:
                files.append((f"DSR-{u.name}-{today}.pdf", pdf.dsr_pdf(b, for_manager=True), "application/pdf"))
            try:
                mailer.send(db, [manager.email], subject, text, html, files, cc=[u.email])
                r.status, r.sent_at = "sent", datetime.now(UTC)
                db.commit()
            except Exception as e:
                log.warning("mail %s: %s", u.email, e)
        if cfg["enabled"] and manager and once(db, f"digest:{today}:{team.id}"):
            s = rollup.team_day(db, team, today)
            table = []
            for u in rollup.members(db, team.id):
                a = service.compute_day(db, u, today, rebuild=False)["analysis"]
                r = db.scalar(select(DsrReport.status).where(DsrReport.user_id == u.id, DsrReport.day == today))
                table.append({"name": u.name, "report": r or "none",
                              "productive": f"{a['breakdown']['productive'] // 60} min",
                              "meetings": f"{a['breakdown']['meeting'] // 60} min"})
            subject, text, html = mailer.digest_message(team.name, today, s.content, table)
            try:
                mailer.send(db, [manager.email], subject, text, html)
            except Exception as e:
                log.warning("digest %s: %s", team.name, e)


def excel_mime() -> str:
    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def job_nightly(db: Session, now: datetime) -> None:
    if now.astimezone().hour < 2 or not once(db, f"nightly:{now.astimezone():%Y%m%d}"):
        return
    from app.clients import learn as learner
    from app.routers.clients import llm_namer
    learned = learner.learn(db, (now - timedelta(days=14)).date(), llm_namer(db))
    log.info("client suggestions: %s", learned)
    days = settings_store.get(db, "tracking")["retention_days"]
    n = db.execute(delete(RawEvent).where(RawEvent.started_at < now - timedelta(days=days))).rowcount
    db.commit()
    log.info("retention: removed %s raw events older than %s days", n, days)
    # Sites with no category that took 10+ minutes yesterday: ask the model, queue for the admin.
    llm, model = get_llm(db)
    if not llm:
        return
    names = [c for c in db.scalars(select(Category.name))]
    known = set(db.scalars(select(RuleSuggestion.domain)))
    rows = db.execute(select(ActivitySession.domain, func.sum(ActivitySession.duration_s), func.array_agg(ActivitySession.title))
                      .where(ActivitySession.category_id.is_(None), ActivitySession.kind == "active",
                             ActivitySession.domain.is_not(None), ActivitySession.day >= (now - timedelta(days=2)).date())
                      .group_by(ActivitySession.domain).having(func.sum(ActivitySession.duration_s) >= 600)).all()
    cat_ids = dict(db.execute(select(Category.name, Category.id)).all())
    for domain, secs, titles in rows:
        if domain in known:
            continue
        out = levels.suggest_rule(db, llm, model, domain, [t for t in titles if t][:5], names)
        if out:
            db.add(RuleSuggestion(domain=domain, category_id=cat_ids[out["category"]], reason=out["reason"],
                                  seconds_seen=int(secs)))
            db.commit()


def job_periods(db: Session, now: datetime) -> None:
    local = now.astimezone()
    if local.hour < 3:
        return
    today = local.date()
    jobs = []
    if today.weekday() == 0:
        jobs.append(("week", today - timedelta(days=7)))
    if today.day == 1:
        jobs.append(("month", (today - timedelta(days=1)).replace(day=1)))
    for period, start in jobs:
        if not once(db, f"{period}:{start}"):
            continue
        for u in tracked_users(db):
            rollup.period_summary(db, "user", u.id, period, start)
        for t in db.scalars(select(Team)):
            rollup.period_summary(db, "team", t.id, period, start)


JOBS = (job_refresh, job_sync, job_dsr, job_team, job_mail, job_nightly, job_periods)


def tick() -> None:
    now = datetime.now(UTC)
    for job in JOBS:
        with SessionLocal() as db:
            try:
                job(db, now)
            except Exception:
                db.rollback()
                log.exception("%s failed", job.__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log.info("worker started (database %s)", settings.database_url.rsplit("@", 1)[-1])
    while True:
        tick()
        time.sleep(TICK_S)


if __name__ == "__main__":
    main()
