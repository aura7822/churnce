"""Scripted customer journeys for the controlled demonstration.

Everything produced here is flagged `simulated=True` and flows through exactly the same ingest path
as real extension traffic (consent, domain checks, redaction, chunking), so the demo exercises the
real pipeline. The dashboard labels these results as simulated, never as real-customer measurements.
"""
from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .collector import EventBatch, EventIn, IngestResult, ingest_events
from .models import Customer, MonitoringConfig
from .utils import new_id, utcnow

SCENARIOS: dict[str, dict[str, str]] = {
    "checkout_failure": {
        "label": "Checkout failure",
        "description": "Customers hit repeated payment timeouts on the primary checkout action, then abandon.",
    },
    "checkout_success": {
        "label": "Healthy checkout",
        "description": "Customers complete checkout normally. Run after a verified fix to measure the outcome.",
    },
    "onboarding_stall": {
        "label": "Onboarding stall",
        "description": "Customers fail the profile-setup step during onboarding and give up.",
    },
    "search_dead_end": {
        "label": "Search dead ends",
        "description": "Customers search repeatedly and never see a useful result.",
    },
}


def _host(cfg: MonitoringConfig) -> str:
    for d in cfg.authorized_domains or []:
        if not d.startswith("*"):
            return d
    return "localhost"


def _journey(scenario: str, step_ms: int = 700) -> list[dict[str, Any]]:
    """Ordered (relative) events for one session."""
    if scenario == "checkout_failure":
        ep = "/api/payments/charge"
        return [
            dict(event_type="page_view", page_route="/cart"),
            dict(event_type="page_view", page_route="/checkout", response_time_ms=620),
            dict(event_type="click", page_route="/checkout", element_category="primary_action", meta={"element_label": "Pay now"}),
            dict(event_type="interaction_failure", page_route="/checkout", element_category="primary_action", outcome="timeout", response_time_ms=4800, meta={"endpoint": ep, "http_status": 504}),
            dict(event_type="click", page_route="/checkout", element_category="primary_action", meta={"element_label": "Pay now"}),
            dict(event_type="interaction_failure", page_route="/checkout", element_category="primary_action", outcome="timeout", response_time_ms=5100, meta={"endpoint": ep, "http_status": 504}),
            dict(event_type="click", page_route="/checkout", element_category="primary_action", meta={"element_label": "Pay now"}),
            dict(event_type="interaction_failure", page_route="/checkout", element_category="primary_action", outcome="error", response_time_ms=2300, meta={"endpoint": ep, "http_status": 502}),
            dict(event_type="abandonment", page_route="/checkout", outcome="abandoned"),
        ]
    if scenario == "checkout_success":
        ep = "/api/payments/charge"
        return [
            dict(event_type="page_view", page_route="/cart"),
            dict(event_type="page_view", page_route="/checkout", response_time_ms=540),
            dict(event_type="click", page_route="/checkout", element_category="primary_action", outcome="success", response_time_ms=410, meta={"endpoint": ep, "http_status": 200}),
            dict(event_type="workflow_completed", page_route="/checkout", outcome="success"),
        ]
    if scenario == "onboarding_stall":
        ep = "/api/onboarding/profile"
        return [
            dict(event_type="page_view", page_route="/onboarding"),
            dict(event_type="click", page_route="/onboarding", element_category="primary_action", meta={"step": "profile"}),
            dict(event_type="interaction_failure", page_route="/onboarding", element_category="primary_action", outcome="error", response_time_ms=1900, meta={"endpoint": ep, "http_status": 500, "step": "profile"}),
            dict(event_type="click", page_route="/onboarding", element_category="primary_action", meta={"step": "profile"}),
            dict(event_type="interaction_failure", page_route="/onboarding", element_category="primary_action", outcome="error", response_time_ms=2100, meta={"endpoint": ep, "http_status": 500, "step": "profile"}),
            dict(event_type="error_message", page_route="/onboarding", outcome="error", meta={"error_code": "PROFILE_SAVE_FAILED"}),
            dict(event_type="abandonment", page_route="/onboarding", outcome="abandoned"),
        ]
    if scenario == "search_dead_end":
        return [
            dict(event_type="page_view", page_route="/search"),
            dict(event_type="search_no_results", page_route="/search", outcome="no_results", meta={"search_query": "waterproof hiking boots wide"}),
            dict(event_type="search_no_results", page_route="/search", outcome="no_results", meta={"search_query": "wide waterproof boots"}),
            dict(event_type="search_no_results", page_route="/search", outcome="no_results", meta={"search_query": "boots wide fit"}),
            dict(event_type="abandonment", page_route="/search", outcome="abandoned"),
        ]
    raise ValueError(f"Unknown scenario '{scenario}'")


def simulate(db: Session, cfg: MonitoringConfig, scenario: str, sessions: int = 3, with_customers: bool = True) -> dict[str, Any]:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario '{scenario}'")
    sessions = max(1, min(int(sessions), 12))
    host = _host(cfg)
    customers = (
        list(db.scalars(select(Customer.ref).where(Customer.org_id == cfg.org_id).order_by(Customer.ref)))
        if with_customers
        else []
    )
    random.shuffle(customers)
    now = utcnow()
    total = IngestResult()
    session_ids: list[str] = []
    for i in range(sessions):
        sid = new_id("sim")
        session_ids.append(sid)
        ref = customers[i % len(customers)] if customers else None
        steps = _journey(scenario)
        t0 = now - timedelta(milliseconds=700 * len(steps))
        events = [
            EventIn(
                event_id=new_id("evt"),
                session_id=sid,
                customer_ref=ref,
                site_host=host,
                simulated=True,
                event_timestamp=t0 + timedelta(milliseconds=700 * n),
                **step,
            )
            for n, step in enumerate(steps)
        ]
        res = ingest_events(db, cfg, EventBatch(events=events, site_host=host))
        total.accepted += res.accepted
        total.duplicates += res.duplicates
        total.rejected += res.rejected
    return {"scenario": scenario, "sessions": sessions, "accepted": total.accepted, "rejected": total.rejected, "simulated": True}
