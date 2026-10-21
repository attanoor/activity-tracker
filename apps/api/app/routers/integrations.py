"""Per-person Google connection (only used when the admin chose the 'oauth' mode)."""

import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import settings_store
from app.config import settings
from app.db import get_db
from app.deps import current_user
from app.integrations import google_auth
from app.models import GoogleToken, User

router = APIRouter(prefix="/integrations/google", tags=["integrations"])
STATE_COOKIE = "tracker_google_state"


@router.get("/status")
def status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    cfg = settings_store.get(db, "google")
    tok = db.get(GoogleToken, user.id)
    return {"mode": cfg["mode"], "connected": bool(tok), "google_email": tok.google_email if tok else None,
            "identity": google_auth.google_identity(user),
            "sources": [k for k in ("calendar", "gmail", "drive") if cfg.get(k)]}


@router.get("/connect")
def connect(user: User = Depends(current_user), db: Session = Depends(get_db)):
    cfg = settings_store.get(db, "google")
    if cfg["mode"] != "oauth" or not cfg["client_id"] or not cfg["redirect_base"]:
        raise HTTPException(400, "Per-person Google connection is not set up by the admin")
    state = secrets.token_urlsafe(24)
    resp = RedirectResponse(google_auth.oauth_start_url(cfg, state), status_code=302)
    resp.set_cookie(STATE_COOKIE, f"{user.id}:{state}", httponly=True, samesite="lax", max_age=600,
                    secure=settings.cookie_secure)
    return resp


@router.get("/callback")
def callback(request: Request, code: str = "", state: str = "", error: str = "",
             user: User = Depends(current_user), db: Session = Depends(get_db)):
    expected = request.cookies.get(STATE_COOKIE, "")
    if error:
        return RedirectResponse(f"/account?google=error&reason={error}", status_code=302)
    if not code or not secrets.compare_digest(expected, f"{user.id}:{state}"):
        raise HTTPException(400, "Sign-in link expired or was not started here; try Connect again")
    with httpx.Client(timeout=30) as http:
        try:
            google_auth.oauth_exchange(db, user, code, http)
        except google_auth.GoogleNotConfigured as e:
            return RedirectResponse(f"/account?google=error&reason={str(e)[:120]}", status_code=302)
    resp = RedirectResponse("/account?google=connected", status_code=302)
    resp.delete_cookie(STATE_COOKIE)
    return resp


@router.post("/disconnect", status_code=204)
def disconnect(user: User = Depends(current_user), db: Session = Depends(get_db)):
    tok = db.get(GoogleToken, user.id)
    if tok:
        db.delete(tok)
        db.commit()
