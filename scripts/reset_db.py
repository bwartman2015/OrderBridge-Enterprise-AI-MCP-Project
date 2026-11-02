#!/usr/bin/env python
"""Wipe the database and reload db/schema.sql + db/seed.sql.

Seed dates are relative to today, so run this on a new day to refresh the demo
scenarios (at-risk orders etc.). Usage:  python scripts/reset_db.py [--yes]
"""

import argparse

from sqlalchemy.engine import make_url

from orderbridge.config import settings
from orderbridge.db import reset_database


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args()
    target = make_url(settings.database_url).render_as_string(hide_password=True)
    if not args.yes:
        answer = input(f"This deletes ALL data in {target}. Type 'reset' to continue: ")
        if answer.strip() != "reset":
            print("Cancelled.")
            return
    reset_database()
    print(f"Database reset and re-seeded: {target}")
    print("Note: events already in Redpanda are not removed (that is fine for the demo).")


if __name__ == "__main__":
    main()
