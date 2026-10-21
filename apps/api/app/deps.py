from datetime import UTC, datetime

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuthSession, Device, User
from app.security import token_hash

COOKIE = "tracker_session"


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Not signed in")
    sess = db.get(AuthSession, token_hash(token))
    if not sess or sess.expires_at <= datetime.now(UTC):
        raise HTTPException(401, "Session expired")
    user = db.get(User, sess.user_id)
    if not user or not user.active:
        raise HTTPException(401, "Account disabled")
    return user


def require_role(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "Not allowed")
        return user
    return dep


def current_device(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> Device:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Device token required")
    device = db.query(Device).filter(Device.token_hash == token_hash(token)).one_or_none()
    if not device or device.revoked_at is not None:
        raise HTTPException(401, "Unknown or revoked device")
    owner = db.get(User, device.user_id)
    if not owner or not owner.active:
        raise HTTPException(401, "This person's account is disabled")
    return device
