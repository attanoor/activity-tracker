import gzip
import json
from datetime import UTC, date, datetime, timedelta

import pytest

from app.clients import domains, email_time, learn
from app.clients.resolve import Resolver
from app.models import (ActivitySession, CalendarEvent, Client, ClientIdentifier, Device, DsrReport, Team, Ticket,
                        WorkAction)
from conftest import login

DAY = date(2026, 10, 21)
T0 = datetime(2026, 10, 21, 4, 0, tzinfo=UTC)  # 09:00 Asia/Karachi


def make_client(db, name, status="confirmed", **ids):
    c = Client(name=name, status=status)
    db.add(c)
    db.flush()
    for kind, values in ids.items():
        for v in values if isinstance(values, list) else [values]:
            db.add(ClientIdentifier(client_id=c.id, kind=kind, value=v.lower(), source="admin"))
    db.commit()
    return c


# --- helpers --------------------------------------------------------------------------------------------
def test_domain_helpers():
    assert domains.registrable("bo.riverclub.co.uk") == "riverclub.co.uk"
    assert domains.parents("www.member.riverclub.com") == ["member.riverclub.com", "riverclub.com"]
    assert not domains.is_external("gmail.com", set())
    assert not domains.is_external("mail.globalnorthstar.com", {"globalnorthstar.com"})
    assert domains.is_external("riverclub.com", {"globalnorthstar.com"})
    assert domains.guess_name_from_domain("river-oaks-cc.com") == "River Oaks Cc"
    assert domains.norm_name("The River Club, Inc.") == "river club"


def test_gmail_title_subjects():
    s = email_time.subject_from_title
    assert s("Re: Fwd: Billing setup for March - ali@globalnorthstar.com - Gmail") == "billing setup for march"
    assert s("Inbox (12) - ali@globalnorthstar.com - Gmail") is None
    assert s("Search results - ali@x.com - Gmail") is None
    assert s("Billing - Google Docs") is None
    assert email_time.normalize_subject("RE: [External] Re:  Menu  upload") == "menu upload"


# --- resolver -------------------------------------------------------------------------------------------
def test_resolver_order_and_confirmed_only(db):
    river = make_client(db, "River Club", web_domain="riverclub.com", email_domain="riverclub.com", mantis_project="River Club POS")
    oaks = make_client(db, "Oak Hills Country Club", name_alias="oak hills")
    make_client(db, "Pending Club", status="suggested", web_domain="pending.com")
    db.add(Ticket(id="10231", project="River Club POS", summary="Receipt VAT"))
    db.commit()
    r = Resolver(db)
    assert r.by_host("bo.riverclub.com") == river.id
    assert r.by_host("pending.com") is None  # not confirmed yet
    assert r.by_text("Welcome to Oak Hills Country Club") == oaks.id
    assert r.by_text("oak hills") == oaks.id
    assert r.by_ticket("10231") == river.id
    assert r.by_emails(["me@globalnorthstar.com", "gm@riverclub.com", "x@gmail.com"]) == river.id
    # The web domain wins over a different club name on the page.
    assert r.for_session("riverclub.com", "Oak Hills Country Club", None, None) == river.id


def test_internal_and_public_domains_never_match(db):
    from app import settings_store
    settings_store.update(db, "clients", {"internal_domains": ["globalnorthstar.com"]})
    make_client(db, "Ours", email_domain="globalnorthstar.com")
    assert Resolver(db).by_emails(["a@globalnorthstar.com", "b@gmail.com"]) is None


# --- learning -------------------------------------------------------------------------------------------
def test_learn_suggests_and_import_confirms(db, make_user):
    u = make_user("ali@example.com")
    db.add(ActivitySession(user_id=u.id, day=DAY, started_at=T0, ended_at=T0 + timedelta(minutes=30), duration_s=1800,
                           kind="active", app="chrome.exe", domain="bo.riverclub.com", title="Members", klass="neutral",
                           club="River Club", section="Membership › Billing", contexts=[]))
    for i in range(2):
        db.add(WorkAction(ext_key=f"g{i}", user_id=u.id, day=DAY, source="gmail", action="replied", object_id="t",
                          object_title="Menu", at=T0, meta={"to": [{"email": f"gm{i}@oakhills.com", "name": "GM"}]}))
    db.add(Ticket(id="5", project="Lakeside POS", summary="x"))
    db.commit()
    out = learn.learn(db, DAY - timedelta(days=1))
    assert out == {"web_domain": 1, "email_domain": 1, "mantis_project": 1}
    names = {c.name: c.status for c in db.query(Client)}
    assert names == {"River Club": "suggested", "Oakhills": "suggested", "Lakeside POS": "suggested"}
    # Admin import of the club list confirms and merges by name, and adds domains.
    res = learn.import_names(db, ["River Club, riverclub.com", "Brand New CC", ""])
    assert res["new"] == 1 and res["identifiers"] == 1
    assert db.query(Client).filter_by(name="River Club").one().status == "confirmed"
    # Learning again adds nothing new.
    assert learn.learn(db, DAY - timedelta(days=1)) == {}


# --- pipeline: page context -> sessions -> client --------------------------------------------------------
def post(client_, token, events):
    body = gzip.compress(json.dumps({"events": events}).encode())
    return client_.post("/ingest/events", content=body, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json", "Content-Encoding": "gzip"})


@pytest.fixture()
def tracked(client, db, make_user):
    team = Team(name="Support", timezone="Asia/Karachi")
    db.add(team)
    db.commit()
    u = make_user("ali@example.com", team_id=team.id)
    from app.security import token_hash
    db.add(Device(user_id=u.id, hostname="PC", token_hash=token_hash("tok")))
    db.commit()
    return u


def ev(seq, minute, secs, **kw):
    return {"seq": seq, "started_at": (T0 + timedelta(minutes=minute)).isoformat(), "duration_s": secs,
            "kind": kw.pop("kind", "active"), **kw}


def test_context_splits_sessions_by_club_and_attributes(client, db, tracked):
    river = make_client(db, "River Club", name_alias="river club")
    oaks = make_client(db, "Oak Hills", web_domain="oakhills.com")
    bo = {"app": "chrome.exe", "domain": "backoffice.northstar.example", "url": "https://backoffice.northstar.example/members"}
    events = [
        ev(1, 0, 1200, title="Members", context={"clubs": ["River Club"], "crumbs": ["Membership", "Billing"]}, **bo),
        ev(2, 20, 600, title="Members", context={"clubs": ["Oak Hills"], "crumbs": ["Membership", "Dues"]}, **bo),
        ev(3, 30, 300, title="Members", kind="private", context={"clubs": ["Secret"]}),
        ev(4, 35, 900, app="chrome.exe", domain="oakhills.com", url="https://oakhills.com/menu", title="Menu"),
    ]
    assert post(client, "tok", events).json()["accepted"] == 4
    login(client, "ali@example.com")
    client.get(f"/me/days/{DAY}")
    rows = db.query(ActivitySession).filter_by(kind="active").order_by(ActivitySession.started_at).all()
    assert [(r.club, r.section, r.client_id) for r in rows] == [
        ("River Club", "Membership › Billing", river.id),
        ("Oak Hills", "Membership › Dues", oaks.id),
        (None, None, oaks.id),
    ]
    private = db.query(ActivitySession).filter_by(kind="private").one()
    assert private.club is None and private.contexts == []


def test_context_size_limit(client, tracked):
    big = {"crumbs": ["x" * 500] * 10}
    assert post(client, "tok", [ev(1, 0, 60, app="chrome.exe", domain="a.com", context=big)]).status_code == 422


# --- time by client -------------------------------------------------------------------------------------
def test_by_client_channels(client, db, tracked):
    river = make_client(db, "River Club", web_domain="riverclub.com", email_domain="riverclub.com",
                                              mantis_project="River POS")
    events = [
        ev(1, 0, 1800, app="chrome.exe", domain="riverclub.com", url="https://riverclub.com/bo", title="Setup"),
        ev(2, 30, 600, app="chrome.exe", domain="mail.google.com", url="https://mail.google.com/mail/u/0",
           title="Re: Menu upload - ali@example.com - Gmail"),
        ev(3, 40, 300, app="chrome.exe", domain="mail.google.com", url="https://mail.google.com/mail/u/0",
           title="Inbox (3) - ali@example.com - Gmail"),
    ]
    post(client, "tok", events)
    db.add(WorkAction(ext_key="g1", user_id=tracked.id, day=DAY, source="gmail", action="received", object_id="th",
                      object_title="Menu upload", at=T0, meta={"from": [{"email": "gm@riverclub.com", "name": "GM"}]}))
    db.add(WorkAction(ext_key="g2", user_id=tracked.id, day=DAY, source="gmail", action="replied", object_id="th",
                      object_title="Re: Menu upload", at=T0, meta={"to": [{"email": "gm@riverclub.com", "name": "GM"}]}))
    db.add(WorkAction(ext_key="m1", user_id=tracked.id, day=DAY, source="mantis", action="reported", object_id="77",
                      object_title="Bug", at=T0, meta={"project": "River POS", "category": "Bug"}))
    db.add(CalendarEvent(user_id=tracked.id, day=DAY, ext_id="e1", title="River call", attendees=3,
                         attendee_domains=["riverclub.com"], started_at=T0 + timedelta(hours=3),
                         ended_at=T0 + timedelta(hours=3, minutes=30)))
    db.commit()
    login(client, "ali@example.com")
    o = client.get(f"/me/overview/{DAY}").json()
    rows = {r["client"]: r for r in o["analysis"]["by_client"]["rows"]}
    r = rows["River Club"]
    assert (r["web_s"], r["email_s"], r["meetings_s"]) == (1800, 600, 1800)
    assert (r["emails_sent"], r["emails_received"]) == (1, 1)
    assert r["ticket_actions"] == {"reported": 1} and r["issue_types"] == {"Bug": 1}
    assert rows["No client"]["email_s"] == 300  # the inbox list view has no client
    # Manual off-PC work for the client is added, and shows in the analysis.
    m = client.post("/me/manual-entries", json={"day": str(DAY), "start": "15:00", "end": "15:45", "kind": "site_visit",
                                                "title": "On-site POS training", "client_id": river.id})
    assert m.status_code == 201
    o = client.get(f"/me/overview/{DAY}").json()
    r = {x["client"]: x for x in o["analysis"]["by_client"]["rows"]}["River Club"]
    assert r["manual_s"] == 2700


# --- daily lock and reopen ------------------------------------------------------------------------------
def test_daily_lock_and_manager_reopen(client, db, tracked, make_user):
    from app import settings_store
    settings_store.update(db, "tracking", {"edit_hours_after_day": 12})
    old = date.today() - timedelta(days=3)
    login(client, "ali@example.com")
    r = client.post("/me/manual-entries", json={"day": str(old), "start": "10:00", "end": "11:00", "kind": "call", "title": "x"})
    assert r.status_code == 409 and "closed" in r.json()["detail"]
    assert client.post(f"/me/dsr/{old}/generate").status_code == 409
    client.post("/auth/logout")

    boss = make_user("boss@example.com", role="manager")
    team = db.get(Team, tracked.team_id)
    team.manager_id = boss.id
    db.commit()
    login(client, "boss@example.com")
    out = client.post(f"/people/{tracked.id}/dsr/{old}/reopen").json()
    assert out["editable"] and out["reopened"]
    client.post("/auth/logout")

    login(client, "ali@example.com")
    assert client.post("/me/manual-entries", json={"day": str(old), "start": "10:00", "end": "11:00", "kind": "call",
                                                   "title": "Client call"}).status_code == 201
    # A resource can't reopen.
    assert client.post(f"/people/{tracked.id}/dsr/{old}/reopen").status_code == 403
    # Today stays editable without any reopen.
    assert client.get(f"/me/manual-entries?day={date.today()}").json()["editable"] is True
    assert db.query(DsrReport).one().reopened_by == boss.id


# --- admin endpoints ------------------------------------------------------------------------------------
def test_admin_clients_endpoints(client, db, make_user):
    make_user("admin@example.com", role="admin")
    login(client, "admin@example.com")
    a = client.post("/admin/clients", json={"name": "River Club"}).json()
    b = client.post("/admin/clients", json={"name": "River Golf (dup)"}).json()
    assert client.post("/admin/clients", json={"name": "river club"}).status_code == 409
    client.post(f"/admin/clients/{a['id']}/identifiers", json={"kind": "web_domain", "value": "https://www.RiverClub.com/x"})
    assert client.post(f"/admin/clients/{b['id']}/identifiers",
                       json={"kind": "web_domain", "value": "riverclub.com"}).status_code == 409
    client.post(f"/admin/clients/{b['id']}/identifiers", json={"kind": "email_domain", "value": "rivergolf.com"})
    merged = client.post(f"/admin/clients/{b['id']}/merge", json={"into_id": a["id"]}).json()
    assert sorted((i["kind"], i["value"]) for i in merged["identifiers"]) == [
        ("email_domain", "rivergolf.com"), ("name_alias", "river golf (dup)"), ("web_domain", "riverclub.com")]
    imp = client.post("/admin/clients/import", json={"text": "Oak Hills CC, oakhills.com\nRiver Club"}).json()
    assert imp["new"] == 1
    assert [c["name"] for c in client.get("/clients").json()] == ["Oak Hills CC", "River Club"]
    assert client.patch(f"/admin/clients/{a['id']}", json={"status": "ignored"}).json()["status"] == "ignored"
