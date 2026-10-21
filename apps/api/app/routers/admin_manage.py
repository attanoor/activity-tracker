"""Admin management beyond creation: editing people and teams, password resets, linked PCs."""

import secrets
from datetime import UTC, datetime, time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.db import get_db
from app.models import ROLES, AuthSession, Device, Team, User
from app.routers.admin import TeamOut, _check_tz, admin_only
from app.security import hash_password

router = APIRouter(prefix="/admin", tags=["admin"])


class PersonOut(BaseModel):
    id: int
    email: str
    name: str
    role: str
    team_id: int | None
    timezone: str | None
    active: bool
    devices: int
    last_seen_at: datetime | None
    mantis_username: str | None
    google_email: str | None


@router.get("/people", response_model=list[PersonOut])
def list_people(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    stats = dict(
        (uid, (n, seen)) for uid, n, seen in db.execute(
            select(Device.user_id, func.count(), func.max(Device.last_seen_at))
            .where(Device.revoked_at.is_(None)).group_by(Device.user_id))
    )
    return [PersonOut(id=u.id, email=u.email, name=u.name, role=u.role, team_id=u.team_id, timezone=u.timezone,
                      active=u.active, devices=stats.get(u.id, (0, None))[0], last_seen_at=stats.get(u.id, (0, None))[1],
                      mantis_username=u.mantis_username, google_email=u.google_email)
            for u in db.scalars(select(User).order_by(User.active.desc(), User.name))]


class PersonPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    role: str | None = None
    team_id: int | None = None
    timezone: str | None = None
    active: bool | None = None
    mantis_username: str | None = Field(None, max_length=120)
    google_email: str | None = Field(None, max_length=254)
    clear_team: bool = False  # team_id=None means "unchanged"; this removes the person from their team

    _tz = field_validator("timezone")(_check_tz)

    @field_validator("role")
    @classmethod
    def _role(cls, v: str | None) -> str | None:
        if v is not None and v not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        return v


@router.patch("/people/{user_id}", response_model=PersonOut)
def update_person(user_id: int, body: PersonPatch, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Unknown user")
    if user.id == admin.id and ((body.role and body.role != "admin") or body.active is False):
        raise HTTPException(400, "You cannot remove your own admin access or disable yourself")
    if body.team_id is not None and not db.get(Team, body.team_id):
        raise HTTPException(422, "Unknown team")
    changes = body.model_dump(exclude_unset=True, exclude={"clear_team"})
    if body.clear_team:
        changes["team_id"] = None
    for k in ("mantis_username", "google_email"):
        if k in changes:
            changes[k] = (changes[k] or "").strip() or None  # empty = derive from the email
    for k, v in changes.items():
        setattr(user, k, v)
    if body.active is False:
        db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    audit(db, admin.id, "user.update", f"user:{user.id}", {k: str(v) for k, v in changes.items()})
    db.commit()
    return next(p for p in list_people(db, admin) if p.id == user.id)


class ResetOut(BaseModel):
    password: str


@router.post("/people/{user_id}/reset-password", response_model=ResetOut)
def reset_password(user_id: int, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    """Sets a random password, signs the person out everywhere, and returns the password this once."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Unknown user")
    password = secrets.token_urlsafe(12)
    user.password_hash = hash_password(password)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    audit(db, admin.id, "user.reset_password", f"user:{user.id}")
    db.commit()
    return ResetOut(password=password)


class DeviceOut(BaseModel):
    id: int
    hostname: str
    created_at: datetime
    last_seen_at: datetime | None
    revoked_at: datetime | None


@router.get("/people/{user_id}/devices", response_model=list[DeviceOut])
def person_devices(user_id: int, db: Session = Depends(get_db), _: User = Depends(admin_only)):
    rows = db.scalars(select(Device).where(Device.user_id == user_id).order_by(Device.created_at.desc()))
    return [DeviceOut(id=d.id, hostname=d.hostname, created_at=d.created_at, last_seen_at=d.last_seen_at,
                      revoked_at=d.revoked_at) for d in rows]


@router.post("/devices/{device_id}/revoke", response_model=DeviceOut)
def revoke_device(device_id: int, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "Unknown device")
    if d.revoked_at is None:
        d.revoked_at = datetime.now(UTC)
        audit(db, admin.id, "device.revoke", f"device:{d.id}", {"hostname": d.hostname})
        db.commit()
    return DeviceOut(id=d.id, hostname=d.hostname, created_at=d.created_at, last_seen_at=d.last_seen_at,
                     revoked_at=d.revoked_at)


class TeamPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    timezone: str | None = None
    shift_start: time | None = None
    shift_end: time | None = None
    break_minutes: int | None = Field(None, ge=0, le=240)
    manager_id: int | None = None
    clear_manager: bool = False

    _tz = field_validator("timezone")(_check_tz)


@router.patch("/teams/{team_id}", response_model=TeamOut)
def update_team(team_id: int, body: TeamPatch, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(404, "Unknown team")
    changes = body.model_dump(exclude_unset=True, exclude={"clear_manager"})
    if body.clear_manager:
        changes["manager_id"] = None
    if changes.get("manager_id") is not None:
        mgr = db.get(User, changes["manager_id"])
        if not mgr or mgr.role not in ("manager", "admin"):
            raise HTTPException(422, "The manager must be a person with the manager or admin role")
    if "name" in changes and db.scalar(select(Team).where(Team.name == changes["name"], Team.id != team.id)):
        raise HTTPException(409, "A team with that name exists")
    start, end = changes.get("shift_start", team.shift_start), changes.get("shift_end", team.shift_end)
    if end <= start:
        raise HTTPException(422, "Shift must end after it starts")
    for k, v in changes.items():
        setattr(team, k, v)
    audit(db, admin.id, "team.update", f"team:{team.id}", {k: str(v) for k, v in changes.items()})
    db.commit()
    return TeamOut(id=team.id, name=team.name, timezone=team.timezone, shift_start=team.shift_start,
                   shift_end=team.shift_end, break_minutes=team.break_minutes, manager_id=team.manager_id)
