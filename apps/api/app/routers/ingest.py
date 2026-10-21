import gzip
import io
import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, Field, ValidationError, field_validator
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_device
from app.models import EVENT_KINDS, Device, RawEvent

router = APIRouter(prefix="/ingest", tags=["ingest"])

MAX_BODY = 5 * 1024 * 1024
MAX_EVENTS = 5000
CLOCK_SKEW = timedelta(minutes=5)


class EventIn(BaseModel):
    seq: int = Field(ge=0)
    started_at: AwareDatetime
    duration_s: int = Field(ge=1, le=86_400)
    kind: str
    app: str | None = Field(None, max_length=255)
    title: str | None = Field(None, max_length=2000)
    url: str | None = Field(None, max_length=4000)
    domain: str | None = Field(None, max_length=255)

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in EVENT_KINDS:
            raise ValueError(f"kind must be one of {EVENT_KINDS}")
        return v


class BatchIn(BaseModel):
    events: list[EventIn] = Field(max_length=MAX_EVENTS)


class BatchOut(BaseModel):
    accepted: int
    duplicates: int
    max_seq: int | None


async def _read_batch(request: Request) -> BatchIn:
    body = await request.body()
    if request.headers.get("content-encoding", "").lower() == "gzip":
        try:
            body = gzip.GzipFile(fileobj=io.BytesIO(body)).read(MAX_BODY + 1)
        except OSError:
            raise HTTPException(400, "Body is not valid gzip")
    if len(body) > MAX_BODY:
        raise HTTPException(413, "Batch too large")
    try:
        return BatchIn.model_validate(json.loads(body))
    except (ValueError, ValidationError) as e:
        raise HTTPException(422, f"Invalid batch: {e}")


@router.post("/events", response_model=BatchOut)
async def ingest_events(request: Request, device: Device = Depends(current_device), db: Session = Depends(get_db)):
    batch = await _read_batch(request)
    now = datetime.now(UTC)
    rows = []
    for e in batch.events:
        if e.started_at > now + CLOCK_SKEW:
            raise HTTPException(422, f"Event seq {e.seq} starts in the future")
        private = e.kind in ("private", "paused")
        rows.append({
            "device_id": device.id, "user_id": device.user_id, "seq": e.seq, "started_at": e.started_at,
            "duration_s": e.duration_s, "kind": e.kind,
            # The agent already strips private/paused details; drop them here too in case an old agent didn't.
            "app": None if private else e.app, "title": None if private else e.title,
            "url": None if private else e.url, "domain": None if private else e.domain,
        })
    accepted = 0
    if rows:
        stmt = insert(RawEvent).values(rows).on_conflict_do_nothing(constraint="uq_raw_events_device_seq")
        accepted = len(db.execute(stmt.returning(RawEvent.id)).all())
    device.last_seen_at = now
    db.commit()
    return BatchOut(accepted=accepted, duplicates=len(rows) - accepted,
                    max_seq=max((e.seq for e in batch.events), default=None))
