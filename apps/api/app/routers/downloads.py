"""Agent and extension downloads, plus the signed-in person's own setup codes.

Builds land in dist/downloads with a manifest.json written by scripts/build-agent.ps1 and build-extension.ps1.
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import ROOT
from app.db import get_db
from app.deps import current_user
from app.models import User
from app.routers.admin import EnrolCodeOut, issue_enrol_code

DOWNLOADS = ROOT / "dist" / "downloads"
router = APIRouter(tags=["downloads"])


class DownloadOut(BaseModel):
    key: str
    file: str
    version: str
    size: int
    sha256: str
    built_at: str


def _manifest() -> dict[str, dict]:
    try:
        return json.loads((DOWNLOADS / "manifest.json").read_text())
    except (OSError, ValueError):
        return {}


def _file(entry: dict | None):
    """The entry's file, only if it exists directly inside DOWNLOADS."""
    if not entry:
        return None
    path = (DOWNLOADS / entry["file"]).resolve()
    return path if path.parent == DOWNLOADS.resolve() and path.is_file() else None


@router.get("/downloads", response_model=list[DownloadOut])
def list_downloads(_: User = Depends(current_user)):
    return [DownloadOut(key=k, **v) for k, v in _manifest().items() if _file(v)]


@router.get("/downloads/{key}")
def download(key: str, _: User = Depends(current_user)):
    path = _file(_manifest().get(key))
    if not path:
        raise HTTPException(404, "Not built yet")
    return FileResponse(path, filename=path.name)


@router.get("/privacy-notice")
def privacy_notice(_: User = Depends(current_user), db: Session = Depends(get_db)):
    from app import settings_store
    return {"text": settings_store.get(db, "tracking")["privacy_text"]}


@router.post("/me/enrol-codes", response_model=EnrolCodeOut, status_code=201)
def my_enrol_code(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Anyone signed in can link their own PC; the code only ever enrols a device for them."""
    return issue_enrol_code(db, user.id, user.id)
