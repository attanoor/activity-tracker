"""Integrations against recorded API responses (httpx.MockTransport): no network, no real accounts."""

import json
from datetime import UTC, date, datetime

import httpx
import pytest

from app.integrations import google_auth, google_sync, mantis
from app.models import CalendarEvent, Team, WorkAction

DAY = date(2026, 10, 21)
TZ = "Asia/Karachi"


@pytest.fixture()
def ali(db, make_user):
    t = Team(name="Support", timezone=TZ)
    db.add(t)
    db.commit()
    return make_user("ali@example.com", team_id=t.id, mantis_username="ali.m")


def client(routes):
    def handler(req: httpx.Request):
        for (method, prefix), fn in routes.items():
            if req.method == method and str(req.url).startswith(prefix):
                return fn(req)
        return httpx.Response(404, json={"error": str(req.url)})
    return httpx.Client(transport=httpx.MockTransport(handler))


CAL_ITEMS = [
    {"id": "e1", "summary": "Standup", "start": {"dateTime": "2026-10-21T10:00:00+05:00"},
     "end": {"dateTime": "2026-10-21T10:15:00+05:00"}, "hangoutLink": "https://meet.google.com/x",
     "attendees": [{"email": "ali@example.com", "self": True, "responseStatus": "accepted"}, {"email": "b@example.com"}],
     "organizer": {"email": "b@example.com"}},
    {"id": "e2", "summary": "Declined", "start": {"dateTime": "2026-10-21T11:00:00+05:00"},
     "end": {"dateTime": "2026-10-21T12:00:00+05:00"},
     "attendees": [{"email": "ali@example.com", "self": True, "responseStatus": "declined"}]},
    {"id": "e3", "summary": "Holiday", "start": {"date": "2026-10-21"}, "end": {"date": "2026-10-22"}},
    {"id": "e4", "summary": "Busy block", "transparency": "transparent", "start": {"dateTime": "2026-10-21T13:00:00+05:00"},
     "end": {"dateTime": "2026-10-21T14:00:00+05:00"}},
]


def test_calendar_sync_filters_and_is_idempotent(db, ali):
    http = client({("GET", google_sync.CAL): lambda r: httpx.Response(200, json={"items": CAL_ITEMS})})
    assert google_sync.sync_calendar(db, ali, DAY, TZ, "tok", http) == 1
    assert google_sync.sync_calendar(db, ali, DAY, TZ, "tok", http) == 1
    [ev] = db.query(CalendarEvent).all()
    assert (ev.title, ev.attendees, ev.has_video) == ("Standup", 2, True)
    # deleted in Google -> removed here
    http = client({("GET", google_sync.CAL): lambda r: httpx.Response(200, json={"items": []})})
    google_sync.sync_calendar(db, ali, DAY, TZ, "tok", http)
    assert db.query(CalendarEvent).count() == 0


def test_gmail_counts_sent_and_replies_from_headers_only(db, ali):
    msgs = {"m1": {"threadId": "t1", "internalDate": str(int(datetime(2026, 10, 21, 6, tzinfo=UTC).timestamp() * 1000)),
                   "snippet": "Thanks, attached", "payload": {"headers": [
                       {"name": "Subject", "value": "Re: Invoice"}, {"name": "To", "value": "Client <c@client.com>"},
                       {"name": "In-Reply-To", "value": "<abc@x>"}]}},
            "m2": {"threadId": "t2", "internalDate": str(int(datetime(2026, 10, 21, 7, tzinfo=UTC).timestamp() * 1000)),
                   "snippet": "Hi", "payload": {"headers": [{"name": "Subject", "value": "New project"},
                                                            {"name": "To", "value": "a@x.com, b@y.com"}]}}}
    seen = {}

    def get_msg(r):
        seen["format"] = r.url.params.get("format")
        return httpx.Response(200, json=msgs[r.url.path.rsplit("/", 1)[1]])
    http = client({("GET", f"{google_sync.GMAIL}/messages/"): get_msg,
                   ("GET", f"{google_sync.GMAIL}/messages"): lambda r: httpx.Response(200, json={"messages": [{"id": "m1"}, {"id": "m2"}]})})
    assert google_sync.sync_gmail(db, ali, DAY, TZ, "tok", http) == 2
    assert google_sync.sync_gmail(db, ali, DAY, TZ, "tok", http) == 0
    assert seen["format"] == "metadata"  # never the body
    acts = {a.action: a for a in db.query(WorkAction).all()}
    assert set(acts) == {"replied", "new_thread"}
    assert acts["replied"].meta["to_domains"] == ["client.com"]
    assert acts["new_thread"].meta["recipients"] == 2


def test_drive_keeps_only_own_actions(db, ali):
    acts = {"activities": [
        {"primaryActionDetail": {"edit": {}}, "timestamp": "2026-10-21T06:00:00Z",
         "actors": [{"user": {"knownUser": {"isCurrentUser": True}}}],
         "targets": [{"driveItem": {"name": "items/1", "title": "Q4 plan", "mimeType": "application/vnd.google-apps.document"}}]},
        {"primaryActionDetail": {"edit": {}}, "timestamp": "2026-10-21T06:10:00Z",
         "actors": [{"user": {"knownUser": {"personName": "people/2"}}}],
         "targets": [{"driveItem": {"name": "items/1", "title": "Q4 plan"}}]},
        {"primaryActionDetail": {"permissionChange": {}}, "timestamp": "2026-10-21T07:00:00Z",
         "actors": [{"user": {"knownUser": {"isCurrentUser": True}}}],
         "targets": [{"driveItem": {"name": "items/9", "title": "Budget"}}]}]}
    http = client({("POST", google_sync.DRIVE_ACTIVITY): lambda r: httpx.Response(200, json=acts)})
    assert google_sync.sync_drive(db, ali, DAY, TZ, "tok", http) == 2
    assert sorted(a.action for a in db.query(WorkAction).all()) == ["edited", "shared"]


ISSUE = {"id": 12345, "summary": "Login fails", "project": {"name": "Portal"},
         "created_at": "2026-10-21T05:00:00+00:00", "updated_at": "2026-10-21T09:00:00+00:00",
         "reporter": {"name": "client1"},
         "notes": [{"id": 1, "created_at": "2026-10-21T06:00:00+00:00", "reporter": {"name": "ali.m"},
                    "text": "Please send logs", "view_state": {"name": "public"}},
                   {"id": 2, "created_at": "2026-10-20T06:00:00+00:00", "reporter": {"name": "ali.m"}, "text": "old"}],
         "history": [{"created_at": "2026-10-21T07:00:00+00:00", "user": {"name": "ali.m"}, "field": {"name": "handler"},
                      "new_value": {"name": "ali.m"}},
                     {"created_at": "2026-10-21T08:00:00+00:00", "user": {"name": "ali.m"}, "field": {"name": "status"},
                      "old_value": {"name": "assigned"}, "new_value": {"name": "resolved"}},
                     {"created_at": "2026-10-21T08:30:00+00:00", "user": {"name": "ali.m"}, "field": {"name": "status"},
                      "old_value": {"name": "resolved"}, "new_value": {"name": "feedback"}}]}


def test_mantis_credits_each_action_once(db, ali, make_user):
    make_user("other@example.com")
    pages = {"1": [ISSUE, {**ISSUE, "id": 1, "updated_at": "2026-10-19T00:00:00+00:00"}]}
    headers = {}

    def issues(r):
        headers["auth"] = r.headers.get("authorization")
        return httpx.Response(200, json={"issues": pages.get(r.url.params["page"], [])})
    http = client({("GET", "https://mantis.example.com/api/rest/issues/12345"): lambda r: httpx.Response(200, json={"issues": [ISSUE]}),
                   ("GET", "https://mantis.example.com/api/rest/issues"): issues})
    since = datetime(2026, 10, 21, 0, tzinfo=UTC)
    out = mantis.sync(db, "https://mantis.example.com/", since, http, api_token="secret")
    assert out == {"issues": 1, "added": 4, "unmatched": 1}  # the client's "reported" has no tracker user
    assert headers["auth"] == "secret"
    acts = sorted(a.action for a in db.query(WorkAction).all())
    assert acts == ["reopened", "resolved", "responded", "took"]
    assert mantis.sync(db, "https://mantis.example.com", since, http, api_token="secret")["added"] == 0
    note = db.query(WorkAction).filter_by(action="responded").one()
    assert note.meta["note_text"] == "Please send logs" and note.user_id == ali.id


def test_mantis_token_comes_only_from_environment(monkeypatch):
    monkeypatch.delenv(mantis.TOKEN_ENV, raising=False)
    with pytest.raises(mantis.MantisNotConfigured):
        mantis.token()
    monkeypatch.setenv(mantis.TOKEN_ENV, " abc ")
    assert mantis.token() == "abc"


def test_service_account_jwt_is_signed_rs256():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    jwt = google_auth.service_account_jwt({"client_email": "sa@p.iam.gserviceaccount.com", "private_key": pem},
                                          "ali@example.com", [google_auth.SCOPES["calendar"]], now=1000)
    import base64
    h, c, sig = jwt.split(".")
    claims = json.loads(base64.urlsafe_b64decode(c + "=="))
    assert claims["sub"] == "ali@example.com" and claims["exp"] == 4600 and "calendar.readonly" in claims["scope"]
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    key.public_key().verify(base64.urlsafe_b64decode(sig + "=="), f"{h}.{c}".encode(), padding.PKCS1v15(), hashes.SHA256())
