"""Integration tests run against the `activity_test` database (created by scripts/setup.ps1).

The schema is rebuilt from the Alembic migrations once per run, so the migrations themselves are tested.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
API = ROOT / "apps" / "api"


def _test_url() -> str | None:
    url = os.environ.get("TRACKER_TEST_DATABASE_URL")
    env_file = ROOT / ".local" / ".env"
    if not url and env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("TRACKER_TEST_DATABASE_URL="):
                url = line.split("=", 1)[1].strip()
    return url


TEST_URL = _test_url()
if TEST_URL:
    # Must happen before `app` is imported, so the app's engine points at the test database.
    os.environ["TRACKER_DATABASE_URL"] = TEST_URL


@pytest.fixture(scope="session")
def migrated():
    if not TEST_URL:
        pytest.skip("no test database configured (run scripts/setup.ps1)")
    from sqlalchemy import create_engine, text
    eng = create_engine(TEST_URL)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    eng.dispose()
    env = {**os.environ, "TRACKER_MIGRATE_URL": TEST_URL}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API, env=env, check=True)


@pytest.fixture()
def db(migrated):
    from sqlalchemy import text

    from app.db import SessionLocal, engine
    from app.seed import ensure_defaults
    with engine.begin() as c:
        tables = c.execute(text(
            "SELECT string_agg(quote_ident(tablename), ',') FROM pg_tables "
            "WHERE schemaname='public' AND tablename <> 'alembic_version'")).scalar()
        c.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    with SessionLocal() as s:
        ensure_defaults(s)
        yield s


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def make_user(db):
    from app.models import User
    from app.security import hash_password

    def make(email="res@example.com", role="resource", password="correct-horse", **kw):
        u = User(email=email, name=email.split("@")[0], password_hash=hash_password(password), role=role, **kw)
        db.add(u)
        db.commit()
        return u
    return make


def login(client, email, password="correct-horse"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()
