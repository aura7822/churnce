"""Hybrid semantic chunking: journey boundaries define context, thresholds bound size."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Iterable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .audit import audit
from .config import get_settings
from .database import notify
from .enums import ChunkState, STAGE_OF_STATE
from .models import Chunk, Event, MonitoringConfig, SessionRec
from .privacy import redact, scan
from .utils import iso, utcnow

settings = get_settings()

MAX_EVENTS_PER_CHUNK = 12
FRICTION_TRIGGER = 5
SKIPPED = "-"

TERMINAL_TYPES = {"workflow_completed", "abandonment"}


def event_signal(ev: Event) -> str | None:
    """Classify a single event as a friction signal, or None if it is neutral."""
    t, outcome, rt = ev.event_type, (ev.outcome or ""), ev.response_time_ms or 0
    if t == "interaction_failure":
        return "timeout" if outcome == "timeout" else "error"
    if t == "error_message":
        return "error"
    if t == "form_validation_failure":
        return "validation_failure"
    if t == "search_no_results":
        return "no_results"
    if t == "abandonment":
        return "abandoned"
    if t == "slow_response":
        return "slow"
    if t == "repeated_click":
        return "unresponsive"
    if outcome == "timeout":
        return "timeout"
    if outcome in ("error", "failure"):
        return "error"
    if rt > settings.slow_threshold_ms and outcome not in ("success", "ok") and t in ("click", "page_load"):
        return "slow"
    return None


def describe_event(ev: Event) -> str:
    t, rt = ev.event_type, ev.response_time_ms
    code = ev.meta.get("http_status") or ev.meta.get("error_code")
    if t == "interaction_failure":
        if ev.outcome == "timeout":
            return f"Request timed out{f' after {rt} ms' if rt else ''}"
        return f"Request returned an error{f' (HTTP {code})' if code else ''}"
    if t == "click":
        if ev.element_category == "primary_action":
            return f"Primary action attempted on {ev.page_route}"
        return f"Clicked {ev.element_category or 'element'} on {ev.page_route}"
    if t == "repeated_click":
        return f"Repeated clicks with no visible response on {ev.page_route}"
    if t == "form_validation_failure":
        return f"Form validation failed ({ev.meta.get('form_field_category', 'field')})"
    if t == "search":
        return "Search performed"
    if t == "search_no_results":
        return "Search returned no useful results"
    if t == "error_message":
        return f"Visible error message shown{f' ({code})' if code else ''}"
    if t == "abandonment":
        step = ev.meta.get("step")
        return f"Workflow abandoned{f' at step {step}' if step else ''}"
    if t == "workflow_completed":
        return "Workflow completed"
    if t == "slow_response":
        return f"Slow response{f' ({rt} ms)' if rt else ''}"
    if t == "inactivity":
        return "Inactivity interval"
    if t == "page_load":
        return f"Loaded {ev.page_route}{f' in {rt} ms' if rt else ''}"
    return f"Viewed {ev.page_route}"


def _dominant_signal(signals: list[str]) -> str:
    if not signals:
        return ""
    if "abandoned" in signals and len(set(signals) - {"abandoned"}) == 0:
        return "abandoned"
    non_abandon = [s for s in signals if s != "abandoned"]
    pool = non_abandon or signals
    return Counter(pool).most_common(1)[0][0]


def _summary(stage: str, signal: str, friction: int, completed: bool, abandoned: bool) -> str:
    label = stage.replace("_", " ")
    if completed and friction:
        return f"Completed {label} after {friction} friction event{'s' if friction != 1 else ''}"
    if signal == "timeout":
        return f"Repeated {label} interaction timeouts" if friction > 1 else f"{label.capitalize()} interaction timed out"
    if signal == "error":
        return f"Repeated {label} errors" if friction > 1 else f"{label.capitalize()} returned an error"
    if signal == "validation_failure":
        return f"Repeated {label} form validation failures"
    if signal == "no_results":
        return "Searches returned no useful results"
    if signal == "slow":
        return f"Slow responses during {label}"
    if signal == "unresponsive":
        return f"Interface unresponsive during {label}"
    if signal == "abandoned" or abandoned:
        return f"{label.capitalize()} workflow abandoned"
    return f"{label.capitalize()} activity"


def _qualifies(group: list[Event]) -> bool:
    friction = sum(1 for e in group if event_signal(e))
    completed = any(e.event_type == "workflow_completed" for e in group)
    if friction:
        return True
    return completed and len(group) >= 3  # success worth remembering only if there was a journey


def _build_chunk(db: Session, session: SessionRec, cfg: MonitoringConfig, group: list[Event], now) -> Chunk | None:
    signals = [s for s in (event_signal(e) for e in group) if s]
    completed = any(e.event_type == "workflow_completed" for e in group)
    abandoned = any(e.event_type == "abandonment" for e in group)
    stage = group[0].journey_stage
    dominant = _dominant_signal(signals)
    friction = len(signals)

    lines, redactions = [], 0
    for e in group:
        text, found = redact(describe_event(e))
        redactions += sum(found.values()) + e.redaction_count
        lines.append(text)

    primary_clicks = sum(1 for e in group if e.event_type == "click" and e.element_category == "primary_action")
    rts = [e.response_time_ms for e in group if e.response_time_ms]
    endpoints = Counter(e.meta.get("endpoint") for e in group if e.meta.get("endpoint"))
    statuses = Counter(str(e.meta.get("http_status")) for e in group if e.meta.get("http_status"))
    t0, t1 = group[0].event_timestamp, group[-1].event_timestamp
    observations = {
        "attempt_count": max(primary_clicks, friction),
        "failure_count": friction,
        "observed_response_time_ms": max(rts) if rts else None,
        "workflow_completed": completed,
        "workflow_abandoned": abandoned,
        "event_count": len(group),
        "duration_seconds": max(0, int((t1 - t0).total_seconds())),
        "endpoint": endpoints.most_common(1)[0][0] if endpoints else None,
        "http_status": statuses.most_common(1)[0][0] if statuses else None,
    }
    summary = _summary(stage, dominant, friction, completed, abandoned)
    sensitivity = "filtered" if redactions else "clean"
    if scan(summary + " " + " ".join(lines)):
        sensitivity = "flagged"  # residual sensitive content after redaction: never auto-approve

    manual = cfg.review_policy == "manual" or (cfg.review_policy == "restricted" and bool(session.customer_ref))
    chunk = Chunk(
        org_id=session.org_id,
        session_id=session.id,
        journey_stage=stage,
        signal=dominant,
        issue_signature=f"{stage}:{dominant}" if dominant and friction else "",
        summary=summary,
        original_summary=summary,
        events=lines,
        source_event_ids=[e.id for e in group],
        observations=observations,
        sensitivity_status=sensitivity,
        state=ChunkState.PENDING_REVIEW,
        version=1,
        review_mode="manual" if manual else "auto",
        review_deadline=None if manual else now + timedelta(seconds=cfg.review_seconds or settings.review_seconds),
        simulated=session.simulated,
    )
    db.add(chunk)
    db.flush()
    db.execute(update(Event).where(Event.id.in_([e.id for e in group])).values(chunk_id=chunk.id))
    audit(db, chunk.org_id, "system", "chunk_created", "chunk", chunk.id, None, ChunkState.PENDING_REVIEW)
    notify(db, chunk.org_id, {"type": "chunk_created", "chunk_id": chunk.id, "session_id": session.id})
    notify(
        db,
        chunk.org_id,
        {
            "type": "pipeline_stage_changed",
            "chunk_id": chunk.id,
            "previous_stage": STAGE_OF_STATE[ChunkState.CREATED],
            "current_stage": STAGE_OF_STATE[ChunkState.PENDING_REVIEW],
            "timestamp": iso(now),
        },
    )
    return chunk


def _groups(events: Iterable[Event], now, idle_seconds: int, flush_idle: bool) -> list[list[Event]]:
    groups: list[list[Event]] = []
    cur: list[Event] = []
    for ev in events:
        if cur and ev.journey_stage != cur[0].journey_stage:
            groups.append(cur)  # journey boundary
            cur = []
        cur.append(ev)
        friction = sum(1 for e in cur if event_signal(e))
        if ev.event_type in TERMINAL_TYPES or len(cur) >= MAX_EVENTS_PER_CHUNK or friction >= FRICTION_TRIGGER:
            groups.append(cur)
            cur = []
    if cur and flush_idle:
        idle = (now - max(e.received_at for e in cur)).total_seconds() >= idle_seconds
        if idle:
            groups.append(cur)
            cur = []
    return groups


def process_session(
    db: Session, session: SessionRec, cfg: MonitoringConfig, now=None, flush_idle: bool = False
) -> list[Chunk]:
    now = now or utcnow()
    events = list(
        db.scalars(
            select(Event)
            .where(Event.session_id == session.id, Event.chunk_id.is_(None))
            .order_by(Event.event_timestamp, Event.received_at, Event.id)
        )
    )
    if not events:
        return []
    created: list[Chunk] = []
    for group in _groups(events, now, settings.chunk_idle_seconds, flush_idle):
        if _qualifies(group):
            chunk = _build_chunk(db, session, cfg, group, now)
            if chunk:
                created.append(chunk)
        else:
            db.execute(update(Event).where(Event.id.in_([e.id for e in group])).values(chunk_id=SKIPPED))
    return created


def flush_idle_sessions(db: Session, limit: int = 50) -> int:
    """Close open episodes for sessions that have gone quiet."""
    now = utcnow()
    cutoff = now - timedelta(seconds=settings.chunk_idle_seconds)
    session_ids = list(
        db.scalars(
            select(Event.session_id)
            .where(Event.chunk_id.is_(None), Event.received_at < cutoff)
            .group_by(Event.session_id)
            .limit(limit)
        )
    )
    made = 0
    for sid in session_ids:
        sess = db.get(SessionRec, sid)
        if not sess:
            continue
        cfg = db.scalar(select(MonitoringConfig).where(MonitoringConfig.org_id == sess.org_id))
        if cfg:
            made += len(process_session(db, sess, cfg, now=now, flush_idle=True))
    return made
