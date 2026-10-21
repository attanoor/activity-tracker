from conftest import login


def setup(client, make_user):
    admin = make_user("admin@example.com", role="admin")
    res = make_user("res@example.com")
    login(client, "admin@example.com")
    return admin, res


def test_people_list_edit_and_disable(client, make_user):
    admin, res = setup(client, make_user)
    team = client.post("/admin/teams", json={"name": "Support"}).json()
    people = {p["email"]: p for p in client.get("/admin/people").json()}
    assert people["res@example.com"]["devices"] == 0 and people["res@example.com"]["active"]

    r = client.patch(f"/admin/people/{res.id}", json={"name": "Res One", "role": "manager", "team_id": team["id"]})
    assert r.status_code == 200 and (r.json()["name"], r.json()["role"], r.json()["team_id"]) == ("Res One", "manager", team["id"])
    assert client.patch(f"/admin/people/{res.id}", json={"clear_team": True}).json()["team_id"] is None
    assert client.patch(f"/admin/people/{res.id}", json={"role": "boss"}).status_code == 422
    assert client.patch(f"/admin/people/{res.id}", json={"team_id": 999}).status_code == 422

    # Disabling signs the person out and blocks sign-in and their PCs.
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as other:
        login(other, "res@example.com")
        code = other.post("/me/enrol-codes").json()["code"]
        token = other.post("/devices/enrol", json={"code": code, "hostname": "PC"}).json()["token"]
        assert client.patch(f"/admin/people/{res.id}", json={"active": False}).json()["active"] is False
        assert other.get("/auth/me").status_code == 401
        assert other.post("/auth/login", json={"email": "res@example.com", "password": "correct-horse"}).status_code == 401
        r = other.post("/ingest/events", json={"events": []}, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401


def test_admin_cannot_lock_themselves_out(client, make_user):
    admin, _ = setup(client, make_user)
    assert client.patch(f"/admin/people/{admin.id}", json={"role": "resource"}).status_code == 400
    assert client.patch(f"/admin/people/{admin.id}", json={"active": False}).status_code == 400
    assert client.patch(f"/admin/people/{admin.id}", json={"name": "Boss"}).status_code == 200


def test_reset_password(client, make_user):
    _, res = setup(client, make_user)
    pw = client.post(f"/admin/people/{res.id}/reset-password").json()["password"]
    assert len(pw) >= 12
    client.post("/auth/logout")
    assert client.post("/auth/login", json={"email": "res@example.com", "password": "correct-horse"}).status_code == 401
    login(client, "res@example.com", pw)


def test_devices_list_and_revoke(client, make_user):
    _, res = setup(client, make_user)
    code = client.post(f"/admin/users/{res.id}/enrol-codes").json()["code"]
    token = client.post("/devices/enrol", json={"code": code, "hostname": "PC-RES"}).json()["token"]
    [d] = client.get(f"/admin/people/{res.id}/devices").json()
    assert d["hostname"] == "PC-RES" and d["revoked_at"] is None
    assert client.post(f"/admin/devices/{d['id']}/revoke").json()["revoked_at"] is not None
    r = client.post("/ingest/events", json={"events": []}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert [p for p in client.get("/admin/people").json() if p["id"] == res.id][0]["devices"] == 0


def test_team_edit_rules(client, make_user):
    _, res = setup(client, make_user)
    t = client.post("/admin/teams", json={"name": "A"}).json()
    client.post("/admin/teams", json={"name": "B"})
    assert client.patch(f"/admin/teams/{t['id']}", json={"name": "B"}).status_code == 409
    assert client.patch(f"/admin/teams/{t['id']}", json={"shift_end": "08:00:00"}).status_code == 422
    assert client.patch(f"/admin/teams/{t['id']}", json={"manager_id": res.id}).status_code == 422  # not a manager
    client.patch(f"/admin/people/{res.id}", json={"role": "manager"})
    r = client.patch(f"/admin/teams/{t['id']}", json={"manager_id": res.id, "break_minutes": 45, "timezone": "Asia/Karachi"})
    assert r.status_code == 200 and (r.json()["manager_id"], r.json()["break_minutes"]) == (res.id, 45)
    assert client.patch(f"/admin/teams/{t['id']}", json={"timezone": "Mars/Base"}).status_code == 422


def test_admin_endpoints_need_admin(client, make_user):
    make_user("res@example.com")
    login(client, "res@example.com")
    assert client.get("/admin/people").status_code == 403
    assert client.post("/admin/people/1/reset-password").status_code == 403
