"""Role-based authorization for MCP tools.

Identity comes from environment variables that Claude Code passes when it starts
the server (`claude mcp add ... --env MCP_ACTOR=brad --env MCP_ROLE=planner`).
In production this would come from an OAuth token instead (see README).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

READ = "read"
WRITE = "write"

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "viewer": frozenset({READ}),
    "planner": frozenset({READ, WRITE}),
}


@dataclass(frozen=True)
class Identity:
    actor: str
    role: str


def current_identity() -> Identity:
    """Read on every call, so a misconfiguration can never be cached into a wider grant."""
    actor = os.getenv("MCP_ACTOR", "").strip() or "unknown"
    # Least privilege: no role configured means read-only.
    role = os.getenv("MCP_ROLE", "").strip().lower() or "viewer"
    return Identity(actor=actor, role=role)


def is_allowed(identity: Identity, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(identity.role, frozenset())


def denial_message(identity: Identity, tool: str, permission: str) -> str:
    if identity.role not in ROLE_PERMISSIONS:
        return (
            f"ACCESS DENIED: role '{identity.role}' is not recognised (valid roles: "
            f"{', '.join(ROLE_PERMISSIONS)}). '{tool}' was not run. This attempt was logged."
        )
    return (
        f"ACCESS DENIED: '{identity.actor}' has role '{identity.role}', which does not allow "
        f"{permission} tools such as '{tool}'. Ask a user with the 'planner' role. "
        "This attempt was logged in the audit trail."
    )
