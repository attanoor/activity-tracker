"""Clients (clubs): admin management, the list people pick from, and manual off-PC entries."""

from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app import settings_store
from app.ai import levels
from app.ai.llm import get_llm
from app.audit import audit
from app.clients import learn as learner
from app.clients.domains import clean_host
from app.db import get_db
from app.deps import current_user
from app.models import ActivitySession, Client, ClientIdentifier, DsrReport, ManualEntry, User
from app.pipeline.rebuild import user_timezone
from app.routers.admin import admin_only

router = APIRouter(tags=["clients"])
KINDS = ("web_domain", "email_domain", "email_address", "name_alias", "mantis_project")


def _client_out(db: Session, c: Client) -> dict:
    ids = db.scalars(select(ClientIdentifier).where(ClientIdentifier.client_id == c.id).order_by(ClientIdentifier.kind)).all()
    return {"id": c.id, "name": c.name, "status": c.status, "notes": c.notes, "seconds_seen": c.seconds_seen,
            "identifiers": [{"id": i.id, "kind": i.kind, "value": i.value, "source": i.source} for i in ids]}


@router.get("/clients")
def client_names(_: User = Depends(current_user), db: Session = Depends(get_db)):
    """Confirmed clients, for pickers (e.g. the manual entry form)."""
    return [{"id": i, "name": n} for i, n in db.execute(select(Client.id, Client.name)
                                                         .where(Client.status == "confirmed").order_by(Client.name))]


@router.get("/admin/clients")
def list_clients(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    rows = db.scalars(select(Client).order_by(Client.status != "suggested", Client.name)).all()
    return [_client_out(db, c) for c in rows]


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    notes: str = ""


@router.post("/admin/clients", status_code=201)
def create_client(body: ClientIn, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    if db.scalar(select(Client).where(func.lower(Client.name) == body.name.strip().lower())):
        raise HTTPException(409, "A client with that name exists")
    c = Client(name=body.name.strip(), notes=body.notes, status="confirmed")
    db.add(c)
    db.flush()
    audit(db, admin.id, "client.create", f"client:{c.id}", {"name": c.name})
    db.commit()
    return _client_out(db, c)


class ClientPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    status: str | None = Field(None, pattern="^(suggested|confirmed|ignored)$")
    notes: str | None = None


@router.patch("/admin/clients/{cid}")
def edit_client(cid: int, body: ClientPatch, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404, "Unknown client")
    if body.name and db.scalar(select(Client).where(func.lower(Client.name) == body.name.strip().lower(), Client.id != cid)):
        raise HTTPException(409, "Another client has that name; merge them instead")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v.strip() if isinstance(v, str) and k == "name" else v)
    audit(db, admin.id, "client.update", f"client:{c.id}", body.model_dump(exclude_unset=True))
    db.commit()
    return _client_out(db, c)


class MergeIn(BaseModel):
    into_id: int


@router.post("/admin/clients/{cid}/merge")
def merge(cid: int, body: MergeIn, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    """Moves every identifier (and attributed time) of this client to another, then deletes it."""
    src, dst = db.get(Client, cid), db.get(Client, body.into_id)
    if not src or not dst or src.id == dst.id:
        raise HTTPException(422, "Pick two different clients")
    db.execute(update(ClientIdentifier).where(ClientIdentifier.client_id == src.id).values(client_id=dst.id))
    db.execute(update(ActivitySession).where(ActivitySession.client_id == src.id).values(client_id=dst.id))
    db.execute(update(ManualEntry).where(ManualEntry.client_id == src.id).values(client_id=dst.id))
    learner.add_identifier(db, dst, "name_alias", src.name.lower(), source="admin")
    dst.seconds_seen += src.seconds_seen
    db.delete(src)
    audit(db, admin.id, "client.merge", f"client:{dst.id}", {"merged": src.name})
    db.commit()
    return _client_out(db, dst)


class IdentifierIn(BaseModel):
    kind: str = Field(pattern="^(" + "|".join(KINDS) + ")$")
    value: str = Field(min_length=2, max_length=255)


@router.post("/admin/clients/{cid}/identifiers", status_code=201)
def add_identifier(cid: int, body: IdentifierIn, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404, "Unknown client")
    value = body.value.strip().lower()
    if body.kind in ("web_domain", "email_domain"):
        # Accept a pasted address ("https://www.club.com/page") or an email ("gm@club.com") and keep the host.
        host = urlsplit(value).hostname if "://" in value else value.split("@")[-1].split("/")[0]
        value = clean_host(host) or value
    existing = db.scalar(select(ClientIdentifier).where(ClientIdentifier.kind == body.kind, ClientIdentifier.value == value))
    if existing:
        owner = db.get(Client, existing.client_id)
        raise HTTPException(409, f"{value} already belongs to {owner.name}")
    db.add(ClientIdentifier(client_id=c.id, kind=body.kind, value=value, source="admin"))
    audit(db, admin.id, "client.identifier_add", f"client:{c.id}", {"kind": body.kind, "value": value})
    db.commit()
    return _client_out(db, c)


@router.delete("/admin/client-identifiers/{iid}", status_code=204)
def delete_identifier(iid: int, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    i = db.get(ClientIdentifier, iid)
    if i:
        audit(db, admin.id, "client.identifier_delete", f"client:{i.client_id}", {"kind": i.kind, "value": i.value})
        db.delete(i)
        db.commit()


def llm_namer(db: Session):
    llm, model = get_llm(db)
    if not llm:
        return None
    known = [n for n, in db.execute(select(Client.name).where(Client.status == "confirmed"))]
    return lambda domain, hints: levels.suggest_client_name(db, llm, model, domain, hints, known)


@router.post("/admin/clients/learn")
def learn_now(days: int = 14, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    out = learner.learn(db, date.today() - timedelta(days=min(max(days, 1), 60)), llm_namer(db))
    audit(db, admin.id, "client.learn", None, out)
    db.commit()
    return out


class ImportIn(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)


@router.post("/admin/clients/import")
def import_clients(body: ImportIn, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    """One club per line: 'Club Name' or 'Club Name, website or email domain, ...' (e.g. the MantisClubs list)."""
    out = learner.import_names(db, body.text.splitlines())
    audit(db, admin.id, "client.import", None, out)
    db.commit()
    return out


# --- the daily lock and manual entries --------------------------------------------------------------------
def edit_deadline(db: Session, user: User, day: date) -> datetime:
    from zoneinfo import ZoneInfo
    hours = settings_store.get(db, "tracking")["edit_hours_after_day"]
    end_of_day = datetime.combine(day + timedelta(days=1), time.min, ZoneInfo(user_timezone(db, user)))
    return end_of_day + timedelta(hours=hours)


def can_edit_day(db: Session, user: User, day: date) -> tuple[bool, str]:
    r = db.scalar(select(DsrReport).where(DsrReport.user_id == user.id, DsrReport.day == day))
    if r and r.status != "draft":
        return False, "This day's report was submitted. Ask your manager to reopen it if something is missing."
    if r and r.reopened_by:
        return True, ""
    if datetime.now(UTC) > edit_deadline(db, user, day):
        return False, "This day is closed for changes. Ask your manager to reopen it."
    return True, ""


class ManualIn(BaseModel):
    day: date
    start: time
    end: time
    kind: str = Field(pattern="^(call|site_visit|meeting|other)$")
    title: str = Field(min_length=1, max_length=200)
    client_id: int | None = None
    note: str = Field("", max_length=1000)


def _manual_out(m: ManualEntry, names: dict) -> dict:
    return {"id": m.id, "day": m.day, "start": m.started_at, "end": m.ended_at, "kind": m.kind, "title": m.title,
            "client_id": m.client_id, "client": names.get(m.client_id), "note": m.note}


@router.get("/me/manual-entries")
def my_manual(day: date, user: User = Depends(current_user), db: Session = Depends(get_db)):
    names = dict(db.execute(select(Client.id, Client.name)).all())
    rows = db.scalars(select(ManualEntry).where(ManualEntry.user_id == user.id, ManualEntry.day == day)
                      .order_by(ManualEntry.started_at)).all()
    ok, why = can_edit_day(db, user, day)
    return {"entries": [_manual_out(m, names) for m in rows], "editable": ok, "reason": why}


@router.post("/me/manual-entries", status_code=201)
def add_manual(body: ManualIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from zoneinfo import ZoneInfo
    ok, why = can_edit_day(db, user, body.day)
    if not ok:
        raise HTTPException(409, why)
    if body.end <= body.start:
        raise HTTPException(422, "The end time must be after the start time")
    if body.client_id is not None:
        c = db.get(Client, body.client_id)
        if not c or c.status != "confirmed":
            raise HTTPException(422, "Unknown client")
    z = ZoneInfo(user_timezone(db, user))
    m = ManualEntry(user_id=user.id, day=body.day, started_at=datetime.combine(body.day, body.start, z),
                    ended_at=datetime.combine(body.day, body.end, z), kind=body.kind, title=body.title.strip(),
                    client_id=body.client_id, note=body.note.strip())
    db.add(m)
    db.flush()
    audit(db, user.id, "manual_entry.add", f"manual:{m.id}", {"day": body.day.isoformat(), "kind": body.kind})
    db.commit()
    return _manual_out(m, dict(db.execute(select(Client.id, Client.name)).all()))


@router.delete("/me/manual-entries/{mid}", status_code=204)
def delete_manual(mid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.get(ManualEntry, mid)
    if not m or m.user_id != user.id:
        raise HTTPException(404, "Unknown entry")
    ok, why = can_edit_day(db, user, m.day)
    if not ok:
        raise HTTPException(409, why)
    db.execute(delete(ManualEntry).where(ManualEntry.id == mid))
    audit(db, user.id, "manual_entry.delete", f"manual:{mid}")
    db.commit()
