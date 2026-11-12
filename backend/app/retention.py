"""Retention and deletion. Removing source data also removes everything derived from it:
chunks, their embeddings (evidence records) and orphaned sessions. Audit logs are kept; they hold
state transitions and actor identities, never raw customer content."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .audit import audit
from .models import Chunk, Event, EvidenceRecord, MonitoringConfig, SessionRec
from .utils import utcnow

log = logging.getLogger("churnce.retention")


def purge_org(db: Session, cfg: MonitoringConfig, actor: str = "retention-policy") -> dict[str, int]:
    cutoff = utcnow() - timedelta(days=max(1, cfg.retention_days))
    old_chunks = list(db.scalars(select(Chunk.id).where(Chunk.org_id == cfg.org_id, Chunk.created_at < cutoff)))
    ev_removed = 0
    if old_chunks:
        ev_removed = db.execute(delete(EvidenceRecord).where(EvidenceRecord.org_id == cfg.org_id, EvidenceRecord.chunk_id.in_(old_chunks))).rowcount or 0
        db.execute(delete(Chunk).where(Chunk.id.in_(old_chunks)))
    events_removed = db.execute(delete(Event).where(Event.org_id == cfg.org_id, Event.event_timestamp < cutoff)).rowcount or 0
    live = select(Event.session_id).where(Event.org_id == cfg.org_id).distinct()
    sessions_removed = db.execute(
        delete(SessionRec).where(SessionRec.org_id == cfg.org_id, SessionRec.last_seen < cutoff, SessionRec.id.not_in(live))
    ).rowcount or 0
    result = {"events": events_removed, "chunks": len(old_chunks), "embeddings": ev_removed, "sessions": sessions_removed}
    if any(result.values()):
        audit(db, cfg.org_id, actor, "retention_purge", "organization", cfg.org_id, None, None, {**result, "retention_days": cfg.retention_days})
    return result


def purge_all(db: Session) -> None:
    for cfg in db.scalars(select(MonitoringConfig)).all():
        purge_org(db, cfg)
