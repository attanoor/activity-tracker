import json

from conftest import login


def test_self_service_code_enrols_own_device(client, make_user, db):
    from app.models import Device
    me = make_user("res@example.com")
    login(client, "res@example.com")
    code = client.post("/me/enrol-codes").json()["code"]
    client.post("/auth/logout")
    assert client.post("/devices/enrol", json={"code": code, "hostname": "PC1"}).status_code == 201
    assert db.query(Device).one().user_id == me.id


def test_codes_need_login(client):
    assert client.post("/me/enrol-codes").status_code == 401
    assert client.get("/downloads").status_code == 401


def test_change_password(client, make_user):
    make_user("res@example.com")
    login(client, "res@example.com")
    bad = client.post("/auth/change-password", json={"current_password": "wrong", "new_password": "x" * 12})
    assert bad.status_code == 400
    short = client.post("/auth/change-password", json={"current_password": "correct-horse", "new_password": "short"})
    assert short.status_code == 422
    ok = client.post("/auth/change-password",
                     json={"current_password": "correct-horse", "new_password": "a-much-better-one"})
    assert ok.status_code == 204
    assert client.get("/auth/me").status_code == 200  # this session stays signed in
    client.post("/auth/logout")
    assert client.post("/auth/login", json={"email": "res@example.com", "password": "correct-horse"}).status_code == 401
    login(client, "res@example.com", "a-much-better-one")


def test_downloads_listing_and_path_safety(client, make_user, tmp_path, monkeypatch):
    from app.routers import downloads
    monkeypatch.setattr(downloads, "DOWNLOADS", tmp_path)
    (tmp_path / "agent.exe").write_bytes(b"MZ-test")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "agent": {"file": "agent.exe", "version": "0.1.0", "size": 7, "sha256": "abc", "built_at": "now"},
        "extension": {"file": "missing.zip", "version": "0.1.0", "size": 1, "sha256": "x", "built_at": "now"},
        "evil": {"file": "../secret.txt", "version": "0", "size": 1, "sha256": "x", "built_at": "now"},
    }))
    (tmp_path.parent / "secret.txt").write_text("no")
    make_user("res@example.com")
    login(client, "res@example.com")
    assert [d["key"] for d in client.get("/downloads").json()] == ["agent"]
    assert client.get("/downloads/agent").content == b"MZ-test"
    assert client.get("/downloads/extension").status_code == 404
    assert client.get("/downloads/evil").status_code == 404
