"""MantisBT: every ticket action, credited to the person who did it.

The API token is read from the TRACKER_MANTIS_TOKEN environment variable, which the operator sets; it is never
stored in the database or shown in the UI. Read-only: only GET requests are made.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.google_sync import _add_action
from app.models import Team, User

TOKEN_ENV = "TRACKER_MANTIS_TOKEN"
CLOSED = {"resolved", "closed"}


class MantisNotConfigured(Exception):
    pass


def token() -> str:
    t = os.environ.get(TOKEN_ENV, "").strip()
    if not t:
        raise MantisNotConfigured(f"Set the {TOKEN_ENV} environment variable on the server")
    return t


def _ts(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


class UserMatcher:
    """Mantis account -> tracker user: explicit Mantis username, then email, then email local part."""

    def __init__(self, db: Session):
        self.users = [u for u in db.scalars(select(User).where(User.active.is_(True)))]
        tz_of_team = {t.id: t.timezone for t in db.scalars(select(Team))}
        self.tz = {u.id: u.timezone or tz_of_team.get(u.team_id, "UTC") for u in self.users}

    def match(self, mu: dict | None) -> User | None:
        if not mu:
            return None
        name, email = (mu.get("name") or "").lower(), (mu.get("email") or "").lower()
        for u in self.users:
            if u.mantis_username and u.mantis_username.lower() == name:
                return u
        for u in self.users:
            if email and email in {u.email.lower(), (u.google_email or "").lower()}:
                return u
        for u in self.users:
            if not u.mantis_username and name and u.email.split("@")[0].lower() == name:
                return u
        return None


def actions_for_issue(issue: dict, since: datetime) -> list[dict]:
    """Every action on one issue at or after `since`, with the Mantis user who did it."""
    iid = str(issue["id"])
    title = issue.get("summary", "")
    out = []
    created = _ts(issue["created_at"])
    if created >= since:
        out.append({"key": f"mantis:{iid}:reported", "who": issue.get("reporter"), "action": "reported", "at": created, "meta": {}})
    for n in issue.get("notes", []):
        at = _ts(n["created_at"])
        if at >= since:
            out.append({"key": f"mantis:{iid}:note:{n['id']}", "who": n.get("reporter"), "action": "responded", "at": at,
                         "meta": {"note_text": (n.get("text") or "")[:1500],
                                  "private": (n.get("view_state") or {}).get("name") == "private"}})
    for i, h in enumerate(issue.get("history", [])):
        at = _ts(h["created_at"])
        if at < since:
            continue
        field = (h.get("field") or {}).get("name")
        kind = (h.get("type") or {}).get("name", "")
        new, old = h.get("new_value") or {}, h.get("old_value") or {}
        action = None
        if field == "status":
            new_s, old_s = (new.get("name") or "").lower(), (old.get("name") or "").lower()
            action = new_s if new_s in CLOSED else ("reopened" if old_s in CLOSED else "status_changed")
            meta = {"from": old_s, "to": new_s}
        elif field == "handler":
            mine = (new.get("name") or "").lower() == ((h.get("user") or {}).get("name") or "").lower()
            action, meta = ("took" if mine else "assigned"), {"to": new.get("name")}
        elif "file" in kind and "added" in kind:
            action, meta = "attached", {"file": h.get("message") or ""}
        if action:
            key = f"mantis:{iid}:h:{h['created_at']}:{field or kind}:{i}"
            out.append({"key": key, "who": h.get("user"), "action": action, "at": at, "meta": meta})
    for a in out:
        a["issue_id"], a["title"] = iid, title
        a["meta"]["project"] = (issue.get("project") or {}).get("name")
    return out


def sync(db: Session, base_url: str, since: datetime, http: httpx.Client, api_token: str | None = None) -> dict:
    """Walks issues by last update (newest first) until older than `since`, records each action once."""
    headers = {"Authorization": api_token or token()}
    base = base_url.rstrip("/") + "/api/rest"
    matcher = UserMatcher(db)
    added = unmatched = issues = 0
    page = 1
    while True:
        r = http.get(f"{base}/issues", params={"page_size": 50, "page": page}, headers=headers)
        r.raise_for_status()
        batch = r.json().get("issues", [])
        if not batch:
            break
        fresh = [i for i in batch if _ts(i["updated_at"]) >= since]
        for summary in fresh:
            issues += 1
            full = http.get(f"{base}/issues/{summary['id']}", headers=headers)
            full.raise_for_status()
            issue = full.json()["issues"][0]
            for a in actions_for_issue(issue, since):
                user = matcher.match(a["who"])
                if not user:
                    unmatched += 1
                    continue
                day = a["at"].astimezone(ZoneInfo(matcher.tz[user.id])).date()
                added += _add_action(db, a["key"], user.id, day, "mantis", a["action"], a["issue_id"], a["title"],
                                     a["at"], a["meta"])
        if len(fresh) < len(batch):
            break  # reached issues last updated before `since`
        page += 1
    db.commit()
    return {"issues": issues, "added": added, "unmatched": unmatched}
