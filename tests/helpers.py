"""Small helpers shared by tests."""

from __future__ import annotations

from sqlalchemy import func, select

from orderbridge.db import new_session
from orderbridge.models import AuditLog, OutboxEvent


def outbox_types() -> list[str]:
    with new_session() as s:
        return list(s.scalars(select(OutboxEvent.event_type).order_by(OutboxEvent.id)))


def audit_rows() -> list[AuditLog]:
    with new_session() as s:
        return list(s.scalars(select(AuditLog).order_by(AuditLog.id)))


def count(model) -> int:
    with new_session() as s:
        return s.scalar(select(func.count()).select_from(model))
