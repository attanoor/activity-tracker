"""Runs the integrations for the worker and the admin 'Sync now' button, turning failures into messages."""

import logging
from datetime import date, datetime

import httpx
from sqlalchemy.orm import Session

from app import settings_store
from app.integrations import google_auth, google_sync, mantis
from app.models import User
from app.pipeline.rebuild import user_timezone

log = logging.getLogger("integrations")


def sync_google(db: Session, user: User, day: date, http: httpx.Client | None = None) -> dict:
    cfg = settings_store.get(db, "google")
    if cfg["mode"] == "off":
        return {"skipped": "Google is switched off"}
    own = http is None
    http = http or httpx.Client(timeout=30)
    out: dict = {}
    try:
        token = google_auth.access_token(db, user, http)
        tz = user_timezone(db, user)
        for name, fn in (("calendar", google_sync.sync_calendar), ("gmail", google_sync.sync_gmail),
                         ("drive", google_sync.sync_drive)):
            if not cfg.get(name):
                continue
            try:
                out[name] = fn(db, user, day, tz, token, http)
            except httpx.HTTPStatusError as e:
                db.rollback()
                out[name] = f"error {e.response.status_code}: {e.response.text[:160]}"
            except httpx.HTTPError as e:
                db.rollback()
                out[name] = f"error: {e}"
    except google_auth.GoogleNotConfigured as e:
        out["error"] = str(e)
    except httpx.HTTPError as e:
        out["error"] = f"could not reach Google: {e}"
    finally:
        if own:
            http.close()
    return out


def sync_mantis(db: Session, since: datetime, http: httpx.Client | None = None) -> dict:
    cfg = settings_store.get(db, "mantis")
    if not cfg["enabled"] or not cfg["base_url"]:
        return {"skipped": "Mantis is switched off"}
    own = http is None
    http = http or httpx.Client(timeout=30)
    try:
        return mantis.sync(db, cfg["base_url"], since, http)
    except mantis.MantisNotConfigured as e:
        return {"error": str(e)}
    except httpx.HTTPStatusError as e:
        db.rollback()
        return {"error": f"Mantis answered {e.response.status_code}: {e.response.text[:160]}"}
    except httpx.HTTPError as e:
        db.rollback()
        return {"error": f"could not reach Mantis: {e}"}
    finally:
        if own:
            http.close()
