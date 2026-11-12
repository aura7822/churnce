#!/usr/bin/env python3
"""Diagnosis accuracy on scripted incidents with known causes (spec 22.4 / Phase 8).

For each scenario this runs the real pipeline end to end, waits for the analysed incident on the same
journey stage and compares the incident type with the known label. A healthy-checkout run acts as a
negative control: it must NOT open or refresh a friction incident (false-positive check).

The result is tagged with the analysis provider the server reports, so you can compare the rules-only
baseline with Gemma by running this twice:
    LLM_PROVIDER=rules   ... start backend ... python scripts/evaluate_diagnosis.py
    LLM_PROVIDER=gemini  ... restart backend  ... python scripts/evaluate_diagnosis.py

Demo tenant only. Takes a few minutes (each scenario waits through the 30-second review window).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _client import Client, parse_ts, wait_for  # noqa: E402

# scenario -> (journey stage the incident must land on, expected incident_type)
LABELS = {
    "checkout_failure": ("checkout", "checkout_reliability"),
    "onboarding_stall": ("onboarding", "onboarding_reliability"),
    "search_dead_end": ("search", "search_discovery"),
}


def fresh_incident(c: Client, stage: str, since):
    for inc in c.request("GET", "/incidents")["incidents"]:
        if inc["journey_stage"] == stage and parse_ts(inc["last_seen_at"]) >= since and inc["analyzed_at"] and inc["status"] != "analyzing":
            if parse_ts(inc["analyzed_at"]) >= since:
                return inc
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--email", default="admin@churnce.demo")
    ap.add_argument("--password", default="Churnce!2026")
    ap.add_argument("--sessions", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=150, help="seconds to wait per scenario")
    ap.add_argument("--skip-negative", action="store_true")
    args = ap.parse_args()

    c = Client(args.api)
    c.login(args.email, args.password)
    rows, providers = [], set()

    for scenario, (stage, expected) in LABELS.items():
        since = parse_ts(c.request("GET", "/chunks?limit=1")["server_time"])
        c.request("POST", "/demo/simulate", {"scenario": scenario, "sessions": args.sessions})
        print(f"{scenario}: simulated, waiting for diagnosis...")
        inc = wait_for(lambda: fresh_incident(c, stage, since), args.timeout, 2.0, f"{stage} incident")
        got = inc["incident_type"] if inc else "(none)"
        provider = inc["analysis_provider"] if inc else "-"
        providers.add(provider)
        rows.append((scenario, expected, got, provider, got == expected))

    negative = None
    if not args.skip_negative:
        since = parse_ts(c.request("GET", "/chunks?limit=1")["server_time"])
        c.request("POST", "/demo/simulate", {"scenario": "checkout_success", "sessions": args.sessions})
        print("checkout_success (negative control): waiting through the review window...")
        time.sleep(35)
        touched = [i for i in c.request("GET", "/incidents")["incidents"] if i["journey_stage"] == "checkout" and parse_ts(i["last_seen_at"]) >= since]
        negative = not touched

    print(f"\n{'scenario':<20}{'expected':<24}{'got':<24}{'provider':<12}ok")
    for s, e, g, p, ok in rows:
        print(f"{s:<20}{e:<24}{g:<24}{p:<12}{'yes' if ok else 'NO'}")
    correct = sum(1 for r in rows if r[4])
    print(f"\nDiagnosis accuracy: {correct}/{len(rows)}  (provider: {', '.join(sorted(providers))})")
    if negative is not None:
        print(f"Negative control (healthy checkout opens no incident): {'PASS' if negative else 'FAIL - false positive'}")
    print("Note: three scripted scenarios are a smoke test of the pipeline, not a statistically meaningful accuracy estimate.")
    return 0 if correct == len(rows) and negative is not False else 1


if __name__ == "__main__":
    raise SystemExit(main())
