"""Idempotency keys for POST /orders.

A client sends a unique Idempotency-Key header with each new order. If the network
drops and the client retries with the SAME key and SAME body, we return the
original response instead of creating a second order. The same key with a
DIFFERENT body is a client bug, so we answer 409 Conflict.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from orderbridge.models import IdempotencyKey


def fingerprint(body: dict[str, Any]) -> str:
    """SHA-256 of the body in a canonical form (sorted keys, no extra spaces)."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def find(session: Session, key: str) -> IdempotencyKey | None:
    return session.get(IdempotencyKey, key)


def remember(session: Session, key: str, request_hash: str, status_code: int, response: dict) -> None:
    """Store the response in the SAME transaction as the order it describes."""
    session.add(
        IdempotencyKey(key=key, request_hash=request_hash, status_code=status_code, response=response)
    )
