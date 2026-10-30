"""Outcome measurement and intervention memory. Reports strength of evidence, never just a delta."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .audit import audit
from .config import get_settings
from .database import notify
from .enums import ActionStatus, ChunkState
from .models import (
    Action,
    Chunk,
    Communication,
    Event,
    Incident,
    Outcome,
    Resolution,
    SessionRec,
)
from .rag.store import ingest_document
from .utils import iso, utcnow

settings = get_settings()
MIN_SAMPLE = 5
STRONG_SAMPLE = 30


def stage_completion(db: Session, org_id: str, stage: str, since: datetime | None = None, until: datetime | None = None) -> dict[str, Any]:
    """Share of sessions touching a journey stage that completed its workflow in the window."""
    base = [Event.org_id == org_id, Event.journey_stage == stage]
    if since:
        base.append(Event.event_timestamp >= since)
    if until:
        base.append(Event.event_timestamp < until)
    touched = db.scalar(select(func.count(func.distinct(Event.session_id))).where(*base)) or 0
    done = db.scalar(select(func.count(func.distinct(Event.session_id))).where(*base, Event.event_type == "workflow_completed")) or 0
    return {"sessions": touched, "completed": done, "rate": (done / touched) if touched else 0.0}


def _strength(n_a: int, n_b: int, method: str) -> str:
    if min(n_a, n_b) < MIN_SAMPLE:
        return "insufficient"
    if method == "holdout" and min(n_a, n_b) >= STRONG_SAMPLE:
        return "strong"
    return "moderate" if min(n_a, n_b) >= STRONG_SAMPLE else "low"


def evaluate_outcome(db: Session, inc: Incident, actor: str) -> list[Outcome]:
    res = db.get(Resolution, inc.resolution_id) if inc.resolution_id else None
    if not res or res.status != "verified" or not res.verified_at:
        raise ValueError("Outcomes are measured against a verified resolution; record one first.")
    t = res.verified_at
    before = stage_completion(db, inc.org_id, inc.journey_stage, until=t)
    after = stage_completion(db, inc.org_id, inc.journey_stage, since=t)

    caveats = [
        "Before/after comparisons are observational. Seasonality, traffic mix and other releases can move the same metric.",
        "A verified technical fix does not guarantee every customer experiences the improvement.",
    ]
    if inc.simulated:
        caveats.insert(0, "Simulated data: these figures come from scripted journeys, not real customers.")
    strength = _strength(before["sessions"], after["sessions"], "before_after")
    if strength == "insufficient":
        caveats.append(f"Fewer than {MIN_SAMPLE} sessions in a window; no conclusion should be drawn yet.")

    outcomes = [
        Outcome(
            org_id=inc.org_id,
            incident_id=inc.id,
            resolution_id=res.id,
            metric=f"{inc.journey_stage}_workflow_completion_rate",
            baseline_value=before["rate"],
            post_value=after["rate"],
            n_baseline=before["sessions"],
            n_post=after["sessions"],
            method="before_after",
            strength=strength,
            details={"before": before, "after": after, "caveats": caveats, "resolution_verified_at": iso(t)},
            simulated=inc.simulated,
        )
    ]

    # Re-engagement: did emailed customers come back and finish, compared with a holdout if one exists.
    comms = list(db.scalars(select(Communication).where(Communication.resolution_id == res.id)))
    sent = [c for c in comms if c.status == "sent_simulated"]
    held = [c for c in comms if c.holdout]

    def returned_and_completed(cs: list[Communication], since_attr: str) -> int:
        n = 0
        for c in cs:
            since = getattr(c, since_attr) or t
            got = db.scalar(
                select(Event.id)
                .join(SessionRec, SessionRec.id == Event.session_id)
                .where(
                    SessionRec.customer_id == c.customer_id,
                    Event.event_type == "workflow_completed",
                    Event.journey_stage == inc.journey_stage,
                    Event.event_timestamp > since,
                )
                .limit(1)
            )
            n += 1 if got else 0
        return n

    if sent or held:
        treated_done = returned_and_completed(sent, "sent_at")
        held_done = returned_and_completed(held, "created_at")
        method = "holdout" if held else "treated_only"
        s = _strength(len(sent), len(held), method) if held else "insufficient"
        det = {
            "treated": {"customers": len(sent), "completed": treated_done},
            "holdout": {"customers": len(held), "completed": held_done},
            "caveats": caveats + (["No holdout group configured: treated customers cannot be compared with a counterfactual."] if not held else []),
        }
        outcomes.append(
            Outcome(
                org_id=inc.org_id,
                incident_id=inc.id,
                resolution_id=res.id,
                metric="reengagement_completion_rate",
                baseline_value=(held_done / len(held)) if held else None,
                post_value=(treated_done / len(sent)) if sent else None,
                n_baseline=len(held),
                n_post=len(sent),
                method=method,
                strength=s,
                details=det,
                simulated=inc.simulated,
            )
        )
    for o in outcomes:
        db.add(o)
    db.flush()

    for act in db.scalars(select(Action).where(Action.incident_id == inc.id, Action.status == ActionStatus.COMPLETED)):
        act.status = ActionStatus.OUTCOME
    audit(db, inc.org_id, actor, "outcome_evaluated", "incident", inc.id, None, None, {"strength": strength})

    # Intervention memory: store the result together with its segment, context and method.
    head = outcomes[0]
    delta = (head.post_value or 0) - (head.baseline_value or 0)
    memo = (
        f"Intervention outcome for {inc.title}. Segment: {inc.journey_stage} journeys, lifecycle stage {inc.lifecycle_stage}, "
        f"{inc.affected_sessions} affected session(s). Action taken: resolution '{res.issue_category}' verified via "
        + ", ".join(sorted({s['type'] for s in res.sources}))
        + f". Measurement: before/after completion rate {head.baseline_value:.0%} → {head.post_value:.0%} "
        f"(n={head.n_baseline}/{head.n_post}, change {delta:+.0%}); evidence strength {strength}. "
        + ("Simulated data. " if inc.simulated else "")
        + "Observational result: does not prove the same intervention will work in other contexts."
    )
    ingest_document(
        db, inc.org_id, "intervention_memory", f"outcome_{inc.id}", f"Outcome: {inc.title}", memo,
        meta={"incident": inc.id, "strength": strength, "simulated": inc.simulated}, source_type="outcome",
    )
    notify(db, inc.org_id, {"type": "outcome_recorded", "incident_id": inc.id})
    return outcomes


# ── Dashboard metrics: always computed from live state, never hard-coded ──────
def dashboard_metrics(db: Session, org_id: str) -> dict[str, Any]:
    def count(model, *where) -> int:
        return db.scalar(select(func.count()).select_from(model).where(model.org_id == org_id, *where)) or 0

    now = utcnow()
    states = dict(db.execute(select(Chunk.state, func.count()).where(Chunk.org_id == org_id).group_by(Chunk.state)).all())
    actions = dict(db.execute(select(Action.status, func.count()).where(Action.org_id == org_id).group_by(Action.status)).all())
    inc_open = count(Incident, Incident.status.not_in(["resolved"]))

    # Latency: how long chunks take from creation to being retrievable.
    rows = db.execute(
        select(Chunk.created_at, Chunk.indexed_at).where(Chunk.org_id == org_id, Chunk.indexed_at.is_not(None)).order_by(Chunk.indexed_at.desc()).limit(50)
    ).all()
    lat = sorted((b - a).total_seconds() * 1000 for a, b in rows)
    p50 = lat[len(lat) // 2] if lat else None
    p95 = lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None
    ingest_lag = db.execute(
        select(func.avg(func.julianday(Event.received_at) - func.julianday(Event.event_timestamp))).where(Event.org_id == org_id)
    ).scalar() if settings.is_sqlite else None

    return {
        "events_total": count(Event),
        "events_last_hour": count(Event, Event.received_at >= now - timedelta(hours=1)),
        "sessions_total": count(SessionRec),
        "chunks_total": sum(states.values()),
        "chunks_pending_review": states.get(ChunkState.PENDING_REVIEW, 0),
        "chunks_in_flight": sum(states.get(s, 0) for s in (ChunkState.APPROVED, ChunkState.VALIDATING, ChunkState.QUEUED, ChunkState.EMBEDDING)),
        "chunks_indexed": states.get(ChunkState.AVAILABLE, 0) + states.get(ChunkState.INDEXED, 0),
        "chunks_rejected": states.get(ChunkState.REJECTED, 0),
        "chunks_discarded": states.get(ChunkState.DISCARDED, 0),
        "chunk_states": states,
        "incidents_active": inc_open,
        "incidents_total": count(Incident),
        "recommendations_total": sum(actions.values()),
        "actions_awaiting_approval": actions.get(ActionStatus.AWAITING, 0),
        "actions_completed": actions.get(ActionStatus.COMPLETED, 0) + actions.get(ActionStatus.OUTCOME, 0),
        "actions_failed": actions.get(ActionStatus.FAILED, 0),
        "emails_draft": count(Communication, Communication.status == "draft"),
        "emails_approved": count(Communication, Communication.status.in_(["approved", "sent_simulated"])),
        "processing_latency_ms": {"p50": p50, "p95": p95, "samples": len(lat)},
        "ingest_lag_days_avg": ingest_lag,
    }
