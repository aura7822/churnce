"""HTTP + WebSocket surface (spec §20). Business logic lives in the domain modules; this layer
authenticates, authorises, validates, commits, and serialises."""
from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import action_engine, chunk_pipeline, communications, database, demo, feedback, resolutions
from .audit import audit
from .collector import EventBatch, IngestResult, ingest_events
from .config import get_settings
from .database import SessionLocal, get_db, notify
from .enums import ACTION_CATEGORY, COLLECTIONS, STAGE_OF_STATE, ChunkState
from .intelligence import queue_analysis
from . import mailer
from .llm import service as llm_service
from .llm.service import provider_status
from .models import (
    Action, AuditLog, Chunk, Communication, Customer, Event, EvidenceRecord, Incident, MonitoringConfig,
    Organization, Outcome, Resolution, RetrievalRecord, SessionRec, User,
)
from .privacy import redact, scan
from .rag.retrieval import retrieve
from .rag.store import collection_counts, ingest_document
from .realtime import hub
from .retention import purge_org
from .scheduler import scheduler
from .security import (
    ROLES, Principal, client_ip, create_token, current_principal, generate_ingest_key, hash_ingest_key,
    hash_password, ingest_config, limiter, principal_from_token, require, verify_password,
)
from .utils import iso, utcnow

settings = get_settings()
router = APIRouter(prefix="/api/v1")


# ═════════════════════════════ serialisers ═════════════════════════════
def ser_chunk(c: Chunk) -> dict[str, Any]:
    now = utcnow()
    remaining = None
    if c.state == ChunkState.PENDING_REVIEW and c.review_mode == "auto" and c.review_deadline:
        remaining = max(0.0, round((c.review_deadline - now).total_seconds(), 2))
        if c.hold_until and c.hold_until > now:
            remaining = max(remaining, round((c.hold_until - now).total_seconds(), 2))
    return {
        "id": c.id, "session_id": c.session_id, "journey_stage": c.journey_stage, "signal": c.signal,
        "issue_signature": c.issue_signature, "summary": c.summary, "original_summary": c.original_summary,
        "events": c.events, "source_event_ids": c.source_event_ids, "observations": c.observations,
        "sensitivity_status": c.sensitivity_status, "state": c.state, "stage": STAGE_OF_STATE.get(c.state, c.state),
        "version": c.version, "review_mode": c.review_mode, "review_deadline": iso(c.review_deadline),
        "held": bool(c.hold_until and c.hold_until > now), "seconds_remaining": remaining,
        "validation_errors": c.validation_errors, "created_at": iso(c.created_at), "updated_at": iso(c.updated_at),
        "approved_by": c.approved_by, "edited_by": c.edited_by, "indexed_at": iso(c.indexed_at),
        "edited": c.summary != c.original_summary, "simulated": c.simulated,
    }


def ser_event(e: Event) -> dict[str, Any]:
    return {
        "id": e.id, "session_id": e.session_id, "event_type": e.event_type, "page_route": e.page_route,
        "journey_stage": e.journey_stage, "element_category": e.element_category, "outcome": e.outcome,
        "response_time_ms": e.response_time_ms, "event_timestamp": iso(e.event_timestamp),
        "received_at": iso(e.received_at), "redactions": e.redaction_count, "chunk_id": e.chunk_id if e.chunk_id != "-" else None,
        "processing_status": "no_episode" if e.chunk_id == "-" else ("chunked" if e.chunk_id else "pending"),
        "simulated": e.simulated,
    }


def ser_action(a: Action) -> dict[str, Any]:
    return {
        "id": a.id, "incident_id": a.incident_id, "resolution_id": a.resolution_id, "type": a.type,
        "category": a.category, "title": a.title, "rationale": a.rationale, "priority": a.priority,
        "score": a.score, "score_breakdown": a.score_breakdown, "payload": a.payload, "status": a.status,
        "policy_result": a.policy_result, "decided_by": a.decided_by, "decided_at": iso(a.decided_at),
        "executed_at": iso(a.executed_at), "execution_result": a.execution_result, "error": a.error,
        "created_at": iso(a.created_at),
    }


def ser_incident(i: Incident) -> dict[str, Any]:
    return {
        "id": i.id, "title": i.title, "issue_signature": i.issue_signature, "journey_stage": i.journey_stage,
        "signal": i.signal, "incident_type": i.incident_type, "status": i.status, "severity": i.severity,
        "severity_score": i.severity_score, "affected_sessions": i.affected_sessions, "chunk_ids": i.chunk_ids,
        "lifecycle_stage": i.lifecycle_stage, "observed_facts": i.observed_facts, "hypotheses": i.hypotheses,
        "evidence_ids": i.evidence_ids, "unresolved_questions": i.unresolved_questions,
        "recommended_action": i.recommended_action, "customer_message_eligible": i.customer_message_eligible,
        "analysis_provider": i.analysis_provider, "analysis_notes": i.analysis_notes,
        "last_retrieval_id": i.last_retrieval_id, "regression_count": i.regression_count,
        "resolution_id": i.resolution_id, "first_seen_at": iso(i.first_seen_at), "last_seen_at": iso(i.last_seen_at),
        "analyzed_at": iso(i.analyzed_at), "resolved_at": iso(i.resolved_at), "simulated": i.simulated,
    }


def ser_retrieval(r: RetrievalRecord) -> dict[str, Any]:
    return {
        "id": r.id, "incident_id": r.incident_id, "purpose": r.purpose, "query": r.query, "filters": r.filters,
        "candidates": r.candidates, "context": r.context, "embedding_provider": r.embedding_provider,
        "rerank_provider": r.rerank_provider, "latency_ms": r.latency_ms, "created_at": iso(r.created_at),
        "reasoning": (r.filters or {}).get("reasoning"),
    }


def ser_resolution(r: Resolution) -> dict[str, Any]:
    return {
        "resolution_id": r.id, "incident_id": r.incident_id, "issue_category": r.issue_category,
        "resolution_status": r.status, "verification_sources": r.sources, "approved_claims": r.approved_claims,
        "segment_available": r.segment_available, "email_eligible": r.email_eligible,
        "verification_notes": r.verification_notes, "verified_at": iso(r.verified_at), "created_by": r.created_by,
        "created_at": iso(r.created_at),
    }


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    user, _, host = email.partition("@")
    return f"{user[:1]}***@{host}"


def ser_comm(c: Communication, db: Session, p: Principal) -> dict[str, Any]:
    cust = db.get(Customer, c.customer_id)
    can_see = p.role in ("administrator", "marketing_operator")
    return {
        "id": c.id, "incident_id": c.incident_id, "resolution_id": c.resolution_id, "customer_id": c.customer_id,
        "customer_ref": cust.ref if cust else None,
        "recipient": (cust.email if can_see else mask_email(cust.email)) if cust else None,
        "subject": c.subject, "body": c.body, "claims_used": c.claims_used, "status": c.status,
        "policy_result": c.policy_result, "holdout": c.holdout, "generated_by": c.generated_by,
        "approved_by": c.approved_by, "approved_at": iso(c.approved_at), "sent_at": iso(c.sent_at),
        "created_at": iso(c.created_at), "delivery_mode": mailer.delivery_mode(),
    }


def ser_outcome(o: Outcome) -> dict[str, Any]:
    return {
        "id": o.id, "incident_id": o.incident_id, "resolution_id": o.resolution_id, "metric": o.metric,
        "baseline_value": o.baseline_value, "post_value": o.post_value, "n_baseline": o.n_baseline, "n_post": o.n_post,
        "method": o.method, "strength": o.strength, "details": o.details, "simulated": o.simulated,
        "created_at": iso(o.created_at),
    }


def ser_config(cfg: MonitoringConfig) -> dict[str, Any]:
    return {
        "site_name": cfg.site_name, "environment": cfg.environment, "authorized_domains": cfg.authorized_domains,
        "allowed_event_types": cfg.allowed_event_types, "ingest_key_prefix": cfg.ingest_key_prefix,
        "monitoring_enabled": cfg.monitoring_enabled, "review_policy": cfg.review_policy,
        "review_seconds": cfg.review_seconds, "retention_days": cfg.retention_days, "journey_map": cfg.journey_map,
        "holdout_pct": cfg.holdout_pct, "contact_frequency_days": cfg.contact_frequency_days,
        "brand_tone": cfg.brand_tone, "cta_url": cfg.cta_url, "updated_at": iso(cfg.updated_at),
    }


def _cfg(db: Session, org_id: str) -> MonitoringConfig:
    cfg = db.scalar(select(MonitoringConfig).where(MonitoringConfig.org_id == org_id))
    if not cfg:
        raise HTTPException(404, "Monitoring configuration not found")
    return cfg


def _own(db: Session, model, obj_id: str, p: Principal, label: str):
    obj = db.get(model, obj_id)
    if not obj or obj.org_id != p.org_id:  # same answer for "missing" and "someone else's": no tenant probing
        raise HTTPException(404, f"{label} not found")
    return obj


# ═════════════════════════════ auth ═════════════════════════════
class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    limiter.check(f"login:{client_ip(request)}", settings.login_rate_limit)
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if not user or not user.active or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    org = db.get(Organization, user.org_id)
    return {
        "token": create_token(user),
        "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role},
        "organization": {"id": org.id, "name": org.name},
        "environment": _cfg(db, user.org_id).environment,
    }


@router.get("/me")
def me(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    org = db.get(Organization, p.org_id)
    from .security import PERMISSIONS

    return {
        "user": {"id": p.id, "name": p.name, "email": p.email, "role": p.role},
        "organization": {"id": org.id, "name": org.name},
        "environment": _cfg(db, p.org_id).environment,
        "permissions": sorted(PERMISSIONS.get(p.role, set())),
    }


# ═════════════════════════════ events ═════════════════════════════
@router.post("/events", response_model=IngestResult)
def post_events(batch: EventBatch, cfg: MonitoringConfig = Depends(ingest_config), db: Session = Depends(get_db)):
    limiter.check(f"ingest:{cfg.id}", settings.ingest_rate_limit)
    result = ingest_events(db, cfg, batch)
    db.commit()
    return result


@router.get("/events")
def list_events(
    limit: int = Query(100, ge=1, le=500), session_id: str | None = None,
    p: Principal = Depends(require("read")), db: Session = Depends(get_db),
):
    q = select(Event).where(Event.org_id == p.org_id)
    if session_id:
        q = q.where(Event.session_id == session_id)
    rows = db.scalars(q.order_by(Event.received_at.desc(), Event.event_timestamp.desc()).limit(limit)).all()
    return {"events": [ser_event(e) for e in rows], "server_time": iso(utcnow())}


# ═════════════════════════════ chunks ═════════════════════════════
class ChunkCreate(BaseModel):
    session_id: str
    summary: str = Field(min_length=3, max_length=600)
    events: list[str] = Field(min_length=1, max_length=40)
    source_event_ids: list[str] = Field(min_length=1, max_length=100)
    journey_stage: str = Field(default="browse", max_length=40)


class ChunkEdit(BaseModel):
    version: int
    summary: str | None = Field(default=None, max_length=600)
    events: list[str] | None = None


class ChunkApprove(BaseModel):
    version: int | None = None


@router.get("/chunks")
def list_chunks(
    state: str | None = None, limit: int = Query(100, ge=1, le=300),
    p: Principal = Depends(require("read")), db: Session = Depends(get_db),
):
    q = select(Chunk).where(Chunk.org_id == p.org_id)
    if state:
        q = q.where(Chunk.state.in_(state.split(",")))
    rows = db.scalars(q.order_by(Chunk.created_at.desc()).limit(limit)).all()
    return {"chunks": [ser_chunk(c) for c in rows], "server_time": iso(utcnow())}


@router.get("/chunks/pending")
def pending_chunks(p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Chunk).where(Chunk.org_id == p.org_id, Chunk.state.in_([ChunkState.PENDING_REVIEW, ChunkState.REJECTED]))
        .order_by(Chunk.created_at.desc()).limit(100)
    ).all()
    return {"chunks": [ser_chunk(c) for c in rows], "server_time": iso(utcnow())}


@router.post("/chunks", status_code=201)
def create_chunk(body: ChunkCreate, p: Principal = Depends(require("chunks:review")), db: Session = Depends(get_db)):
    """Operator-authored evidence. Must cite real source events of the same tenant and session."""
    sess = db.get(SessionRec, body.session_id) or db.scalar(
        select(SessionRec).where(SessionRec.org_id == p.org_id, SessionRec.external_id == body.session_id)
    )
    if not sess or sess.org_id != p.org_id:
        raise HTTPException(404, "Session not found")
    found = set(db.scalars(select(Event.id).where(Event.org_id == p.org_id, Event.session_id == sess.id, Event.id.in_(body.source_event_ids))))
    if found != set(body.source_event_ids):
        raise HTTPException(422, "source_event_ids must all be events of this session")
    summary, s_found = redact(body.summary.strip())
    lines, redactions = [], sum(s_found.values())
    for line in body.events:
        text, f = redact(line.strip()[:300])
        redactions += sum(f.values())
        lines.append(text)
    cfg = _cfg(db, p.org_id)
    flagged = bool(scan(summary + " " + " ".join(lines)))
    chunk = Chunk(
        org_id=p.org_id, session_id=sess.id, journey_stage=body.journey_stage, summary=summary, original_summary=summary,
        events=lines, source_event_ids=body.source_event_ids, observations={"event_count": len(lines), "authored_by_operator": True},
        sensitivity_status="flagged" if flagged else ("filtered" if redactions else "clean"),
        state=ChunkState.PENDING_REVIEW, review_mode="manual", review_deadline=None, edited_by=p.actor, simulated=sess.simulated,
    )
    db.add(chunk)
    db.flush()
    audit(db, p.org_id, p.actor, "chunk_created_manual", "chunk", chunk.id, None, ChunkState.PENDING_REVIEW)
    notify(db, p.org_id, {"type": "chunk_created", "chunk_id": chunk.id, "session_id": sess.id})
    db.commit()
    return ser_chunk(chunk)


@router.patch("/chunks/{chunk_id}")
def edit_chunk(chunk_id: str, body: ChunkEdit, p: Principal = Depends(require("chunks:review")), db: Session = Depends(get_db)):
    chunk = chunk_pipeline.edit(db, p.org_id, chunk_id, p.actor, body.version, body.summary, body.events)
    db.commit()
    return ser_chunk(chunk)


@router.post("/chunks/{chunk_id}/hold")
def hold_chunk(chunk_id: str, p: Principal = Depends(require("chunks:review")), db: Session = Depends(get_db)):
    """Heartbeat while an operator is typing; pauses the backend countdown."""
    chunk = chunk_pipeline.hold(db, p.org_id, chunk_id)
    db.commit()
    return ser_chunk(chunk)


@router.post("/chunks/{chunk_id}/extend")
def extend_chunk(chunk_id: str, p: Principal = Depends(require("chunks:review")), db: Session = Depends(get_db)):
    """Add 30 seconds to the review countdown (capped); backend-owned, audited."""
    chunk = chunk_pipeline.extend(db, p.org_id, chunk_id, p.actor)
    db.commit()
    return ser_chunk(chunk)


@router.post("/chunks/{chunk_id}/approve")
def approve_chunk(chunk_id: str, body: ChunkApprove | None = None, p: Principal = Depends(require("chunks:review")), db: Session = Depends(get_db)):
    chunk = chunk_pipeline.approve(db, p.org_id, chunk_id, p.actor, body.version if body else None)
    db.commit()
    return ser_chunk(chunk)


@router.post("/chunks/{chunk_id}/discard")
def discard_chunk(chunk_id: str, p: Principal = Depends(require("chunks:review")), db: Session = Depends(get_db)):
    chunk = chunk_pipeline.discard(db, p.org_id, chunk_id, p.actor)
    db.commit()
    return ser_chunk(chunk)


@router.get("/chunks/{chunk_id}")
def get_chunk(chunk_id: str, p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    chunk = _own(db, Chunk, chunk_id, p, "Chunk")
    events = db.scalars(select(Event).where(Event.id.in_(chunk.source_event_ids or []))).all()
    return {**ser_chunk(chunk), "source_events": [ser_event(e) for e in sorted(events, key=lambda e: e.event_timestamp)]}


# ═════════════════════════════ RAG ═════════════════════════════
class RagSearch(BaseModel):
    query: str = Field(min_length=3, max_length=600)
    collections: list[str] | None = None


class DocIn(BaseModel):
    collection: Literal["product_knowledge", "engineering", "support", "business_policy"]
    source_ref: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=10, max_length=60_000)


@router.get("/rag/retrievals")
def list_retrievals(limit: int = Query(20, ge=1, le=100), p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    rows = db.scalars(select(RetrievalRecord).where(RetrievalRecord.org_id == p.org_id).order_by(RetrievalRecord.created_at.desc()).limit(limit)).all()
    return {"retrievals": [{"id": r.id, "incident_id": r.incident_id, "purpose": r.purpose, "query": r.query, "kept": sum(1 for c in r.candidates if c.get("kept")), "candidates": len(r.candidates), "latency_ms": r.latency_ms, "created_at": iso(r.created_at)} for r in rows]}


@router.get("/rag/retrievals/{retrieval_id}")
def get_retrieval(retrieval_id: str, p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    return ser_retrieval(_own(db, RetrievalRecord, retrieval_id, p, "Retrieval"))


@router.post("/rag/search")
def rag_search(body: RagSearch, p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    rec = retrieve(db, p.org_id, body.query, purpose="operator_query", collections=body.collections)
    # Retrieve, then reason: Gemma reads the retrieved passages and returns a structured, evidence-cited answer.
    reasoning = llm_service.reason_over_retrieval(body.query, rec)
    rec.filters = {**(rec.filters or {}), "reasoning": reasoning}
    db.commit()
    return ser_retrieval(rec)


@router.get("/rag/collections")
def rag_collections(p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    counts = collection_counts(db, p.org_id)
    return {"collections": [{"name": c, "passages": counts.get(c, 0)} for c in COLLECTIONS], "provider": provider_status()}


@router.post("/rag/documents", status_code=201)
def add_document(body: DocIn, p: Principal = Depends(require("knowledge:write")), db: Session = Depends(get_db)):
    n = ingest_document(db, p.org_id, body.collection, body.source_ref, body.title, body.body, source_type="operator")
    audit(db, p.org_id, p.actor, "knowledge_ingested", "document", body.source_ref, None, None, {"collection": body.collection, "passages": n})
    db.commit()
    return {"passages": n, "unchanged": n == 0}


# ═════════════════════════════ incidents ═════════════════════════════
@router.get("/incidents")
def list_incidents(status_: str | None = Query(None, alias="status"), p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    q = select(Incident).where(Incident.org_id == p.org_id)
    if status_:
        q = q.where(Incident.status.in_(status_.split(",")))
    rows = db.scalars(q.order_by(Incident.last_seen_at.desc()).limit(100)).all()
    return {"incidents": [ser_incident(i) for i in rows]}


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: str, p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    inc = _own(db, Incident, incident_id, p, "Incident")
    chunks = db.scalars(select(Chunk).where(Chunk.id.in_(inc.chunk_ids or []))).all() if inc.chunk_ids else []
    actions = db.scalars(select(Action).where(Action.incident_id == inc.id).order_by(Action.score.desc())).all()
    retrieval = db.get(RetrievalRecord, inc.last_retrieval_id) if inc.last_retrieval_id else None
    res = db.get(Resolution, inc.resolution_id) if inc.resolution_id else None
    outcomes = db.scalars(select(Outcome).where(Outcome.incident_id == inc.id).order_by(Outcome.created_at.desc())).all()
    return {
        **ser_incident(inc),
        "chunks": [{"id": c.id, "summary": c.summary, "session_id": c.session_id, "created_at": iso(c.created_at)} for c in chunks],
        "actions": [ser_action(a) for a in actions],
        "retrieval": ser_retrieval(retrieval) if retrieval else None,
        "resolution": ser_resolution(res) if res else None,
        "outcomes": [ser_outcome(o) for o in outcomes],
    }


@router.post("/incidents/{incident_id}/analyze", status_code=202)
def analyze_incident(incident_id: str, p: Principal = Depends(require("incidents:analyze")), db: Session = Depends(get_db)):
    inc = _own(db, Incident, incident_id, p, "Incident")
    if inc.status == "analyzing":
        raise HTTPException(409, "Analysis is already running")
    queue_analysis(db, inc, p.actor, "operator request")
    db.commit()
    return ser_incident(inc)


@router.post("/incidents/{incident_id}/evaluate")
def evaluate_incident(incident_id: str, p: Principal = Depends(require("outcomes:evaluate")), db: Session = Depends(get_db)):
    inc = _own(db, Incident, incident_id, p, "Incident")
    try:
        outs = feedback.evaluate_outcome(db, inc, p.actor)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return {"outcomes": [ser_outcome(o) for o in outs]}


@router.get("/outcomes")
def list_outcomes(p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    rows = db.scalars(select(Outcome).where(Outcome.org_id == p.org_id).order_by(Outcome.created_at.desc()).limit(100)).all()
    return {"outcomes": [ser_outcome(o) for o in rows]}


# ═════════════════════════════ recommendations & actions ═════════════════════════════
@router.get("/recommendations")
def recommendations(
    status_: str | None = Query(None, alias="status"), incident_id: str | None = None,
    p: Principal = Depends(require("read")), db: Session = Depends(get_db),
):
    q = select(Action).where(Action.org_id == p.org_id)
    if status_:
        q = q.where(Action.status.in_(status_.split(",")))
    if incident_id:
        q = q.where(Action.incident_id == incident_id)
    rows = db.scalars(q.order_by(Action.created_at.desc()).limit(200)).all()
    inc = {i.id: i for i in db.scalars(select(Incident).where(Incident.id.in_({a.incident_id for a in rows}))).all()} if rows else {}
    return {"recommendations": [{**ser_action(a), "incident_title": inc[a.incident_id].title if a.incident_id in inc else None} for a in rows]}


def _action_gate(db: Session, p: Principal, action_id: str) -> Action:
    act = _own(db, Action, action_id, p, "Action")
    if not p.can(f"actions:approve:{ACTION_CATEGORY.get(act.type, act.category)}"):
        raise HTTPException(403, f"Your role ({p.role}) cannot decide {act.category} actions")
    return act


@router.post("/actions/{action_id}/approve")
def approve_action(action_id: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    _action_gate(db, p, action_id)
    act = action_engine.approve(db, action_id, p.org_id, p.actor)
    db.commit()
    return ser_action(act)


@router.post("/actions/{action_id}/reject")
def reject_action(action_id: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    _action_gate(db, p, action_id)
    act = action_engine.decline(db, action_id, p.org_id, p.actor)
    db.commit()
    return ser_action(act)


# ═════════════════════════════ resolutions ═════════════════════════════
class SourceBody(BaseModel):
    source: resolutions.SourceIn
    approved_claims: list[str] | None = None
    segment_available: bool | None = None


@router.get("/resolutions")
def list_resolutions(p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    rows = db.scalars(select(Resolution).where(Resolution.org_id == p.org_id).order_by(Resolution.created_at.desc()).limit(100)).all()
    return {"resolutions": [ser_resolution(r) for r in rows]}


@router.post("/resolutions", status_code=201)
def post_resolution(body: resolutions.ResolutionIn, p: Principal = Depends(require("resolutions:write")), db: Session = Depends(get_db)):
    res = resolutions.create(db, p.org_id, p.actor, body)
    db.commit()
    return ser_resolution(res)


@router.post("/resolutions/{resolution_id}/sources")
def add_resolution_source(resolution_id: str, body: SourceBody, p: Principal = Depends(require("resolutions:write")), db: Session = Depends(get_db)):
    res = resolutions.add_source(db, p.org_id, p.actor, resolution_id, body.source, body.approved_claims, body.segment_available)
    db.commit()
    return ser_resolution(res)


# ═════════════════════════════ emails ═════════════════════════════
@router.get("/emails")
def list_emails(status_: str | None = Query(None, alias="status"), p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    q = select(Communication).where(Communication.org_id == p.org_id)
    if status_:
        q = q.where(Communication.status.in_(status_.split(",")))
    rows = db.scalars(q.order_by(Communication.created_at.desc()).limit(200)).all()
    return {"emails": [ser_comm(c, db, p) for c in rows]}


@router.post("/emails/{email_id}/approve")
def approve_email(email_id: str, p: Principal = Depends(require("emails:approve")), db: Session = Depends(get_db)):
    c = communications.approve(db, p.org_id, p.actor, email_id)
    db.commit()
    return ser_comm(c, db, p)


@router.post("/emails/{email_id}/reject")
def reject_email(email_id: str, p: Principal = Depends(require("emails:approve")), db: Session = Depends(get_db)):
    c = communications.reject(db, p.org_id, p.actor, email_id)
    db.commit()
    return ser_comm(c, db, p)


class EmailEdit(BaseModel):
    subject: str = Field(min_length=3, max_length=120)
    body: str = Field(min_length=20, max_length=1500)


@router.patch("/emails/{email_id}")
def edit_email(email_id: str, body: EmailEdit, p: Principal = Depends(require("emails:approve")), db: Session = Depends(get_db)):
    c = communications.update_draft(db, p.org_id, p.actor, email_id, body.subject, body.body)
    db.commit()
    return ser_comm(c, db, p)


@router.post("/emails/{email_id}/send")
def send_email(email_id: str, p: Principal = Depends(require("emails:approve")), db: Session = Depends(get_db)):
    """Delivers through SMTP when configured; otherwise records a simulated send and nothing leaves the system."""
    c = communications.deliver(db, p.org_id, p.actor, email_id)
    db.commit()
    return ser_comm(c, db, p)


# ═════════════════════════════ metrics, audit, status ═════════════════════════════
@router.get("/metrics")
def metrics(p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    m = feedback.dashboard_metrics(db, p.org_id)
    cfg = _cfg(db, p.org_id)
    return {
        **m,
        "environment": cfg.environment,
        "monitoring_enabled": cfg.monitoring_enabled,
        "health": {
            "scheduler": scheduler.status(),
            "realtime_subscribers": hub.subscriber_count,
            "providers": provider_status(),
            "knowledge": collection_counts(db, p.org_id),
        },
        "server_time": iso(utcnow()),
    }


@router.get("/logs")
def backend_logs(
    after: int = Query(0, ge=0), level: Literal["INFO", "WARNING", "ERROR"] = "INFO", limit: int = Query(300, ge=1, le=1000),
    p: Principal = Depends(require("logs:read")), db: Session = Depends(get_db),
):
    """Recent backend log lines (newest last) plus live health indicators, for the Backend logs page."""
    from . import logbuf

    db_state = database.ping()
    cfg = get_settings()
    recent = logbuf.handler.count_recent(300)
    return {
        "logs": logbuf.handler.since(after, level, limit),
        "buffered": len(logbuf.handler),
        "indicators": {
            "database": {**db_state, "engine": "sqlite" if cfg.is_sqlite else "postgresql", "host": cfg.db_host, "neon": cfg.is_neon, "pooled": cfg.uses_pooler, "tls": cfg.ssl_mode or None},
            "scheduler": scheduler.status(),
            "realtime_subscribers": hub.subscriber_count,
            "providers": provider_status(),
            "errors_5m": recent["errors"], "warnings_5m": recent["warnings"],
            "uptime_seconds": int(time.time() - logbuf.STARTED),
            "environment": cfg.app_env, "version": "1.0.0",
        },
        "server_time": iso(utcnow()),
    }


@router.get("/audit")
def audit_log(limit: int = Query(100, ge=1, le=500), p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).where(AuditLog.org_id == p.org_id).order_by(AuditLog.ts.desc()).limit(limit)).all()
    return {"audit": [{"id": a.id, "actor": a.actor, "action": a.action, "entity_type": a.entity_type, "entity_id": a.entity_id, "from_state": a.from_state, "to_state": a.to_state, "detail": a.detail, "ts": iso(a.ts)} for a in rows]}


# ═════════════════════════════ governance ═════════════════════════════
class ConfigPatch(BaseModel):
    site_name: str | None = Field(default=None, max_length=200)
    authorized_domains: list[str] | None = Field(default=None, max_length=50)
    allowed_event_types: list[str] | None = None
    monitoring_enabled: bool | None = None
    review_policy: Literal["auto_approve_filtered", "manual", "restricted"] | None = None
    review_seconds: int | None = Field(default=None, ge=3, le=120)
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    holdout_pct: int | None = Field(default=None, ge=0, le=50)
    contact_frequency_days: int | None = Field(default=None, ge=0, le=365)
    brand_tone: str | None = Field(default=None, max_length=300)
    cta_url: str | None = Field(default=None, max_length=500, pattern=r"^https?://")


@router.get("/config")
def get_config(p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    return ser_config(_cfg(db, p.org_id))


@router.patch("/config")
def patch_config(body: ConfigPatch, p: Principal = Depends(require("config:write")), db: Session = Depends(get_db)):
    cfg = _cfg(db, p.org_id)
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(cfg, k, v)
    cfg.updated_at = utcnow()
    audit(db, p.org_id, p.actor, "config_updated", "config", cfg.id, None, None, {"fields": sorted(changes)})
    notify(db, p.org_id, {"type": "config_updated"})
    db.commit()
    return ser_config(cfg)


@router.post("/config/rotate-key")
def rotate_key(p: Principal = Depends(require("config:write")), db: Session = Depends(get_db)):
    cfg = _cfg(db, p.org_id)
    key = generate_ingest_key()
    cfg.ingest_key_hash, cfg.ingest_key_prefix, cfg.updated_at = hash_ingest_key(key), key[:12], utcnow()
    audit(db, p.org_id, p.actor, "ingest_key_rotated", "config", cfg.id)
    db.commit()
    return {"ingest_key": key, "note": "Shown once. Update the browser extension; the previous key no longer works."}


@router.post("/governance/retention/run")
def run_retention(p: Principal = Depends(require("config:write")), db: Session = Depends(get_db)):
    result = purge_org(db, _cfg(db, p.org_id), p.actor)
    db.commit()
    return result


@router.get("/customers")
def list_customers(p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    rows = db.scalars(select(Customer).where(Customer.org_id == p.org_id).order_by(Customer.ref).limit(500)).all()
    full = p.role in ("administrator", "marketing_operator")
    return {"customers": [{"id": c.id, "ref": c.ref, "email": c.email if full else mask_email(c.email), "consent": c.consent, "suppressed": c.suppressed, "last_contacted_at": iso(c.last_contacted_at)} for c in rows]}


class CustomerPatch(BaseModel):
    consent: Literal["opt_in", "opt_out", "unknown"] | None = None
    suppressed: bool | None = None


@router.patch("/customers/{customer_id}")
def patch_customer(customer_id: str, body: CustomerPatch, p: Principal = Depends(require("emails:approve")), db: Session = Depends(get_db)):
    c = _own(db, Customer, customer_id, p, "Customer")
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(c, k, v)
    audit(db, p.org_id, p.actor, "customer_preferences_changed", "customer", c.id, None, None, {"fields": sorted(changes)})
    db.commit()
    return {"id": c.id, "ref": c.ref, "consent": c.consent, "suppressed": c.suppressed}


class UserIn(BaseModel):
    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str = Field(min_length=1, max_length=120)
    role: Literal["administrator", "product_analyst", "engineer", "marketing_operator", "reviewer"]
    password: str = Field(min_length=10, max_length=200)


class UserPatch(BaseModel):
    role: Literal["administrator", "product_analyst", "engineer", "marketing_operator", "reviewer"] | None = None
    active: bool | None = None


@router.get("/users")
def list_users(p: Principal = Depends(require("users:manage")), db: Session = Depends(get_db)):
    rows = db.scalars(select(User).where(User.org_id == p.org_id).order_by(User.created_at)).all()
    return {"users": [{"id": u.id, "name": u.name, "email": u.email, "role": u.role, "active": u.active} for u in rows], "roles": ROLES}


@router.post("/users", status_code=201)
def create_user(body: UserIn, p: Principal = Depends(require("users:manage")), db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "A user with that email already exists")
    u = User(org_id=p.org_id, email=email, name=body.name, role=body.role, password_hash=hash_password(body.password))
    db.add(u)
    db.flush()
    audit(db, p.org_id, p.actor, "user_created", "user", u.id, None, body.role)
    db.commit()
    return {"id": u.id, "email": u.email, "role": u.role}


@router.patch("/users/{user_id}")
def patch_user(user_id: str, body: UserPatch, p: Principal = Depends(require("users:manage")), db: Session = Depends(get_db)):
    u = _own(db, User, user_id, p, "User")
    if u.id == p.id and (body.active is False or (body.role and body.role != "administrator")):
        raise HTTPException(409, "You cannot remove your own administrator access")
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(u, k, v)
    audit(db, p.org_id, p.actor, "user_updated", "user", u.id, None, None, {"fields": sorted(changes)})
    db.commit()
    return {"id": u.id, "role": u.role, "active": u.active}


# ═════════════════════════════ demo ═════════════════════════════
class SimIn(BaseModel):
    scenario: Literal["checkout_failure", "checkout_success", "onboarding_stall", "search_dead_end"]
    sessions: int = Field(default=3, ge=1, le=12)


@router.get("/demo/scenarios")
def demo_scenarios(p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    return {"scenarios": [{"id": k, **v} for k, v in demo.SCENARIOS.items()], "enabled": _cfg(db, p.org_id).environment == "demo"}


@router.post("/demo/simulate")
def simulate(body: SimIn, p: Principal = Depends(require("demo:simulate")), db: Session = Depends(get_db)):
    cfg = _cfg(db, p.org_id)
    if cfg.environment != "demo":
        raise HTTPException(403, "Simulation is only available on a demo tenant")
    out = demo.simulate(db, cfg, body.scenario, body.sessions)
    audit(db, p.org_id, p.actor, "demo_simulation", "demo", body.scenario, None, None, {"sessions": body.sessions})
    db.commit()
    return out


# ═════════════════════════════ real-time stream ═════════════════════════════
@router.websocket("/stream")
async def stream(ws: WebSocket):
    """First client message must be {"type":"auth","token":"<jwt>"}; the token never appears in a URL."""
    await ws.accept()
    try:
        first = await asyncio.wait_for(ws.receive_json(), timeout=8)
        if first.get("type") != "auth" or not first.get("token"):
            raise ValueError("auth required")
        db = SessionLocal()
        try:
            principal = principal_from_token(db, first["token"])
        finally:
            db.close()
    except (Exception,):  # noqa: BLE001 - any failure here means unauthenticated
        await ws.close(code=4401)
        return

    queue = hub.subscribe(principal.org_id)
    await ws.send_json({"type": "hello", "server_time": iso(utcnow()), "role": principal.role})
    reader = asyncio.create_task(ws.receive_text())
    writer = asyncio.create_task(queue.get())
    try:
        while True:
            done, _ = await asyncio.wait({reader, writer}, timeout=25, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                await ws.send_json({"type": "ping", "server_time": iso(utcnow())})
                continue
            if writer in done:
                await ws.send_json(writer.result())
                writer = asyncio.create_task(queue.get())
            if reader in done:
                reader.result()  # raises WebSocketDisconnect when the client leaves
                reader = asyncio.create_task(ws.receive_text())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        reader.cancel()
        writer.cancel()
        hub.unsubscribe(principal.org_id, queue)
