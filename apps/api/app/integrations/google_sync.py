"""Pulls one person's day from Google Calendar, Gmail (metadata only) and Drive Activity. Read-only and
idempotent: events upsert by Google id, actions insert by a unique key, so re-running a day changes nothing."""

from datetime import UTC, date, datetime
from email.utils import getaddresses
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import CalendarEvent, User, WorkAction
from app.pipeline.sessionise import day_bounds

CAL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
DRIVE_ACTIVITY = "https://driveactivity.googleapis.com/v2/activity:query"


def _get(http: httpx.Client, token: str, url: str, **params) -> dict:
    r = http.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    return r.json()


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _local_day(at: datetime, tz: str) -> date:
    return at.astimezone(ZoneInfo(tz)).date()


# --- Calendar ------------------------------------------------------------------------------------------
def parse_events(items: list[dict], email: str) -> list[dict]:
    out = []
    for e in items:
        start, end = e.get("start", {}), e.get("end", {})
        if "dateTime" not in start or "dateTime" not in end:
            continue  # all-day
        if e.get("status") == "cancelled" or e.get("transparency") == "transparent":
            continue  # cancelled, or marked "free"
        if e.get("eventType") in ("outOfOffice", "focusTime", "workingLocation"):
            continue
        me = next((a for a in e.get("attendees", []) if a.get("self") or a.get("email", "").lower() == email.lower()), None)
        if me and me.get("responseStatus") == "declined":
            continue
        has_video = bool(e.get("hangoutLink") or e.get("conferenceData"))
        out.append({"ext_id": e["id"], "title": e.get("summary", "(no title)"), "started_at": _ts(start["dateTime"]),
                    "ended_at": _ts(end["dateTime"]), "attendees": len(e.get("attendees", [])),
                    "has_video": has_video, "organizer": e.get("organizer", {}).get("email")})
    return out


def sync_calendar(db: Session, user: User, day: date, tz: str, token: str, http: httpx.Client) -> int:
    lo, hi = day_bounds(day, tz)
    items, page = [], None
    while True:
        data = _get(http, token, CAL, timeMin=lo.isoformat(), timeMax=hi.isoformat(), singleEvents="true",
                    orderBy="startTime", maxResults=250, **({"pageToken": page} if page else {}))
        items += data.get("items", [])
        page = data.get("nextPageToken")
        if not page:
            break
    events = parse_events(items, user.google_email or user.email)
    seen = set()
    for ev in events:
        seen.add(ev["ext_id"])
        stmt = insert(CalendarEvent).values(user_id=user.id, day=day, **ev).on_conflict_do_update(
            constraint="uq_calendar_events_user_ext",
            set_={k: ev[k] for k in ("title", "started_at", "ended_at", "attendees", "has_video", "organizer")} | {"day": day})
        db.execute(stmt)
    # Events deleted or declined since the last sync disappear from the day.
    for old in db.scalars(select(CalendarEvent).where(CalendarEvent.user_id == user.id, CalendarEvent.day == day)):
        if old.ext_id not in seen:
            db.delete(old)
    db.commit()
    return len(events)


# --- Gmail (headers only) ---------------------------------------------------------------------------------
def sync_gmail(db: Session, user: User, day: date, tz: str, token: str, http: httpx.Client) -> int:
    lo, hi = day_bounds(day, tz)
    q = f"in:sent after:{int(lo.timestamp())} before:{int(hi.timestamp())}"
    ids, page = [], None
    while True:
        data = _get(http, token, f"{GMAIL}/messages", q=q, maxResults=500, **({"pageToken": page} if page else {}))
        ids += [m["id"] for m in data.get("messages", [])]
        page = data.get("nextPageToken")
        if not page:
            break
    n = 0
    for mid in ids:
        m = _get(http, token, f"{GMAIL}/messages/{mid}", format="metadata",
                 metadataHeaders=["Subject", "To", "Cc", "In-Reply-To"])
        headers = {h["name"].lower(): h["value"] for h in m.get("payload", {}).get("headers", [])}
        at = datetime.fromtimestamp(int(m["internalDate"]) / 1000, UTC)
        recipients = [a for _, a in getaddresses([headers.get("to", ""), headers.get("cc", "")]) if "@" in a]
        reply = bool(headers.get("in-reply-to"))
        n += _add_action(db, f"gmail:{mid}", user.id, _local_day(at, tz), "gmail", "replied" if reply else "new_thread",
                         m["threadId"], headers.get("subject", "(no subject)"), at,
                         {"to_domains": sorted({a.split("@")[1].lower() for a in recipients}),
                          "recipients": len(recipients), "snippet": m.get("snippet", "")[:300]})
    db.commit()
    return n


# --- Drive Activity ---------------------------------------------------------------------------------------
DRIVE_ACTIONS = {"create": "created", "edit": "edited", "comment": "commented", "permissionChange": "shared",
                 "rename": "renamed", "move": "moved", "delete": "deleted", "restore": "restored"}


def parse_drive(activities: list[dict]) -> list[dict]:
    out = []
    for a in activities:
        mine = any(act.get("user", {}).get("knownUser", {}).get("isCurrentUser") for act in a.get("actors", []))
        if not mine:
            continue
        kind = next(iter(a.get("primaryActionDetail", {})), None)
        if kind not in DRIVE_ACTIONS:
            continue
        when = a.get("timestamp") or a.get("timeRange", {}).get("endTime")
        for t in a.get("targets", []):
            item = t.get("driveItem")
            if item:
                out.append({"action": DRIVE_ACTIONS[kind], "object_id": item["name"], "title": item.get("title", ""),
                            "mime": item.get("mimeType", ""), "at": _ts(when)})
    return out


def sync_drive(db: Session, user: User, day: date, tz: str, token: str, http: httpx.Client) -> int:
    lo, hi = day_bounds(day, tz)
    body = {"filter": f'time >= "{lo.isoformat()}" AND time < "{hi.isoformat()}"', "pageSize": 100}
    n = 0
    while True:
        r = http.post(DRIVE_ACTIVITY, json=body, headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        data = r.json()
        for x in parse_drive(data.get("activities", [])):
            key = f"drive:{x['object_id']}:{x['action']}:{x['at'].isoformat()}"
            n += _add_action(db, key, user.id, _local_day(x["at"], tz), "drive", x["action"], x["object_id"],
                             x["title"], x["at"], {"mime": x["mime"]})
        if not data.get("nextPageToken"):
            break
        body["pageToken"] = data["nextPageToken"]
    db.commit()
    return n


def _add_action(db: Session, key: str, user_id: int, day: date, source: str, action: str, object_id: str,
                title: str, at: datetime, meta: dict) -> int:
    stmt = insert(WorkAction).values(ext_key=key, user_id=user_id, day=day, source=source, action=action,
                                     object_id=object_id, object_title=title, at=at, meta=meta)
    return len(db.execute(stmt.on_conflict_do_nothing(index_elements=["ext_key"]).returning(WorkAction.id)).all())
