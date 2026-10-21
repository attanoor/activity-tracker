from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.config import settings
from app.db import get_db
from app.deps import require_role
from app.models import ROLES, EnrolCode, Team, User
from app.routers.auth import UserOut, user_out
from app.security import hash_password, new_enrol_code, token_hash

router = APIRouter(prefix="/admin", tags=["admin"])
admin_only = require_role("admin")


def _check_tz(tz: str | None) -> str | None:
    if tz is None:
        return None
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Unknown timezone {tz!r}")
    return tz


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    timezone: str = "UTC"
    shift_start: time = time(9, 0)
    shift_end: time = time(18, 0)
    break_minutes: int = Field(60, ge=0, le=240)
    manager_id: int | None = None

    _tz = field_validator("timezone")(_check_tz)


class TeamOut(TeamIn):
    id: int


@router.post("/teams", response_model=TeamOut, status_code=201)
def create_team(body: TeamIn, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    if body.shift_end <= body.shift_start:
        raise HTTPException(422, "Shift must end after it starts")
    if db.scalar(select(Team).where(Team.name == body.name)):
        raise HTTPException(409, "A team with that name exists")
    team = Team(**body.model_dump())
    db.add(team)
    db.flush()
    audit(db, admin.id, "team.create", f"team:{team.id}", {"name": team.name})
    db.commit()
    return TeamOut(id=team.id, **body.model_dump())


@router.get("/teams", response_model=list[TeamOut])
def list_teams(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    return [TeamOut(id=t.id, name=t.name, timezone=t.timezone, shift_start=t.shift_start, shift_end=t.shift_end,
                    break_minutes=t.break_minutes, manager_id=t.manager_id) for t in db.scalars(select(Team))]


class UserIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10)
    role: str = "resource"
    team_id: int | None = None
    timezone: str | None = None

    _tz = field_validator("timezone")(_check_tz)

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        return v


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserIn, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    email = body.email.strip().lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, "A user with that email exists")
    if body.team_id is not None and not db.get(Team, body.team_id):
        raise HTTPException(422, "Unknown team")
    user = User(email=email, name=body.name, password_hash=hash_password(body.password), role=body.role,
                team_id=body.team_id, timezone=body.timezone)
    db.add(user)
    db.flush()
    audit(db, admin.id, "user.create", f"user:{user.id}", {"role": user.role})
    db.commit()
    return user_out(user)


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.name))]


class EnrolCodeOut(BaseModel):
    code: str
    expires_at: datetime


@router.post("/users/{user_id}/enrol-codes", response_model=EnrolCodeOut, status_code=201)
def create_enrol_code(user_id: int, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    """Returns the code once; only its hash is stored. The person types it into the agent on first run."""
    if not db.get(User, user_id):
        raise HTTPException(404, "Unknown user")
    return issue_enrol_code(db, user_id, admin.id)


def issue_enrol_code(db: Session, user_id: int, actor_id: int) -> EnrolCodeOut:
    code = new_enrol_code()
    expires = datetime.now(UTC) + timedelta(days=settings.enrol_code_ttl_days)
    db.add(EnrolCode(code_hash=token_hash(code), user_id=user_id, created_by=actor_id, expires_at=expires))
    audit(db, actor_id, "enrol_code.create", f"user:{user_id}")
    db.commit()
    return EnrolCodeOut(code=code, expires_at=expires)
