#!/usr/bin/env python3
"""Create the schema and seed the demo tenant (idempotent), without starting the API.

    python scripts/seed_demo.py            # uses DATABASE_URL, defaults to ./backend/churnce.db
    DATABASE_URL=postgresql+psycopg://... python scripts/seed_demo.py

The API seeds on first start when SEED_DEMO=true, so this is only needed to prepare a database ahead
of time or to re-seed after dropping it. It refuses to run when APP_ENV=production.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)  # so the default sqlite path and .env resolve the same way as when the API runs

if os.environ.get("APP_ENV", "").lower() == "production":
    sys.exit("Refusing to seed a demo tenant when APP_ENV=production.")
os.environ.setdefault("SEED_DEMO", "true")

from app.main import init_database  # noqa: E402
from app.seed import DEMO_INGEST_KEY, DEMO_PASSWORD, DEMO_USERS  # noqa: E402
from app.config import get_settings  # noqa: E402


def main() -> None:
    init_database()  # create_all + (on PostgreSQL) CREATE EXTENSION vector + HNSW index + seed_demo
    print(f"Database ready: {get_settings().database_url.split('@')[-1]}")
    print("Demo tenant seeded (or already present). Sign in with any of:")
    for email, name, role in DEMO_USERS:
        print(f"  {email:<26} {role:<20} password: {DEMO_PASSWORD}")
    print(f"Extension / ingest key: {DEMO_INGEST_KEY}")
    print("These credentials are public. Never use them outside a local demo.")


if __name__ == "__main__":
    main()
