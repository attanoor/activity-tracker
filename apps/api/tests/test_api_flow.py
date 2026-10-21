import gzip
import json
from datetime import UTC, datetime, timedelta

from conftest import login

DAY = "2026-10-21"
T0 = datetime(2026, 10, 21, 4, 0, tzinfo=UTC)  # 09:00 in Asia/Karachi


def ev(seq, minute, secs, kind="active", **kw):
    return {"seq": seq, "started_at": (T0 + timedelta(minutes=minute)).isoformat(), "duration_s": secs,
            "kind": kind, **kw}


def enrolled_device(client, make_user):
    make_user("admin@example.com", role="admin")
    login(client, "admin@example.com")
    team = client.post("/admin/teams", json={"name": "Support", "timezone": "Asia/Karachi"}).json()
    user = client.post("/admin/users", json={"email": "Ali@Example.com", "name": "Ali", "password": "correct-horse",
                                             "team_id": team["id"]}).json()
    code = client.post(f"/admin/users/{user['id']}/enrol-codes").json()["code"]
    client.post("/auth/logout")
    r = client.post("/devices/enrol", json={"code": code.lower(), "hostname": "PC-ALI"})
    assert r.status_code == 201, r.text
    return code, r.json()["token"]


def post_events(client, token, events, gz=False):
    body = json.dumps({"events": events}).encode()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if gz:
        body, headers["Content-Encoding"] = gzip.compress(body), "gzip"
    return client.post("/ingest/events", content=body, headers=headers)


def test_full_flow(client, make_user):
    code, token = enrolled_device(client, make_user)

    # The code is single-use.
    assert client.post("/devices/enrol", json={"code": code, "hostname": "x"}).status_code == 400

    events = [
        ev(1, 0, 1800, app="code.exe", title="ingest.py - activity-tracker"),
        ev(2, 30, 600, app="chrome.exe", url="https://mail.google.com/mail/u/0", title="Inbox"),
        ev(3, 40, 300, kind="idle"),
        ev(4, 45, 900, kind="private", app="chrome.exe", title="Bank", domain="bank.example"),
        ev(5, 60, 1200, app="chrome.exe", domain="mantis.example.com", title="0012345: Login fails - MantisBT",
           url="https://mantis.example.com/view.php?id=12345"),
    ]
    r = post_events(client, token, events, gz=True)
    assert r.json() == {"accepted": 5, "duplicates": 0, "max_seq": 5}
    # Re-sending (agent retry after a lost response) is a no-op.
    assert post_events(client, token, events).json() == {"accepted": 0, "duplicates": 5, "max_seq": 5}

    login(client, "ali@example.com")
    day = client.get(f"/me/days/{DAY}").json()
    assert day["total_s"] == 1800 + 600 + 300 + 900 + 1200
    assert day["by_klass"] == {"productive": 3000, "communication": 600, "idle": 300, "private": 900}
    cats = [(s["category"], s["klass"]) for s in day["sessions"]]
    assert cats == [("Development", "productive"), ("Email", "communication"), (None, "idle"),
                    (None, "private"), ("Ticket work", "productive")]
    private = day["sessions"][3]
    assert private["app"] is None and private["title"] is None and private["domain"] is None
    assert day["sessions"][4]["paths"] == [["/view.php?id=12345", 1200]]

    # Rebuilding is idempotent.
    assert client.get(f"/me/days/{DAY}").json()["total_s"] == day["total_s"]


def test_private_details_are_dropped_at_ingest(client, make_user, db):
    from app.models import RawEvent
    _, token = enrolled_device(client, make_user)
    post_events(client, token, [ev(1, 0, 60, kind="private", app="a", title="secret", url="https://s/x")])
    row = db.query(RawEvent).one()
    assert (row.app, row.title, row.url, row.domain) == (None, None, None, None)


def test_ingest_rejects_bad_input(client, make_user, db):
    from app.models import Device
    _, token = enrolled_device(client, make_user)
    future = {"seq": 1, "started_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(), "duration_s": 5,
              "kind": "active"}
    assert post_events(client, token, [future]).status_code == 422
    assert post_events(client, token, [ev(1, 0, 5, kind="hacking")]).status_code == 422
    naive = {"seq": 1, "started_at": "2026-10-21T09:00:00", "duration_s": 5, "kind": "active"}
    assert post_events(client, token, [naive]).status_code == 422
    assert post_events(client, "wrong-token", [ev(1, 0, 5)]).status_code == 401

    device = db.query(Device).one()
    device.revoked_at = datetime.now(UTC)
    db.commit()
    assert post_events(client, token, [ev(1, 0, 5)]).status_code == 401


def test_roles_and_auth(client, make_user):
    make_user("res@example.com")
    assert client.get(f"/me/days/{DAY}").status_code == 401
    login(client, "res@example.com")
    assert client.get("/admin/users").status_code == 403
    assert client.post("/auth/login", json={"email": "res@example.com", "password": "nope"}).status_code == 401
