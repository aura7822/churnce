"""Weekly report: one plain-language summary of everything captured in the last seven days, what needs doing, and what to do about it.
Pure functions over already-loaded rows and facts, so it is deterministic and unit-tested without a database."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from .finance_engine import Txn

IN_TYPES = {"payment", "subscription", "invoice_paid"}
OUT_TYPES = {"refund", "chargeback", "fee", "payout", "bill_paid"}


def _kes(minor: float) -> float:
    return round(minor / 100.0, 2)


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"KES {x:,.0f}"


def _window(rows: list[Txn], a: datetime, b: datetime) -> dict[str, Any]:
    inflow = out = failed_amt = refunds = chargebacks = fees = 0.0
    ok = failed = pending = 0
    reasons: Counter[str] = Counter()
    by_site: dict[str, float] = defaultdict(float)
    for t in rows:
        if not (a <= t.ts < b):
            continue
        amt = _kes(t.amount_minor)
        if t.status == "failed":
            failed += 1
            failed_amt += amt
            reasons[(t.reason or "unspecified")[:40]] += 1
        elif t.status == "pending":
            pending += 1
        elif t.status == "success":
            ok += 1
            if t.txn_type in IN_TYPES:
                inflow += amt
                by_site[t.site_host or "-"] += amt
            elif t.txn_type in OUT_TYPES:
                out += amt
                if t.txn_type == "refund":
                    refunds += amt
                elif t.txn_type == "chargeback":
                    chargebacks += amt
                elif t.txn_type == "fee":
                    fees += amt
    attempts = ok + failed
    return {"inflow": round(inflow, 2), "outflow": round(out, 2), "net": round(inflow - out, 2), "failed": failed, "failed_amount": round(failed_amt, 2), "succeeded": ok, "pending": pending,
            "failure_rate_pct": round(100.0 * failed / attempts, 1) if attempts else 0.0, "refunds": round(refunds, 2), "chargebacks": round(chargebacks, 2), "fees": round(fees, 2),
            "top_failure_reasons": [{"reason": r, "count": c} for r, c in reasons.most_common(3)],
            "top_sites": [{"site": s, "inflow": round(v, 2)} for s, v in sorted(by_site.items(), key=lambda kv: -kv[1])[:5]]}


def _delta(cur: float, prev: float) -> float | None:
    return None if not prev else round(100.0 * (cur - prev) / abs(prev), 1)


def build(rows: list[Txn], facts: dict[str, Any], metrics: dict[str, Any], now: datetime) -> dict[str, Any]:
    """`rows` are in KES minor units. `facts` is finance._facts(); `metrics` is feedback.dashboard_metrics()."""
    start = now - timedelta(days=7)
    prev_start = start - timedelta(days=7)
    wk, pw = _window(rows, start, now), _window(rows, prev_start, start)
    comp, wc = facts["compliance"], facts["working_capital"]
    h7 = next((h for h in facts["forecast"] if h["days"] == 7), None)
    h30 = next((h for h in facts["forecast"] if h["days"] == 30), None)

    # what needs doing, most urgent first
    actions: list[dict[str, str]] = []
    adv: list[dict[str, str]] = []

    def need(priority: str, title: str, detail: str, owner: str) -> None:
        actions.append({"priority": priority, "title": title, "detail": detail, "owner": owner})

    if wk["failure_rate_pct"] >= 8 and wk["failed"] >= 3:
        top = wk["top_failure_reasons"][0]["reason"] if wk["top_failure_reasons"] else "unspecified"
        need("high", "Investigate failed payments", f"{wk['failed']} payments failed ({wk['failure_rate_pct']}%), worth {_fmt(wk['failed_amount'])}. Most common reason: {top}.", "Developer")
    if h30 and h30["net"] < 0:
        need("high", "Close the 30-day cash gap", f"Forecast net cash over 30 days is {_fmt(h30['net'])}; low case closing cash {_fmt(h30['low'])}.", "Website Owner")
    if comp.get("lcr_status") not in (None, "pass"):
        need("high", "Raise liquidity coverage", f"LCR is {comp['lcr']} (status {comp['lcr_status']}). Move cash into same-day-access accounts.", "Website Owner")
    if any(r["verdict"] == "fail" for r in facts.get("stress", [])):
        names = ", ".join(r["scenario"] for r in facts["stress"] if r["verdict"] == "fail")
        need("high", "Prepare for failed stress tests", f"Failed: {names}. Arrange a standby credit line or buffer.", "Website Owner")
    if (metrics.get("actions_awaiting_approval") or 0) > 0:
        need("medium", "Approve pending actions", f"{metrics['actions_awaiting_approval']} action(s) are waiting for approval.", "Website Owner")
    if (metrics.get("chunks_pending_review") or 0) > 0:
        need("medium", "Review captured evidence", f"{metrics['chunks_pending_review']} chunk(s) are in the review gate.", "Data Analyst")
    if (metrics.get("emails_draft") or 0) > 0:
        need("medium", "Edit and send win-back emails", f"{metrics['emails_draft']} draft email(s) are ready for review.", "Website Owner")
    if (metrics.get("incidents_active") or 0) > 0:
        need("medium", "Work through active incidents", f"{metrics['incidents_active']} incident(s) are open.", "Developer")
    if wk["chargebacks"] > 0:
        need("medium", "Respond to chargebacks", f"{_fmt(wk['chargebacks'])} charged back this week.", "Website Owner")
    if not actions:
        need("low", "No urgent actions", "Nothing needs attention this week. Keep capture running.", "Everyone")
    order = {"high": 0, "medium": 1, "low": 2}
    actions.sort(key=lambda a: order[a["priority"]])

    for r in wc.get("recommendations", [])[:3]:
        if r.get("cash_release_kes", 0) > 0:
            adv.append({"title": r["title"], "detail": f"Could release about {_fmt(r['cash_release_kes'])} of cash."})
    if wk["failure_rate_pct"] > pw["failure_rate_pct"] + 2:
        adv.append({"title": "Failure rate is rising", "detail": f"{wk['failure_rate_pct']}% this week against {pw['failure_rate_pct']}% last week. Check the payment provider and recent releases."})
    if facts["pooling"]["idle_cash"] > 0:
        adv.append({"title": "Put idle cash to work", "detail": f"About {_fmt(facts['pooling']['idle_cash'])} sits idle across accounts. Review the sweep proposals."})
    if wk["refunds"] > 0.05 * max(wk["inflow"], 1):
        adv.append({"title": "Refunds are above 5% of inflow", "detail": "Look at the products or journeys behind refund requests before the next billing cycle."})
    if not adv:
        adv.append({"title": "Stay the course", "detail": "Cash, ratios and failures look healthy. Review again next week."})

    net_word = "positive" if wk["net"] >= 0 else "negative"
    headline = f"Net cash flow was {net_word} at {_fmt(wk['net'])}: inflow {_fmt(wk['inflow'])}, outflow {_fmt(wk['outflow'])}. {len(actions)} item(s) need attention."
    return {
        "period": {"from": start.isoformat(), "to": now.isoformat(), "days": 7}, "currency": "KES", "headline": headline,
        "week": wk, "previous_week": pw,
        "change_pct": {"inflow": _delta(wk["inflow"], pw["inflow"]), "failed": _delta(wk["failed"], pw["failed"]), "net": _delta(wk["net"], pw["net"])},
        "cash": {"total": facts["cash_total"], "banks": facts["banks"][:5], "forecast_7": h7, "forecast_30": h30},
        "ratios": comp, "working_capital": {k: wc[k] for k in ("ar", "ap", "inventory", "ccc_days", "net")},
        "captured": {"events_total": metrics.get("events_total", 0), "events_last_hour": metrics.get("events_last_hour", 0), "chunks_indexed": metrics.get("chunks_indexed", 0),
                     "incidents_active": metrics.get("incidents_active", 0), "emails_draft": metrics.get("emails_draft", 0), "emails_approved": metrics.get("emails_approved", 0),
                     "actions_awaiting_approval": metrics.get("actions_awaiting_approval", 0), "actions_completed": metrics.get("actions_completed", 0)},
        "required_actions": actions, "advice": adv,
    }
