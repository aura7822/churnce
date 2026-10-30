from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from .config import get_settings
from .database import Base
from .enums import ChunkState
from .utils import new_id, utcnow

try:  # pgvector is optional when running on SQLite
    from pgvector.sqlalchemy import Vector
except Exception:  # pragma: no cover
    Vector = None  # type: ignore[assignment]

settings = get_settings()


class UTCDateTime(TypeDecorator):
    """Always timezone-aware UTC in Python; naive UTC on SQLite."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        return value if dialect.name == "postgresql" else value.replace(tzinfo=None)

    def process_result_value(self, value, dialect):  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class EmbeddingType(TypeDecorator):
    """pgvector `vector(n)` on PostgreSQL, JSON array elsewhere."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):  # noqa: ANN001
        if dialect.name == "postgresql" and Vector is not None:
            return dialect.type_descriptor(Vector(settings.embedding_dim))
        return dialect.type_descriptor(JSON())

    def process_result_value(self, value, dialect):  # noqa: ANN001
        if value is None:
            return None
        return [float(x) for x in value]


def _id(prefix: str):
    return mapped_column(String(40), primary_key=True, default=lambda: new_id(prefix))


def _ts(**kw: Any):
    return mapped_column(UTCDateTime, default=utcnow, **kw)


# ── Tenancy and access ─────────────────────────────────────────────────────────
class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = _id("org")
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _ts()


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = _id("usr")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(40))
    password_hash: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _ts()


class MonitoringConfig(Base):
    __tablename__ = "monitoring_configs"
    id: Mapped[str] = _id("mon")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), unique=True)
    site_name: Mapped[str] = mapped_column(String(200), default="Primary site")
    environment: Mapped[str] = mapped_column(String(20), default="production")  # demo | production
    authorized_domains: Mapped[list] = mapped_column(JSON, default=list)
    allowed_event_types: Mapped[list] = mapped_column(JSON, default=list)
    ingest_key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    ingest_key_prefix: Mapped[str] = mapped_column(String(12), default="")
    monitoring_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    review_policy: Mapped[str] = mapped_column(String(30), default="auto_approve_filtered")
    review_seconds: Mapped[int] = mapped_column(Integer, default=30)
    retention_days: Mapped[int] = mapped_column(Integer, default=30)
    journey_map: Mapped[dict] = mapped_column(JSON, default=dict)
    holdout_pct: Mapped[int] = mapped_column(Integer, default=0)
    contact_frequency_days: Mapped[int] = mapped_column(Integer, default=7)
    brand_tone: Mapped[str] = mapped_column(String(300), default="Warm, concise, benefit-focused")
    cta_url: Mapped[str] = mapped_column(String(500), default="https://example.com/shop")
    updated_at: Mapped[datetime] = _ts()


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("org_id", "ref"),)
    id: Mapped[str] = _id("cus")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    ref: Mapped[str] = mapped_column(String(80))  # pseudonymous reference used by the extension
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    consent: Mapped[str] = mapped_column(String(20), default="unknown")  # opt_in | opt_out | unknown
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_contacted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = _ts()


# ── Observation ────────────────────────────────────────────────────────────────
class SessionRec(Base):
    __tablename__ = "sessions"
    __table_args__ = (UniqueConstraint("org_id", "external_id"),)
    id: Mapped[str] = _id("ses")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(80))
    customer_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    site_host: Mapped[str | None] = mapped_column(String(200), nullable=True)
    first_seen: Mapped[datetime] = _ts()
    last_seen: Mapped[datetime] = _ts()
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    lifecycle_stage: Mapped[str] = mapped_column(String(20), default="unknown")
    lifecycle_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    lifecycle_signals: Mapped[list] = mapped_column(JSON, default=list)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("org_id", "client_event_id"),
        Index("ix_events_unchunked", "org_id", "session_id", "chunk_id"),
    )
    id: Mapped[str] = _id("evt")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    client_event_id: Mapped[str] = mapped_column(String(80))
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    page_route: Mapped[str] = mapped_column(String(300), default="/")
    journey_stage: Mapped[str] = mapped_column(String(40), default="browse", index=True)
    element_category: Mapped[str | None] = mapped_column(String(60), nullable=True)
    event_timestamp: Mapped[datetime] = _ts(index=True)
    received_at: Mapped[datetime] = _ts()
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    consent_state: Mapped[str] = mapped_column(String(20), default="authorized")
    redaction_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)  # "-" = reviewed, no episode
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[str] = _id("chk")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    journey_stage: Mapped[str] = mapped_column(String(40))
    signal: Mapped[str] = mapped_column(String(30), default="")
    issue_signature: Mapped[str] = mapped_column(String(80), default="", index=True)
    summary: Mapped[str] = mapped_column(Text)
    original_summary: Mapped[str] = mapped_column(Text, default="")
    events: Mapped[list] = mapped_column(JSON, default=list)
    source_event_ids: Mapped[list] = mapped_column(JSON, default=list)
    observations: Mapped[dict] = mapped_column(JSON, default=dict)
    sensitivity_status: Mapped[str] = mapped_column(String(20), default="clean")  # clean | filtered | flagged
    state: Mapped[str] = mapped_column(String(30), default=ChunkState.PENDING_REVIEW, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    review_mode: Mapped[str] = mapped_column(String(10), default="auto")  # auto | manual
    review_deadline: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    hold_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    validation_errors: Mapped[list] = mapped_column(JSON, default=list)
    ingest_attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    edited_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)


# ── Knowledge and retrieval ────────────────────────────────────────────────────
class EvidenceRecord(Base):
    __tablename__ = "evidence_records"
    __table_args__ = (
        UniqueConstraint("chunk_id", "chunk_version", name="uq_evidence_chunk_version"),
        UniqueConstraint("org_id", "collection", "source_ref", "content_hash", name="uq_evidence_doc"),
        Index("ix_evidence_scope", "org_id", "collection", "active"),
    )
    id: Mapped[str] = _id("ev")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    collection: Mapped[str] = mapped_column(String(30))
    source_ref: Mapped[str] = mapped_column(String(120))
    source_type: Mapped[str] = mapped_column(String(30), default="document")
    title: Mapped[str] = mapped_column(String(300), default="")
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list | None] = mapped_column(EmbeddingType, nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(80), default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    session_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    chunk_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    chunk_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quarantined: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _ts()
    effective_at: Mapped[datetime] = _ts()


class RetrievalRecord(Base):
    __tablename__ = "retrieval_records"
    id: Mapped[str] = _id("ret")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    incident_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    purpose: Mapped[str] = mapped_column(String(40), default="incident_analysis")
    query: Mapped[str] = mapped_column(Text)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    context: Mapped[str] = mapped_column(Text, default="")
    embedding_provider: Mapped[str] = mapped_column(String(80), default="")
    rerank_provider: Mapped[str] = mapped_column(String(80), default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _ts(index=True)


# ── Intelligence and action ────────────────────────────────────────────────────
class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[str] = _id("inc")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    issue_signature: Mapped[str] = mapped_column(String(80), index=True)
    journey_stage: Mapped[str] = mapped_column(String(40))
    signal: Mapped[str] = mapped_column(String(30))
    incident_type: Mapped[str] = mapped_column(String(60), default="unclassified")
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    severity: Mapped[str] = mapped_column(String(10), default="medium")
    severity_score: Mapped[float] = mapped_column(Float, default=0.0)
    affected_sessions: Mapped[int] = mapped_column(Integer, default=0)
    chunk_ids: Mapped[list] = mapped_column(JSON, default=list)
    lifecycle_stage: Mapped[str] = mapped_column(String(20), default="unknown")
    observed_facts: Mapped[list] = mapped_column(JSON, default=list)
    hypotheses: Mapped[list] = mapped_column(JSON, default=list)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    unresolved_questions: Mapped[list] = mapped_column(JSON, default=list)
    recommended_action: Mapped[dict] = mapped_column(JSON, default=dict)
    customer_message_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    analysis_provider: Mapped[str] = mapped_column(String(60), default="")
    analysis_notes: Mapped[list] = mapped_column(JSON, default=list)
    last_retrieval_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    chunks_at_analysis: Mapped[int] = mapped_column(Integer, default=0)
    regression_count: Mapped[int] = mapped_column(Integer, default=0)
    resolution_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    first_seen_at: Mapped[datetime] = _ts()
    last_seen_at: Mapped[datetime] = _ts()
    analyzed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)


class Action(Base):
    __tablename__ = "actions"
    __table_args__ = (UniqueConstraint("org_id", "idempotency_key"),)
    id: Mapped[str] = _id("act")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    resolution_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    type: Mapped[str] = mapped_column(String(40))
    category: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(300))
    rationale: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(10), default="medium")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="PROPOSED", index=True)
    policy_result: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    decided_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    execution_result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _ts(index=True)
    updated_at: Mapped[datetime] = _ts()


class Intervention(Base):
    __tablename__ = "interventions"
    id: Mapped[str] = _id("int")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    incident_id: Mapped[str] = mapped_column(String(40), index=True)
    action_id: Mapped[str] = mapped_column(String(40), index=True)
    summary: Mapped[str] = mapped_column(Text)
    segment: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = _ts()


class Resolution(Base):
    __tablename__ = "resolutions"
    id: Mapped[str] = _id("res")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    issue_category: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="pending_verification")  # verified | pending_verification
    sources: Mapped[list] = mapped_column(JSON, default=list)
    approved_claims: Mapped[list] = mapped_column(JSON, default=list)
    segment_available: Mapped[bool] = mapped_column(Boolean, default=False)
    email_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_notes: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = _ts()
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Communication(Base):
    __tablename__ = "communications"
    __table_args__ = (UniqueConstraint("resolution_id", "customer_id"),)
    id: Mapped[str] = _id("com")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    incident_id: Mapped[str] = mapped_column(String(40), index=True)
    resolution_id: Mapped[str] = mapped_column(String(40), index=True)
    customer_id: Mapped[str] = mapped_column(String(40), index=True)
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    claims_used: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|approved|sent_simulated|blocked|rejected
    policy_result: Mapped[dict] = mapped_column(JSON, default=dict)
    holdout: Mapped[bool] = mapped_column(Boolean, default=False)
    generated_by: Mapped[str] = mapped_column(String(60), default="")
    approved_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = _ts(index=True)


class Outcome(Base):
    __tablename__ = "outcomes"
    id: Mapped[str] = _id("out")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    incident_id: Mapped[str] = mapped_column(String(40), index=True)
    resolution_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    metric: Mapped[str] = mapped_column(String(60))
    baseline_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    post_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_baseline: Mapped[int] = mapped_column(Integer, default=0)
    n_post: Mapped[int] = mapped_column(Integer, default=0)
    method: Mapped[str] = mapped_column(String(30), default="before_after")
    strength: Mapped[str] = mapped_column(String(20), default="insufficient")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _ts(index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = _id("aud")
    org_id: Mapped[str] = mapped_column(String(40), index=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[str] = mapped_column(String(60))
    from_state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ts: Mapped[datetime] = _ts(index=True)
