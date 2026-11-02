"""Audit trail shared by every channel (MCP tools, REST API, EDI, approval CLI).

Audit rows are written in their OWN transaction, so a failed or denied action is
still recorded even when the business transaction rolls back.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from orderbridge.db import session_scope
from orderbridge.models import AuditLog

log = logging.getLogger(__name__)

RESULTS = ("OK", "DENIED", "ERROR")


def _jsonable(arguments: dict[str, Any]) -> dict[str, Any]:
    """Make sure arguments can be stored as JSON (dates, Decimals become strings)."""
    return json.loads(json.dumps(arguments, default=str))


def record_audit(
    actor: str,
    role: str,
    tool_or_endpoint: str,
    arguments: dict[str, Any],
    result: str,
    detail: str | None = None,
) -> None:
    """Write one audit row. Never raises: auditing problems are logged instead."""
    if result not in RESULTS:
        raise ValueError(f"result must be one of {RESULTS}")
    try:
        with session_scope() as session:
            session.add(
                AuditLog(
                    actor=actor or "unknown",
                    role=role or "unknown",
                    tool_or_endpoint=tool_or_endpoint,
                    arguments=_jsonable(arguments),
                    result=result,
                    detail=(detail or "")[:2000] or None,
                )
            )
    except Exception:  # pragma: no cover - only when the database itself is down
        log.exception("Could not write audit log entry for %s", tool_or_endpoint)


def recent_audit_entries(session: Session, limit: int = 20) -> list[dict[str, Any]]:
    """Newest audit entries first."""
    rows = session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))
    return [
        {
            "id": r.id,
            "timestamp": r.timestamp.isoformat(),
            "actor": r.actor,
            "role": r.role,
            "tool_or_endpoint": r.tool_or_endpoint,
            "arguments": r.arguments,
            "result": r.result,
            "detail": r.detail,
        }
        for r in rows
    ]
