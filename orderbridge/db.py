"""Database engine and session helpers.

Pattern used everywhere: open a session, do the work, commit once. All changes
in that block (including outbox events) succeed or fail together.

    with session_scope() as session:
        ...
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from orderbridge.config import PROJECT_ROOT, settings

_engine: Engine | None = None
_engine_url: str | None = None


def get_engine() -> Engine:
    """Create the engine on first use (so tests can point settings at a test DB first)."""
    global _engine, _engine_url
    if _engine is None or _engine_url != settings.database_url:
        if _engine is not None:
            _engine.dispose()
        _engine = create_engine(settings.database_url, pool_pre_ping=True)
        _engine_url = settings.database_url
    return _engine


def new_session() -> Session:
    """A new ORM session. The caller is responsible for commit/rollback/close."""
    return Session(get_engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Commit if the block succeeds, roll back if it raises, always close."""
    session = new_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_database() -> None:
    """Drop everything and reload db/schema.sql and db/seed.sql (demo/test helper)."""
    schema = (PROJECT_ROOT / "db" / "schema.sql").read_text()
    seed = (PROJECT_ROOT / "db" / "seed.sql").read_text()
    raw = get_engine().raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            cur.execute(schema)
            cur.execute(seed)
        raw.commit()
    finally:
        raw.close()
