"""Central configuration.

Values come from environment variables, with the git-ignored `.env` file in the
project root as a fallback. Nothing secret is hard-coded here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Real environment variables win over .env (override=False). That is how tests
# and Claude Code (`claude mcp add --env ...`) inject their own values.
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _database_url() -> str:
    """Use DATABASE_URL if given, otherwise build it from the POSTGRES_* values."""
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    password = os.getenv("POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError(
            "No database settings found. Copy .env.example to .env "
            "(cp .env.example .env) and set POSTGRES_PASSWORD."
        )
    user = os.getenv("POSTGRES_USER", "orderbridge")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    name = os.getenv("POSTGRES_DB", "orderbridge")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


def _project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass
class Settings:
    """All runtime settings in one place. Tests may change attributes directly."""

    database_url: str
    kafka_bootstrap_servers: str
    edi_root: Path
    our_isa_id: str
    edi_usage_indicator: str
    edi_poll_seconds: float
    publisher_poll_seconds: float

    @property
    def edi_inbound(self) -> Path:
        return self.edi_root / "inbound"

    @property
    def edi_outbound(self) -> Path:
        return self.edi_root / "outbound"

    @property
    def edi_processed(self) -> Path:
        return self.edi_root / "processed"

    @property
    def edi_error(self) -> Path:
        return self.edi_root / "error"


def load_settings() -> Settings:
    """Read settings from the environment (called once at import time)."""
    return Settings(
        database_url=_database_url(),
        kafka_bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092"),
        edi_root=_project_path(os.getenv("EDI_ROOT", "edi")),
        our_isa_id=os.getenv("OUR_ISA_ID", "ORDERBRIDGE"),
        edi_usage_indicator=os.getenv("EDI_USAGE_INDICATOR", "T"),
        edi_poll_seconds=float(os.getenv("EDI_POLL_SECONDS", "2")),
        publisher_poll_seconds=float(os.getenv("PUBLISHER_POLL_SECONDS", "1")),
    )


settings = load_settings()
