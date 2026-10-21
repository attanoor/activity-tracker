from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.config import settings
from app.db import get_db
from app.deps import COOKIE, current_user
from app.models import AuthSession, User
from app.security import hash_password, new_token, token_hash, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str
    team_id: int | None


def user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, name=u.name, role=u.role, team_id=u.team_id)


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.strip().lower()))
    if not user or not user.active or not verify_password(user.password_hash, body.password):
        raise HTTPException(401, "Wrong email or password")
    token = new_token()
    expires = datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.expires_at <= datetime.now(UTC)))
    db.add(AuthSession(token_hash=token_hash(token), user_id=user.id, expires_at=expires))
    db.commit()
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=settings.cookie_secure,
                        max_age=settings.session_ttl_hours * 3600)
    return user_out(user)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE)
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(token)))
        db.commit()
    response.delete_cookie(COOKIE)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user_out(user)


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)


@router.post("/change-password", status_code=204)
def change_password(body: PasswordIn, request: Request, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(400, "Current password is wrong")
    user.password_hash = hash_password(body.new_password)
    # Sign out every other session; keep this one.
    keep = token_hash(request.cookies.get(COOKIE, ""))
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.token_hash != keep))
    audit(db, user.id, "user.change_password", f"user:{user.id}")
    db.commit()
