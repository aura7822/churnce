"""Lifecycle stage classification. Never infers a stage from a single click; says 'unknown' when thin."""

from __future__ import annotations

from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Event, SessionRec
from .utils import utcnow

MIN_EVENTS = 3


def classify_session(db: Session, sess: SessionRec) -> tuple[str, float, list[str]]:
    signals: list[str] = []
    q = select(SessionRec.id).where(SessionRec.org_id == sess.org_id)
    q = q.where(SessionRec.customer_id == sess.customer_id) if sess.customer_id else q.where(SessionRec.id == sess.id)
    ids = list(db.scalars(q))

    total_events = db.scalar(select(func.count()).select_from(Event).where(Event.session_id.in_(ids))) or 0
    if total_events < MIN_EVENTS:
        return "unknown", 0.2, [f"only {total_events} events observed; not enough to place the customer"]

    stages = Counter(
        db.scalars(select(Event.journey_stage).where(Event.session_id == sess.id))
    )
    current = stages.most_common(1)[0][0] if stages else "browse"
    purchases = db.scalar(
        select(func.count()).select_from(Event).where(
            Event.session_id.in_(ids), Event.event_type == "workflow_completed", Event.journey_stage == "checkout"
        )
    ) or 0
    activated = (db.scalar(
        select(func.count()).select_from(Event).where(
            Event.session_id.in_(ids), Event.event_type == "workflow_completed", Event.journey_stage == "onboarding"
        )
    ) or 0) > 0
    n_sessions = len(ids)

    prior_last = None
    if sess.customer_id:
        prior_last = db.scalar(
            select(func.max(SessionRec.last_seen)).where(
                SessionRec.customer_id == sess.customer_id, SessionRec.id != sess.id
            )
        )
    gap_days = (utcnow() - prior_last).days if prior_last else None

    signals.append(f"{n_sessions} session(s), {purchases} completed purchase(s), onboarding {'done' if activated else 'not done'}")
    if gap_days is not None and gap_days >= 30:
        signals.append(f"returned after {gap_days} days of inactivity")
        return "reactivation", 0.7, signals
    if current in ("registration",):
        return "acquisition", 0.7, signals
    if current == "checkout":
        if purchases == 0:
            return "acquisition", 0.65, signals + ["attempting first purchase"]
        return "retention", 0.65, signals + ["repeat purchase activity"]
    if current == "onboarding":
        return ("engagement", 0.5, signals) if activated else ("activation", 0.7, signals + ["onboarding in progress"])
    if current in ("search", "dashboard", "browse"):
        if activated or n_sessions >= 3:
            return ("retention" if purchases and n_sessions >= 3 else "engagement"), 0.55, signals
        return ("awareness" if n_sessions == 1 and current == "browse" else "engagement"), 0.45, signals
    return "unknown", 0.3, signals


def refresh_session(db: Session, sess: SessionRec) -> None:
    stage, conf, signals = classify_session(db, sess)
    sess.lifecycle_stage, sess.lifecycle_confidence, sess.lifecycle_signals = stage, conf, signals


def classify_incident(db: Session, session_ids: list[str]) -> tuple[str, float]:
    """Majority stage across affected sessions, weighted by classifier confidence."""
    weights: Counter[str] = Counter()
    for sid in session_ids:
        sess = db.get(SessionRec, sid)
        if not sess:
            continue
        refresh_session(db, sess)
        if sess.lifecycle_stage != "unknown":
            weights[sess.lifecycle_stage] += sess.lifecycle_confidence
    if not weights:
        return "unknown", 0.0
    stage, w = weights.most_common(1)[0]
    return stage, round(w / max(1, sum(weights.values())), 2)
