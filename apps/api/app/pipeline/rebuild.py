"""Rebuilds one user's sessions for one local day from raw events. Safe to run any number of times."""

from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.clients.resolve import Resolver
from app.config import settings
from app.dsr.blocks import ticket_of
from app.models import ActivitySession, Category, CategoryRule, RawEvent, Team, User
from app.pipeline.categorise import Rule, categorise, order_rules
from app.pipeline.sessionise import Span, day_bounds, sessionise


def user_timezone(db: Session, user: User) -> str:
    if user.timezone:
        return user.timezone
    if user.team_id:
        team = db.get(Team, user.team_id)
        if team:
            return team.timezone
    return "UTC"


def load_rules(db: Session) -> list[Rule]:
    rows = db.execute(
        select(CategoryRule, Category.klass)
        .join(Category, Category.id == CategoryRule.category_id)
        .where(CategoryRule.enabled.is_(True))
    ).all()
    return order_rules([Rule(r.id, r.field, r.pattern, r.category_id, klass, r.priority) for r, klass in rows])


def rebuild_day(db: Session, user: User, day: date) -> list[ActivitySession]:
    tz = user_timezone(db, user)
    lo, hi = day_bounds(day, tz)
    # A span can start before midnight and run into this day; agents flush spans at most every few
    # minutes, so a one-day look-back is ample.
    events = db.scalars(
        select(RawEvent).where(
            RawEvent.user_id == user.id, RawEvent.started_at < hi, RawEvent.started_at >= lo - timedelta(days=1)
        )
    ).all()
    spans = [Span(e.started_at, e.duration_s, e.kind, e.app, e.title, e.url, e.domain, e.context) for e in events]
    drafts = sessionise(spans, day, tz, settings.merge_gap_seconds)
    rules = load_rules(db)
    resolver = Resolver(db)

    db.execute(delete(ActivitySession).where(ActivitySession.user_id == user.id, ActivitySession.day == day))
    rows = []
    for d in drafts:
        category_id, klass = categorise(d.kind, d.app, d.domain, d.title, rules)
        club, section = d.club, d.section
        client_id = (resolver.for_session(d.domain, club, d.title, ticket_of(d.title, d.paths, d.domain))
                     if d.kind == "active" else None)
        if client_id and category_id is None and klass == "neutral":
            klass = "productive"  # a recognised client's site or backoffice that no rule covers is client work
        rows.append(ActivitySession(
            user_id=user.id, day=day, started_at=d.started_at, ended_at=d.ended_at, duration_s=d.duration_s,
            kind=d.kind, app=d.app, domain=d.domain, title=d.title, titles=d.titles, paths=d.paths,
            category_id=category_id, klass=klass, club=club, section=section, contexts=d.contexts,
            client_id=client_id,
        ))
    db.add_all(rows)
    db.commit()
    return rows
