"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Iterator

from fastapi import Header
from sqlalchemy.orm import Session

from orderbridge.db import new_session


def get_session() -> Iterator[Session]:
    """One database session per request. Routes commit explicitly; anything else rolls back."""
    session = new_session()
    try:
        yield session
    finally:
        session.close()


def get_actor(x_actor: str | None = Header(default=None, description="Who is calling (for the audit log)")) -> str:
    """Caller identity for the audit log. A real system would take this from an OAuth token."""
    return (x_actor or "api-client").strip()[:100]
