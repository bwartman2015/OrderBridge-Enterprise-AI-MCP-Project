"""Shared test fixtures.

Database tests run against a SEPARATE database (orderbridge_test by default) on the
same Postgres server, so running tests never touches your demo data. The schema
and seed are reloaded before every test, so tests cannot affect each other.

Override with TEST_DATABASE_URL=postgresql+psycopg://user:pass@host:port/dbname
"""

from __future__ import annotations

import os

import psycopg
import pytest
from sqlalchemy.engine import make_url

from orderbridge import config


def _test_database_url() -> str:
    if os.getenv("TEST_DATABASE_URL"):
        return os.environ["TEST_DATABASE_URL"]
    return make_url(config.settings.database_url).set(database="orderbridge_test").render_as_string(
        hide_password=False
    )


TEST_DATABASE_URL = _test_database_url()
# Point the whole app at the test database BEFORE any engine is created.
config.settings.database_url = TEST_DATABASE_URL
os.environ["DATABASE_URL"] = TEST_DATABASE_URL  # for subprocesses (MCP stdio test)


def _libpq_url(url: str, database: str | None = None) -> str:
    u = make_url(url).set(drivername="postgresql")
    if database:
        u = u.set(database=database)
    return u.render_as_string(hide_password=False)


def _ensure_test_database() -> str | None:
    """Create the test database if needed. Returns an error message if Postgres is unreachable."""
    name = make_url(TEST_DATABASE_URL).database
    try:
        with psycopg.connect(_libpq_url(TEST_DATABASE_URL, "postgres"), autocommit=True, connect_timeout=3) as conn:
            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
            if not exists:
                conn.execute(f'CREATE DATABASE "{name}"')
    except psycopg.OperationalError as exc:
        return str(exc).strip().splitlines()[0]
    return None


_DB_PROBLEM = _ensure_test_database()


@pytest.fixture
def db():
    """A freshly seeded test database for each test."""
    if _DB_PROBLEM:
        pytest.skip(f"Postgres not reachable ({_DB_PROBLEM}). Start it with: docker compose up -d")
    from orderbridge.db import reset_database

    reset_database()
    yield


@pytest.fixture
def session(db):
    from orderbridge.db import new_session

    s = new_session()
    yield s
    s.rollback()
    s.close()


@pytest.fixture
def edi_dirs(tmp_path, monkeypatch):
    """Point the EDI folders at a temporary directory."""
    monkeypatch.setattr(config.settings, "edi_root", tmp_path)
    for name in ("inbound", "outbound", "processed", "error"):
        (tmp_path / name).mkdir()
    return tmp_path


@pytest.fixture
def planner(monkeypatch):
    monkeypatch.setenv("MCP_ACTOR", "test-planner")
    monkeypatch.setenv("MCP_ROLE", "planner")


@pytest.fixture
def viewer(monkeypatch):
    monkeypatch.setenv("MCP_ACTOR", "test-viewer")
    monkeypatch.setenv("MCP_ROLE", "viewer")


@pytest.fixture
def api(db, edi_dirs):
    from fastapi.testclient import TestClient

    from orderbridge.api.main import app

    with TestClient(app) as client:
        yield client


SAMPLES = config.PROJECT_ROOT / "edi" / "samples"
