"""Demo tenant seeding. Runs only when SEED_DEMO is true AND the database has no organization yet.

The demo tenant is flagged environment="demo": every event it ingests is labelled as simulated and
the dashboard says so. Credentials below are for local demonstration only; keep SEED_DEMO off for
anything else.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .enums import DEFAULT_JOURNEY_MAP
from .models import Customer, MonitoringConfig, Organization, User
from .rag.store import ingest_document
from .security import ROLES, hash_ingest_key, hash_password
from .config import get_settings

log = logging.getLogger("churnce.seed")
settings = get_settings()

DEMO_PASSWORD = "Churnce!2026"
DEMO_INGEST_KEY = "chn_live_demo_northwind_0000000000000000"
SEED_DIR = Path(__file__).resolve().parent.parent / "seed_data"

DEMO_USERS = [
    ("admin@churnce.demo", "Ada Admin", "administrator"),
    ("analyst@churnce.demo", "Priya Analyst", "product_analyst"),
    ("engineer@churnce.demo", "Eli Engineer", "engineer"),
    ("marketing@churnce.demo", "Maya Marketing", "marketing_operator"),
    ("reviewer@churnce.demo", "Rae Reviewer", "reviewer"),
]

# (ref, email, consent, suppressed)
DEMO_CUSTOMERS = [
    ("cust_001", "amina.k@example.com", "opt_in", False),
    ("cust_002", "brian.o@example.com", "opt_in", False),
    ("cust_003", "carol.w@example.com", "opt_in", False),
    ("cust_004", "david.m@example.com", "opt_in", False),
    ("cust_005", "esther.n@example.com", "opt_in", False),
    ("cust_006", "farid.a@example.com", "opt_out", False),  # never contacted
    ("cust_007", "grace.l@example.com", "opt_in", True),  # unsubscribed
    ("cust_008", "hassan.i@example.com", "unknown", False),  # no recorded consent
    ("cust_009", "irene.j@example.com", "opt_in", False),
    ("cust_010", "joel.t@example.com", "opt_in", False),
]


def seed_knowledge(db: Session, org_id: str) -> int:
    path = SEED_DIR / "knowledge.json"
    if not path.exists():
        return 0
    n = 0
    for d in json.loads(path.read_text()):
        n += ingest_document(db, org_id, d["collection"], d["source_ref"], d["title"], d["body"], source_type="seed")
    return n


def seed_demo(db: Session) -> bool:
    if not settings.seed_demo or db.scalar(select(Organization.id).limit(1)):
        return False
    assert {r for _, _, r in DEMO_USERS} <= set(ROLES)
    org = Organization(name="Northwind Goods (demo tenant)")
    db.add(org)
    db.flush()
    db.add(
        MonitoringConfig(
            org_id=org.id,
            site_name="Northwind demo shop",
            environment="demo",
            authorized_domains=["localhost", "127.0.0.1", "demo.churnce.local", "*.churnce.demo"],
            allowed_event_types=[],
            ingest_key_hash=hash_ingest_key(DEMO_INGEST_KEY),
            ingest_key_prefix=DEMO_INGEST_KEY[:12],
            review_seconds=settings.review_seconds,
            journey_map=dict(DEFAULT_JOURNEY_MAP),
            cta_url="http://localhost:8081/",
        )
    )
    for email, name, role in DEMO_USERS:
        db.add(User(org_id=org.id, email=email, name=name, role=role, password_hash=hash_password(DEMO_PASSWORD)))
    for ref, email, consent, suppressed in DEMO_CUSTOMERS:
        db.add(Customer(org_id=org.id, ref=ref, email=email, consent=consent, suppressed=suppressed))
    db.flush()
    docs = seed_knowledge(db, org.id)
    db.commit()
    log.warning("Seeded DEMO tenant (%s knowledge passages). Login: admin@churnce.demo / %s. Disable with SEED_DEMO=false.", docs, DEMO_PASSWORD)
    return True
