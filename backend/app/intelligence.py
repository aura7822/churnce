"""Incident detection, retrieval-grounded analysis and recommendation hand-off."""

from __future__ import annotations

import logging
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import audit
from .config import get_settings
from .database import notify
from .enums import STAGE_BUSINESS_WEIGHT, ChunkState
from .lifecycle import classify_incident
from .llm.service import analyze_incident
from .models import Chunk, Incident, Resolution, SessionRec
from .rag.retrieval import retrieve
from .utils import utcnow

log = logging.getLogger("churnce.intelligence")
settings = get_settings()

OPEN_STATUSES = ("open", "analysis_queued", "analyzing", "analyzed", "action_pending", "regression")
REANALYZE_AFTER_NEW_CHUNKS = 3


def severity_of(chunks: list[Chunk], sessions: int, stage: str) -> tuple[float, str]:
    failures = sum(int((c.observations or {}).get("failure_count", 0)) for c in chunks)
    abandoned = sum(1 for c in chunks if (c.observations or {}).get("workflow_abandoned"))
    weight = STAGE_BUSINESS_WEIGHT.get(stage, 0.5)
    raw = (min(failures, 20) / 20) * 0.35 + (min(sessions, 10) / 10) * 0.35 + (min(abandoned, 5) / 5) * 0.15 + weight * 0.15
    score = round(raw, 3)
    label = "critical" if score >= 0.7 else "high" if score >= 0.45 else "medium" if score >= 0.25 else "low"
    return score, label


def _chunks_of(db: Session, inc: Incident) -> list[Chunk]:
    if not inc.chunk_ids:
        return []
    return list(db.scalars(select(Chunk).where(Chunk.id.in_(inc.chunk_ids))))


def _refresh_metrics(db: Session, inc: Incident) -> None:
    chunks = _chunks_of(db, inc)
    sessions = {c.session_id for c in chunks}
    inc.affected_sessions = len(sessions)
    inc.severity_score, inc.severity = severity_of(chunks, len(sessions), inc.journey_stage)
    inc.simulated = all(c.simulated for c in chunks) if chunks else False
    inc.last_seen_at = utcnow()


def attach_chunk(db: Session, chunk: Chunk) -> Incident | None:
    """Called when a chunk becomes retrievable: grow an open incident or open a new one."""
    sig = chunk.issue_signature
    if not sig or chunk.state != ChunkState.AVAILABLE:
        return None
    open_inc = db.scalar(
        select(Incident).where(
            Incident.org_id == chunk.org_id,
            Incident.issue_signature == sig,
            Incident.status.in_(OPEN_STATUSES),
        )
    )
    if open_inc:
        if chunk.id in open_inc.chunk_ids:
            return open_inc
        open_inc.chunk_ids = [*open_inc.chunk_ids, chunk.id]
        _refresh_metrics(db, open_inc)
        notify(db, open_inc.org_id, {"type": "incident_updated", "incident_id": open_inc.id})
        new_since = len(open_inc.chunk_ids) - open_inc.chunks_at_analysis
        if open_inc.status == "analyzed" and new_since >= REANALYZE_AFTER_NEW_CHUNKS:
            queue_analysis(db, open_inc, "system", "new evidence accumulated")
        return open_inc

    # Recurrence after a verified fix is a regression, not a new mystery.
    resolved = db.scalar(
        select(Incident)
        .where(Incident.org_id == chunk.org_id, Incident.issue_signature == sig, Incident.status == "resolved")
        .order_by(Incident.resolved_at.desc())
    )
    if resolved and resolved.resolved_at and chunk.created_at > resolved.resolved_at:
        resolved.status = "regression"
        resolved.regression_count += 1
        resolved.chunk_ids = [*resolved.chunk_ids, chunk.id]
        _refresh_metrics(db, resolved)
        audit(db, resolved.org_id, "system", "incident_regression", "incident", resolved.id, "resolved", "regression")
        notify(db, resolved.org_id, {"type": "incident_updated", "incident_id": resolved.id, "regression": True})
        return resolved

    matching = list(
        db.scalars(
            select(Chunk).where(
                Chunk.org_id == chunk.org_id, Chunk.issue_signature == sig, Chunk.state == ChunkState.AVAILABLE
            )
        )
    )
    # Chunks already attached to a closed incident must not seed a duplicate.
    closed_ids = {
        cid
        for inc in db.scalars(select(Incident).where(Incident.org_id == chunk.org_id, Incident.issue_signature == sig, Incident.status == "resolved"))
        for cid in inc.chunk_ids
    }
    matching = [c for c in matching if c.id not in closed_ids]
    sessions = {c.session_id for c in matching}
    high_friction = any(int((c.observations or {}).get("failure_count", 0)) >= settings.incident_high_friction for c in matching)
    if len(sessions) < settings.incident_min_sessions and not high_friction:
        return None

    stage, _, signal = sig.partition(":")
    inc = Incident(
        org_id=chunk.org_id,
        title=f"{stage.replace('_', ' ').capitalize()}: {chunk.summary}",
        issue_signature=sig,
        journey_stage=stage,
        signal=signal,
        status="open",
        chunk_ids=[c.id for c in matching],
        first_seen_at=min(c.created_at for c in matching),
    )
    db.add(inc)
    db.flush()
    _refresh_metrics(db, inc)
    audit(db, inc.org_id, "system", "incident_opened", "incident", inc.id, None, "open", {"signature": sig})
    notify(db, inc.org_id, {"type": "incident_updated", "incident_id": inc.id, "created": True})
    queue_analysis(db, inc, "system", "incident opened")
    return inc


def queue_analysis(db: Session, inc: Incident, actor: str, reason: str) -> None:
    if inc.status in ("analysis_queued", "analyzing"):
        return
    prev = inc.status
    inc.status = "analysis_queued"
    audit(db, inc.org_id, actor, "analysis_requested", "incident", inc.id, prev, "analysis_queued", {"reason": reason})
    notify(db, inc.org_id, {"type": "incident_updated", "incident_id": inc.id})


def _facts(db: Session, inc: Incident, chunks: list[Chunk]) -> tuple[list[str], dict]:
    obs = [c.observations or {} for c in chunks]
    failures = sum(int(o.get("failure_count", 0)) for o in obs)
    attempts = sum(int(o.get("attempt_count", 0)) for o in obs)
    abandoned = sum(1 for o in obs if o.get("workflow_abandoned"))
    completed = sum(1 for o in obs if o.get("workflow_completed"))
    rts = [o["observed_response_time_ms"] for o in obs if o.get("observed_response_time_ms")]
    endpoints = Counter(o["endpoint"] for o in obs if o.get("endpoint"))
    facts = [
        f"{inc.affected_sessions} session(s) produced {len(chunks)} approved chunk(s) with signature {inc.issue_signature}",
        f"{failures} friction event(s) across {attempts} recorded attempt(s)",
    ]
    if rts:
        facts.append(f"Slowest observed response: {max(rts)} ms")
    if abandoned:
        facts.append(f"{abandoned} chunk(s) ended with the workflow abandoned")
    if completed:
        facts.append(f"{completed} chunk(s) ended with the workflow completed after friction")
    stats = {"endpoint": endpoints.most_common(1)[0][0] if endpoints else None}
    return facts, stats


def retrieval_query(inc: Incident, endpoint: str | None) -> str:
    target = f" on {endpoint}" if endpoint else ""
    return (
        f"Find previous {inc.journey_stage} {inc.signal.replace('_', ' ')} failures{target}, related error logs, "
        f"known issues, relevant product documentation, support complaints and verified interventions "
        f"associated with {inc.journey_stage} journeys that stall or are abandoned."
    )


def run_analysis(db: Session, incident_id: str) -> Incident | None:
    """Claim, retrieve, reason, validate, then hand the result to the action engine."""
    from .action_engine import propose_actions

    claimed = db.execute(
        Incident.__table__.update()
        .where(Incident.id == incident_id, Incident.status == "analysis_queued")
        .values(status="analyzing")
    )
    if claimed.rowcount != 1:
        return None
    inc = db.get(Incident, incident_id)
    db.refresh(inc)
    notify(db, inc.org_id, {"type": "incident_updated", "incident_id": inc.id})

    chunks = _chunks_of(db, inc)
    _refresh_metrics(db, inc)
    facts, stats = _facts(db, inc, chunks)
    focus = " ".join(filter(None, [inc.journey_stage, inc.signal.replace("_", " "), stats["endpoint"]]))
    retrieval = retrieve(db, inc.org_id, retrieval_query(inc, stats["endpoint"]), incident_id=inc.id, focus=focus)
    kept = [c for c in retrieval.candidates if c["kept"]]
    ctx = {
        "incident": {
            "id": inc.id,
            "issue_signature": inc.issue_signature,
            "journey_stage": inc.journey_stage,
            "signal": inc.signal,
            "affected_sessions": inc.affected_sessions,
            "severity": inc.severity,
            "endpoint": stats["endpoint"],
        },
        "facts": facts,
        "evidence": [
            {"source_ref": c["source_ref"], "collection": c["collection"], "title": c["title"], "content": c["snippet"], "rerank_score": c["rerank_score"]}
            for c in kept
        ],
        "context": retrieval.context,
    }
    outcome = analyze_incident(ctx)
    a = outcome.analysis

    stage, stage_conf = classify_incident(db, list({c.session_id for c in chunks}))
    notes = list(outcome.notes)
    if stage != "unknown":
        if a.lifecycle_stage not in ("unknown", stage):
            notes.append(f"Model suggested lifecycle stage '{a.lifecycle_stage}'; classifier evidence says '{stage}'")
        a.lifecycle_stage = stage
    else:
        a.lifecycle_stage = "unknown"
        notes.append("Lifecycle stage left as unknown: not enough customer history")

    inc.incident_type = a.incident_type
    inc.lifecycle_stage = a.lifecycle_stage
    inc.observed_facts = a.observed_facts
    inc.hypotheses = [h.model_dump() for h in a.hypotheses]
    inc.evidence_ids = a.evidence_ids
    inc.unresolved_questions = a.unresolved_questions
    inc.recommended_action = a.recommended_action.model_dump()
    inc.customer_message_eligible = False
    inc.analysis_provider = outcome.provider
    inc.analysis_notes = notes
    inc.last_retrieval_id = retrieval.id
    inc.chunks_at_analysis = len(inc.chunk_ids)
    inc.analyzed_at = utcnow()
    inc.status = "analyzed"
    audit(db, inc.org_id, "system", "analysis_completed", "incident", inc.id, "analyzing", "analyzed", {"provider": outcome.provider, "retrieval": retrieval.id})
    notify(db, inc.org_id, {"type": "retrieval_completed", "retrieval_id": retrieval.id, "incident_id": inc.id})

    propose_actions(db, inc, a)
    notify(db, inc.org_id, {"type": "incident_updated", "incident_id": inc.id})
    return inc


def sweep_analysis(db: Session, limit: int = 5) -> int:
    ids = list(db.scalars(select(Incident.id).where(Incident.status == "analysis_queued").order_by(Incident.first_seen_at).limit(limit)))
    n = 0
    for iid in ids:
        try:
            if run_analysis(db, iid):
                n += 1
            db.commit()
        except Exception:
            db.rollback()
            log.exception("analysis crashed for %s", iid)
            inc = db.get(Incident, iid)
            if inc and inc.status == "analyzing":
                inc.status = "open"
                inc.analysis_notes = [*inc.analysis_notes, "Analysis crashed; see server logs. Re-run when ready."]
                db.commit()
    return n


def active_resolution(db: Session, inc: Incident) -> Resolution | None:
    return db.get(Resolution, inc.resolution_id) if inc.resolution_id else None
