from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models import ActivitySession, Category, User
from app.pipeline.rebuild import rebuild_day

router = APIRouter(prefix="/me/days", tags=["days"])


class SessionOut(BaseModel):
    id: int
    started_at: datetime
    ended_at: datetime
    duration_s: int
    kind: str
    app: str | None
    domain: str | None
    title: str | None
    titles: list
    paths: list
    category: str | None
    klass: str


class DayOut(BaseModel):
    day: date
    total_s: int
    by_klass: dict[str, int]
    sessions: list[SessionOut]


def day_out(db: Session, user: User, day: date, rebuild: bool) -> DayOut:
    if rebuild:
        rebuild_day(db, user, day)
    names = dict(db.execute(select(Category.id, Category.name)).all())
    rows = db.scalars(
        select(ActivitySession)
        .where(ActivitySession.user_id == user.id, ActivitySession.day == day)
        .order_by(ActivitySession.started_at)
    ).all()
    by_klass: dict[str, int] = {}
    for r in rows:
        by_klass[r.klass] = by_klass.get(r.klass, 0) + r.duration_s
    return DayOut(
        day=day, total_s=sum(by_klass.values()), by_klass=by_klass,
        sessions=[SessionOut(
            id=r.id, started_at=r.started_at, ended_at=r.ended_at, duration_s=r.duration_s, kind=r.kind,
            app=r.app, domain=r.domain, title=r.title, titles=r.titles, paths=r.paths,
            category=names.get(r.category_id), klass=r.klass,
        ) for r in rows],
    )


@router.get("/{day}", response_model=DayOut)
def my_day(day: date, rebuild: bool = True, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The signed-in person's own day. Rebuilt from raw events by default so it is always current."""
    return day_out(db, user, day, rebuild)
