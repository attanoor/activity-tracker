from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit
from app.db import get_db
from app.models import Device, EnrolCode
from app.security import new_token, token_hash

router = APIRouter(prefix="/devices", tags=["devices"])


class EnrolIn(BaseModel):
    code: str = Field(min_length=4, max_length=32)
    hostname: str = Field(min_length=1, max_length=255)


class EnrolOut(BaseModel):
    device_id: int
    token: str


@router.post("/enrol", response_model=EnrolOut, status_code=201)
def enrol(body: EnrolIn, db: Session = Depends(get_db)):
    code = body.code.strip().upper()
    row = db.scalar(select(EnrolCode).where(EnrolCode.code_hash == token_hash(code)).with_for_update())
    now = datetime.now(UTC)
    if not row or row.used_at is not None or row.expires_at <= now:
        raise HTTPException(400, "Enrolment code is invalid, used or expired")
    row.used_at = now
    token = new_token()
    device = Device(user_id=row.user_id, hostname=body.hostname, token_hash=token_hash(token))
    db.add(device)
    db.flush()
    audit(db, row.user_id, "device.enrol", f"device:{device.id}", {"hostname": body.hostname})
    db.commit()
    return EnrolOut(device_id=device.id, token=token)
