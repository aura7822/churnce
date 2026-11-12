#!/usr/bin/env python3
"""Drive a scripted customer journey through Churnce and watch the pipeline react.

Two modes:
  --mode ingest  (default) POST raw events with the site's ingest key, exactly as the browser
                 extension does. This exercises consent, domain checks, redaction and chunking.
  --mode api     Use the authenticated /demo/simulate endpoint (several scenarios, demo tenant only).

Everything it sends is flagged simulated=true and the dashboard labels it as such.

    python scripts/simulate_journey.py                       # checkout failure, 3 sessions
    python scripts/simulate_journey.py --scenario search_dead_end --mode api
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _client import Client, wait_for  # noqa: E402

DEMO_INGEST_KEY = "chn_live_demo_northwind_0000000000000000"  # published demo key; see backend/app/seed.py
SCENARIOS = ("checkout_failure", "checkout_success", "onboarding_stall", "search_dead_end")


def checkout_failure_events(session_id: str, customer_ref: str | None, host: str) -> list[dict]:
    """The spec's section 24 journey: repeated slow/failed pay attempts, then abandonment."""
    ep = "/api/payments/charge"
    steps = [
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
    t0 = datetime.now(timezone.utc) - timedelta(milliseconds=700 * len(steps))
    return [
        {
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "session_id": session_id,
            "customer_ref": customer_ref,
            "site_host": host,
            "simulated": True,
            "event_timestamp": (t0 + timedelta(milliseconds=700 * i)).isoformat(),
            **s,
        }
        for i, s in enumerate(steps)
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://localhost:8000", help="backend base URL")
    ap.add_argument("--mode", choices=("ingest", "api"), default="ingest")
    ap.add_argument("--scenario", choices=SCENARIOS, default="checkout_failure")
    ap.add_argument("--sessions", type=int, default=3, help="distinct sessions (incidents need at least 2)")
    ap.add_argument("--ingest-key", default=DEMO_INGEST_KEY)
    ap.add_argument("--email", default="admin@churnce.demo")
    ap.add_argument("--password", default="Churnce!2026")
    ap.add_argument("--no-wait", action="store_true", help="send events and exit")
    args = ap.parse_args()

    c = Client(args.api)
    me = c.login(args.email, args.password)
    print(f"Signed in as {me['user']['email']} ({me['user']['role']}) on {me['organization']['name']} [{me['environment']}]")

    if args.mode == "ingest":
        if args.scenario != "checkout_failure":
            sys.exit("--mode ingest only scripts checkout_failure; use --mode api for the other scenarios.")
        sent = 0
        for i in range(args.sessions):
            events = checkout_failure_events(f"sim_{uuid.uuid4().hex[:10]}", f"cust_{i + 1:03d}", "localhost")
            out = c.request("POST", "/events", {"events": events, "site_host": "localhost"}, headers={"X-Churnce-Key": args.ingest_key})
            sent += out["accepted"]
            if out["rejected"]:
                print("  rejected:", out["rejected"])
        print(f"Ingested {sent} events across {args.sessions} sessions.")
    else:
        out = c.request("POST", "/demo/simulate", {"scenario": args.scenario, "sessions": args.sessions})
        print(f"Simulated {out['scenario']}: accepted={out['accepted']} rejected={len(out['rejected']) if isinstance(out['rejected'], list) else out['rejected']}")

    if args.no_wait:
        return 0

    print("Waiting for the chunk review gate (open the dashboard's Chunk Lab to edit or approve inside the window)...")
    pending = wait_for(lambda: c.request("GET", "/chunks/pending")["chunks"], 30, 1.0, "pending chunks")
    if pending:
        for ch in pending[:5]:
            print(f"  pending {ch['id']}  v{ch['version']}  {ch['summary']}")
    approved = wait_for(
        lambda: [x for x in c.request("GET", "/chunks?state=AVAILABLE_FOR_RETRIEVAL")["chunks"]] or None,
        60, 2.0, "an indexed chunk",
    )
    print(f"Indexed chunks available for retrieval: {len(approved) if approved else 0}")

    inc = wait_for(
        lambda: [i for i in c.request("GET", "/incidents")["incidents"] if i["analyzed_at"]] or None, 90, 2.0, "an analysed incident"
    )
    if not inc:
        print("No analysed incident yet. Check the Intelligence page; incidents need >= 2 affected sessions.")
        return 1
    top = inc[0]
    print(f"\nIncident {top['id']}: {top['title']}")
    print(f"  type={top['incident_type']}  lifecycle={top['lifecycle_stage']}  severity={top['severity']}  provider={top['analysis_provider']}")
    for h in top["hypotheses"][:2]:
        print(f"  hypothesis ({h.get('confidence')}): {h.get('description')}")
    ra = top["recommended_action"] or {}
    print(f"  recommended: {ra.get('type')} [{ra.get('priority')}] - {ra.get('reason')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
