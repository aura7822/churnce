"""Website-ID sessions see one website only. These helpers express that limit once, so every list endpoint applies it the same way."""
from __future__ import annotations

from sqlalchemy import select

from .models import Chunk, Customer, Incident, SessionRec
from .security import Principal


def session_ids(p: Principal):
    """Sub-select of the session ids that belong to the principal's website (callers use it with `.in_(...)`)."""
    return select(SessionRec.id).where(SessionRec.org_id == p.org_id, SessionRec.site_host == p.site_host)


def chunk_ids(db, p: Principal) -> set[str]:
    return set(db.scalars(select(Chunk.id).where(Chunk.org_id == p.org_id, Chunk.session_id.in_(session_ids(p))).limit(20000)).all())


def incident_ids(db, p: Principal) -> set[str]:
    """Incidents that contain at least one chunk from this website."""
    mine = chunk_ids(db, p)
    out: set[str] = set()
    for inc in db.scalars(select(Incident).where(Incident.org_id == p.org_id).limit(5000)).all():
        if mine.intersection(inc.chunk_ids or []):
            out.add(inc.id)
    return out


def customer_ids(db, p: Principal) -> set[str]:
    return {c for c in db.scalars(select(SessionRec.customer_id).where(SessionRec.org_id == p.org_id, SessionRec.site_host == p.site_host, SessionRec.customer_id.is_not(None))).all() if c}


def owns_host(p: Principal, host: str | None) -> bool:
    return not p.scoped or (host or "") == p.site_host


def visible_hosts(p: Principal, hosts: list[str]) -> list[str]:
    return [h for h in hosts if owns_host(p, h)]
