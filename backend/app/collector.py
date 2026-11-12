"""Event intake: authorization, normalization, privacy filtering and idempotent storage."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import notify
from .enums import DEFAULT_JOURNEY_MAP, EVENT_TYPES
from .models import Customer, Event, MonitoringConfig, SessionRec
from .privacy import redact
from .utils import clamp, iso, utcnow

settings = get_settings()

# Only these meta keys survive normalization. Everything else is dropped, never stored.
META_ALLOWED = {
    "error_code",
    "http_status",
    "element_label",
    "search_query",
    "form_field_category",
    "step",
    "endpoint",
    "attempt",
    "reason",
}
OUTCOMES = {"success", "ok", "timeout", "error", "failure", "no_results", "validation_failure", "abandoned"}
ALIASES = {"route_change": "page_view", "navigation": "page_view", "rage_click": "repeated_click"}


class EventIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=80)
    session_id: str = Field(min_length=1, max_length=80)
    event_type: str = Field(min_length=1, max_length=40)
    page_route: str = Field(default="/", max_length=500)
    element_category: str | None = Field(default=None, max_length=60)
    event_timestamp: datetime | None = None
    response_time_ms: int | None = None
    outcome: str | None = Field(default=None, max_length=30)
    consent_state: str = "authorized"
    customer_ref: str | None = Field(default=None, max_length=80)
    journey_stage: str | None = Field(default=None, max_length=40)
    site_host: str | None = Field(default=None, max_length=200)
    meta: dict[str, Any] = Field(default_factory=dict)
    simulated: bool = False


class EventBatch(BaseModel):
    events: list[EventIn] = Field(min_length=1, max_length=100)
    site_host: str | None = None


class IngestResult(BaseModel):
    accepted: int = 0
    duplicates: int = 0
    rejected: list[dict[str, str]] = Field(default_factory=list)


_NUMERIC_SEGMENT = re.compile(r"/(?:\d{2,}|[0-9a-f]{8,}(?:-[0-9a-f]{4,})*)(?=/|$)", re.I)


def normalize_route(route: str) -> str:
    """Strip origin, query and fragment; collapse identifiers so routes group meaningfully."""
    parsed = urlparse(route)
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    path = _NUMERIC_SEGMENT.sub("/:id", path)
    return (path.rstrip("/") or "/")[:200]


def stage_for_route(route: str, journey_map: dict[str, str] | None) -> str:
    mapping = {**DEFAULT_JOURNEY_MAP, **(journey_map or {})}
    best, best_len = "browse", -1
    for prefix, stage in mapping.items():
        if (route == prefix or route.startswith(prefix.rstrip("/") + "/")) and len(prefix) > best_len:
            best, best_len = stage, len(prefix)
    return best


def clean_meta(meta: dict[str, Any]) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    redactions = 0
    for key, value in (meta or {}).items():
        if key not in META_ALLOWED or value is None:
            continue
        if isinstance(value, (int, float, bool)):
            out[key] = value
            continue
        text = str(value)
        if key == "endpoint":
            text = urlparse(text).path or text  # drop query strings, which often carry identifiers
        if key == "search_query":
            text = text[:80]
        text, found = redact(text)
        redactions += sum(found.values())
        out[key] = text[:200]
    return out, redactions


def _resolve_timestamp(ts: datetime | None, now: datetime) -> datetime:
    if ts is None:
        return now
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts = ts.astimezone(timezone.utc)
    if ts > now + timedelta(minutes=5):  # client clock ahead: trust server time
        return now
    return ts


def _host_authorized(host: str | None, domains: list[str]) -> bool:
    if not host:
        return False
    host = host.split(":")[0].lower()
    for d in domains:
        d = d.lower().strip()
        if host == d or (d.startswith("*.") and host.endswith(d[1:])):
            return True
    return False


def ingest_events(db: Session, cfg: MonitoringConfig, batch: EventBatch) -> IngestResult:
    result = IngestResult()
    if not cfg.monitoring_enabled:
        result.rejected.append({"event_id": "*", "reason": "monitoring_disabled"})
        return result

    now = utcnow()
    allowed_types = set(cfg.allowed_event_types or EVENT_TYPES)
    demo = cfg.environment == "demo"
    touched: dict[str, SessionRec] = {}
    seen_ids = set(
        db.scalars(
            select(Event.client_event_id).where(
                Event.org_id == cfg.org_id, Event.client_event_id.in_([e.event_id for e in batch.events])
            )
        )
    )

    for ev in batch.events:
        host = ev.site_host or batch.site_host
        if not _host_authorized(host, cfg.authorized_domains or []):
            result.rejected.append({"event_id": ev.event_id, "reason": "domain_not_authorized"})
            continue
        if ev.consent_state != "authorized":
            result.rejected.append({"event_id": ev.event_id, "reason": "consent_not_authorized"})
            continue
        etype = ALIASES.get(ev.event_type, ev.event_type)
        if etype not in EVENT_TYPES or etype not in allowed_types:
            result.rejected.append({"event_id": ev.event_id, "reason": "event_type_not_allowed"})
            continue
        if ev.event_id in seen_ids:
            result.duplicates += 1
            continue
        seen_ids.add(ev.event_id)

        route = normalize_route(ev.page_route)
        stage = (
            ev.journey_stage
            if ev.journey_stage and ev.journey_stage in {*DEFAULT_JOURNEY_MAP.values(), *(cfg.journey_map or {}).values()}
            else stage_for_route(route, cfg.journey_map)
        )
        meta, redactions = clean_meta(ev.meta)
        outcome = (ev.outcome or "").lower() or None
        if outcome and outcome not in OUTCOMES:
            outcome = "error" if "err" in outcome else None
        rt = int(clamp(ev.response_time_ms, 0, 600_000)) if ev.response_time_ms is not None else None

        sess = touched.get(ev.session_id)
        if sess is None:
            sess = db.scalar(
                select(SessionRec).where(SessionRec.org_id == cfg.org_id, SessionRec.external_id == ev.session_id)
            )
            if sess is None:
                sess = SessionRec(
                    org_id=cfg.org_id,
                    external_id=ev.session_id,
                    first_seen=now,
                    last_seen=now,
                    site_host=(host or "")[:200],
                    simulated=demo or ev.simulated,
                )
                db.add(sess)
            touched[ev.session_id] = sess
        if ev.customer_ref and not sess.customer_ref:
            sess.customer_ref = ev.customer_ref
            cust = db.scalar(select(Customer).where(Customer.org_id == cfg.org_id, Customer.ref == ev.customer_ref))
            if cust:
                sess.customer_id = cust.id
        sess.last_seen = now
        sess.event_count = (sess.event_count or 0) + 1
        db.flush()

        row = Event(
            org_id=cfg.org_id,
            session_id=sess.id,
            client_event_id=ev.event_id,
            event_type=etype,
            page_route=route,
            journey_stage=stage,
            element_category=ev.element_category,
            event_timestamp=_resolve_timestamp(ev.event_timestamp, now),
            received_at=now,
            response_time_ms=rt,
            outcome=outcome,
            meta=meta,
            consent_state=ev.consent_state,
            redaction_count=redactions,
            simulated=demo or ev.simulated,
        )
        db.add(row)
        db.flush()
        result.accepted += 1
        notify(
            db,
            cfg.org_id,
            {
                "type": "event_ingested",
                "event": {
                    "id": row.id,
                    "session_id": sess.id,
                    "event_type": row.event_type,
                    "page_route": row.page_route,
                    "journey_stage": row.journey_stage,
                    "outcome": row.outcome,
                    "response_time_ms": row.response_time_ms,
                    "redactions": row.redaction_count,
                    "simulated": row.simulated,
                    "event_timestamp": iso(row.event_timestamp),
                },
            },
        )

    if result.accepted:
        from .chunking import process_session

        for sess in touched.values():
            process_session(db, sess, cfg, now=now)
    return result
