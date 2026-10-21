"""Who may see whose data: everyone sees themselves; a manager sees the people in teams they manage; admins see
everyone. Every view of someone else's day is written to the audit log."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit
from app.models import Team, User


def managed_team_ids(db: Session, viewer: User) -> list[int]:
    if viewer.role == "admin":
        return list(db.scalars(select(Team.id)))
    if viewer.role == "manager":
        return list(db.scalars(select(Team.id).where(Team.manager_id == viewer.id)))
    return []


def can_view(db: Session, viewer: User, target: User) -> bool:
    if viewer.id == target.id or viewer.role == "admin":
        return True
    return viewer.role == "manager" and target.team_id in managed_team_ids(db, viewer)


def target_user(db: Session, viewer: User, user_id: int, what: str) -> User:
    target = db.get(User, user_id)
    if not target or not can_view(db, viewer, target):
        raise HTTPException(404, "No such person in your teams")
    if target.id != viewer.id:
        audit(db, viewer.id, f"view.{what}", f"user:{target.id}")
        db.commit()
    return target


def team_for(db: Session, viewer: User, team_id: int) -> Team:
    team = db.get(Team, team_id)
    if not team or team.id not in managed_team_ids(db, viewer):
        raise HTTPException(404, "No such team")
    return team
