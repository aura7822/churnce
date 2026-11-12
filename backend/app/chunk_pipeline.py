"""Chunk lifecycle: review gate, validation, embedding and indexing.

Every transition is a conditional UPDATE (claim), so concurrent workers or retried requests
can never double-process a chunk. The database *is* the durable work queue.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Iterable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .audit import audit
from .config import get_settings
from .database import notify
from .enums import STAGE_OF_STATE, ChunkState
from .models import Chunk, MonitoringConfig
from .privacy import redact, scan
from .rag.embeddings import get_embedder
from .rag.store import upsert_chunk_evidence
from .utils import iso, utcnow

log = logging.getLogger("churnce.pipeline")
settings = get_settings()

HOLD_SECONDS = 15
EXTEND_SECONDS = 30
MAX_DEADLINE_AHEAD_SECONDS = 600  # a countdown can never be pushed more than 10 minutes into the future
MAX_INGEST_ATTEMPTS = 3
MAX_SUMMARY_CHARS = 600


class PipelineError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


def claim(db: Session, chunk_id: str, from_states: Iterable[str], to_state: str, actor: str = "system", **extra) -> Chunk | None:
    """Atomically move a chunk between states. Returns the refreshed chunk, or None if lost the race."""
    now = utcnow()
    prev = db.scalar(select(Chunk.state).where(Chunk.id == chunk_id))
    res = db.execute(
        update(Chunk)
        .where(Chunk.id == chunk_id, Chunk.state.in_(list(from_states)))
        .values(state=to_state, updated_at=now, **extra)
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        return None
    chunk = db.get(Chunk, chunk_id)
    db.refresh(chunk)
    audit(db, chunk.org_id, actor, "chunk_state", "chunk", chunk.id, prev, to_state)
    notify(
        db,
        chunk.org_id,
        {
            "type": "pipeline_stage_changed",
            "chunk_id": chunk.id,
            "previous_stage": STAGE_OF_STATE.get(prev or "", "created"),
            "current_stage": STAGE_OF_STATE[to_state],
            "state": to_state,
            "version": chunk.version,
            "timestamp": iso(now),
        },
    )
    return chunk


def _get(db: Session, chunk_id: str, org_id: str) -> Chunk:
    chunk = db.get(Chunk, chunk_id)
    if not chunk or chunk.org_id != org_id:
        raise PipelineError("Chunk not found", 404)
    return chunk


# ── Operator actions ───────────────────────────────────────────────────────────
def hold(db: Session, org_id: str, chunk_id: str) -> Chunk:
    """Heartbeat from the dashboard while an operator is editing: pauses the countdown."""
    chunk = _get(db, chunk_id, org_id)
    if chunk.state != ChunkState.PENDING_REVIEW:
        raise PipelineError(f"Chunk is {chunk.state}; nothing to hold")
    chunk.hold_until = utcnow() + timedelta(seconds=HOLD_SECONDS)
    return chunk


def extend(db: Session, org_id: str, chunk_id: str, actor: str, seconds: int = EXTEND_SECONDS) -> Chunk:
    """Push the backend countdown out by `seconds`. The deadline stays a database column, so the
    extension is honoured even if every dashboard is closed. Manual-review chunks have no timer."""
    chunk = _get(db, chunk_id, org_id)
    if chunk.state != ChunkState.PENDING_REVIEW:
        raise PipelineError(f"Chunk is {chunk.state}; only chunks pending review can be extended")
    if chunk.review_mode == "manual" or chunk.review_deadline is None:
        raise PipelineError("This chunk is in manual review and has no countdown to extend")
    now = utcnow()
    base = max(chunk.review_deadline, now)  # extending an already-lapsed deadline restarts from now
    new_deadline = min(base + timedelta(seconds=seconds), now + timedelta(seconds=MAX_DEADLINE_AHEAD_SECONDS))
    res = db.execute(
        update(Chunk)
        .where(Chunk.id == chunk.id, Chunk.state == ChunkState.PENDING_REVIEW)
        .values(review_deadline=new_deadline, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:  # the timer or another operator moved the chunk first
        raise PipelineError("Chunk changed state before the extension applied")
    db.refresh(chunk)
    audit(db, org_id, actor, "chunk_extended", "chunk", chunk.id, chunk.state, chunk.state, {"seconds": seconds, "deadline": iso(new_deadline)})
    notify(
        db,
        org_id,
        {
            "type": "pipeline_stage_changed",
            "chunk_id": chunk.id,
            "previous_stage": "review",
            "current_stage": "review",
            "state": chunk.state,
            "version": chunk.version,
            "timestamp": iso(now),
        },
    )
    return chunk


def edit(db: Session, org_id: str, chunk_id: str, actor: str, version: int, summary: str | None, events: list[str] | None) -> Chunk:
    chunk = _get(db, chunk_id, org_id)
    if chunk.version != version:
        raise PipelineError(f"Stale edit: chunk is at version {chunk.version}, request was for {version}")
    if chunk.state not in (ChunkState.PENDING_REVIEW, ChunkState.REJECTED):
        raise PipelineError(f"Chunk is {chunk.state} and can no longer be edited")
    prev = chunk.state

    new_summary, s_found = redact((summary if summary is not None else chunk.summary).strip()[:MAX_SUMMARY_CHARS])
    if not new_summary:
        raise PipelineError("Summary cannot be empty", 422)
    new_events = list(chunk.events)
    e_found: dict[str, int] = {}
    if events is not None:
        new_events = []
        for line in events[:40]:
            clean, found = redact(line.strip()[:240])
            for k, v in found.items():
                e_found[k] = e_found.get(k, 0) + v
            if clean:
                new_events.append(clean)
    changed = new_summary != chunk.summary or new_events != chunk.events
    if not changed:
        return chunk

    # Compare-and-swap on version: a concurrent edit or auto-approval wins, we fail cleanly.
    res = db.execute(
        update(Chunk)
        .where(Chunk.id == chunk.id, Chunk.version == version, Chunk.state.in_([ChunkState.PENDING_REVIEW, ChunkState.REJECTED]))
        .values(
            summary=new_summary,
            events=new_events,
            version=version + 1,
            state=ChunkState.PENDING_REVIEW,
            sensitivity_status="filtered" if (s_found or e_found or chunk.sensitivity_status != "clean") else "clean",
            validation_errors=[],
            edited_by=actor,
            hold_until=utcnow() + timedelta(seconds=HOLD_SECONDS),
            review_deadline=None
            if chunk.review_mode == "manual"
            else utcnow() + timedelta(seconds=_review_seconds(db, org_id)),
            updated_at=utcnow(),
        )
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        raise PipelineError("Chunk changed while you were editing; reload and retry")
    db.refresh(chunk)
    audit(db, org_id, actor, "chunk_edited", "chunk", chunk.id, prev, ChunkState.PENDING_REVIEW, {"version": chunk.version})
    notify(
        db,
        org_id,
        {
            "type": "pipeline_stage_changed",
            "chunk_id": chunk.id,
            "previous_stage": STAGE_OF_STATE[prev],
            "current_stage": "review",
            "state": ChunkState.PENDING_REVIEW,
            "version": chunk.version,
            "timestamp": iso(utcnow()),
        },
    )
    return chunk


def _review_seconds(db: Session, org_id: str) -> int:
    cfg = db.scalar(select(MonitoringConfig).where(MonitoringConfig.org_id == org_id))
    return (cfg.review_seconds if cfg else None) or settings.review_seconds


def approve(db: Session, org_id: str, chunk_id: str, actor: str, version: int | None = None) -> Chunk:
    chunk = _get(db, chunk_id, org_id)
    if version is not None and chunk.version != version:
        raise PipelineError(f"Stale approval: chunk is at version {chunk.version}")
    got = claim(
        db,
        chunk_id,
        [ChunkState.PENDING_REVIEW, ChunkState.REJECTED],
        ChunkState.APPROVED,
        actor,
        approved_at=utcnow(),
        approved_by=actor,
        hold_until=None,
    )
    if got is None:
        raise PipelineError(f"Chunk is {chunk.state} and cannot be approved")
    validate(db, got)
    return got


def discard(db: Session, org_id: str, chunk_id: str, actor: str) -> Chunk:
    chunk = _get(db, chunk_id, org_id)
    got = claim(db, chunk_id, [ChunkState.PENDING_REVIEW, ChunkState.REJECTED], ChunkState.DISCARDED, actor)
    if got is None:
        raise PipelineError(f"Chunk is {chunk.state} and cannot be discarded")
    return got


# ── Validation ─────────────────────────────────────────────────────────────────
def validate(db: Session, chunk: Chunk) -> Chunk:
    """Schema, privacy and access checks. Failing chunks never reach the vector index."""
    got = claim(db, chunk.id, [ChunkState.APPROVED], ChunkState.VALIDATING)
    if got is None:
        return chunk
    errors: list[str] = []
    if not got.summary.strip():
        errors.append("schema: summary is empty")
    if not isinstance(got.events, list) or not got.events or not all(isinstance(x, str) for x in got.events):
        errors.append("schema: events must be a non-empty list of strings")
    if not got.source_event_ids:
        errors.append("provenance: chunk has no source events")
    found = scan(got.summary + "\n" + "\n".join(got.events))
    if found:
        errors.append("privacy: sensitive content detected (" + ", ".join(sorted(found)) + ")")
    if errors:
        got = claim(db, got.id, [ChunkState.VALIDATING], ChunkState.REJECTED, "validator", validation_errors=errors, sensitivity_status="flagged" if found else got.sensitivity_status)
        return got
    return claim(db, got.id, [ChunkState.VALIDATING], ChunkState.QUEUED, "validator", validation_errors=[]) or got


# ── Indexing ───────────────────────────────────────────────────────────────────
def chunk_text(chunk: Chunk) -> str:
    obs = chunk.observations or {}
    facts = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in obs.items() if v not in (None, "", False) or k.startswith("workflow"))
    return f"{chunk.summary}\nJourney stage: {chunk.journey_stage}. Signal: {chunk.signal or 'none'}.\n" + "\n".join(
        f"- {line}" for line in chunk.events
    ) + f"\nObservations: {facts}"


def index_chunk(db: Session, chunk_id: str) -> Chunk | None:
    got = claim(db, chunk_id, [ChunkState.QUEUED], ChunkState.EMBEDDING)
    if got is None:
        return None
    embedder = get_embedder()
    try:
        text = chunk_text(got)
        if scan(text):  # defence in depth: never embed something the scanner would flag
            raise ValueError("privacy scan failed at indexing time")
        vec = embedder.embed_passages([text])[0]
        upsert_chunk_evidence(db, got, text, vec, embedder.name)
    except Exception as exc:
        attempts = got.ingest_attempts + 1
        log.warning("indexing %s failed (attempt %s): %s", got.id, attempts, exc)
        if attempts >= MAX_INGEST_ATTEMPTS:
            return claim(
                db, got.id, [ChunkState.EMBEDDING], ChunkState.REJECTED, "indexer",
                ingest_attempts=attempts, validation_errors=[f"indexing: {str(exc)[:200]}"],
            )
        return claim(
            db, got.id, [ChunkState.EMBEDDING], ChunkState.QUEUED, "indexer",
            ingest_attempts=attempts, next_attempt_at=utcnow() + timedelta(seconds=2**attempts),
        )
    got = claim(db, got.id, [ChunkState.EMBEDDING], ChunkState.INDEXED, "indexer", indexed_at=utcnow())
    got = claim(db, got.id, [ChunkState.INDEXED], ChunkState.AVAILABLE, "indexer") or got
    from .intelligence import attach_chunk

    attach_chunk(db, got)
    return got


# ── Scheduler sweeps ───────────────────────────────────────────────────────────
def sweep_review_gate(db: Session) -> int:
    """Auto-approve privacy-filtered chunks whose backend countdown has elapsed.

    The timer lives here, not in the browser: closing the dashboard never stalls the pipeline.
    Flagged chunks and manual-review chunks are never approved by the clock.
    """
    now = utcnow()
    rows = db.scalars(
        select(Chunk)
        .where(
            Chunk.state == ChunkState.PENDING_REVIEW,
            Chunk.review_mode == "auto",
            Chunk.review_deadline.is_not(None),
            Chunk.review_deadline <= now,
            Chunk.sensitivity_status != "flagged",
        )
        .limit(100)
    ).all()
    n = 0
    for c in rows:
        if c.hold_until and c.hold_until > now:
            continue  # operator is mid-edit
        try:
            got = claim(
                db, c.id, [ChunkState.PENDING_REVIEW], ChunkState.APPROVED, "auto-policy",
                approved_at=now, approved_by="auto-policy",
            )
            if got:
                validate(db, got)
                n += 1
        except Exception:  # one bad chunk must not stall the sweep
            log.exception("auto-approval failed for %s", c.id)
    return n


def sweep_indexing(db: Session, limit: int = 20) -> int:
    now = utcnow()
    ids = list(
        db.scalars(
            select(Chunk.id)
            .where(Chunk.state == ChunkState.QUEUED, (Chunk.next_attempt_at.is_(None)) | (Chunk.next_attempt_at <= now))
            .order_by(Chunk.updated_at)
            .limit(limit)
        )
    )
    n = 0
    for cid in ids:
        try:
            if index_chunk(db, cid):
                n += 1
            db.commit()
        except Exception:
            db.rollback()
            log.exception("indexing crashed for %s", cid)
    return n
