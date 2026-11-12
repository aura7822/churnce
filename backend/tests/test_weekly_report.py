from datetime import datetime, timedelta, timezone

from app import weekly_report as wr
from app.finance_engine import Txn

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def t(days, typ, status, amt, reason=None, site="shop.test"):
    return Txn(ts=NOW - timedelta(days=days, hours=2), txn_type=typ, status=status, amount_minor=int(amt * 100), currency="KES", reason=reason, site_host=site)


FACTS = {"cash_total": 900000, "banks": [{"bank": "Equity", "balance_kes": 900000, "share_pct": 100}], "forecast": [{"days": 7, "net": 5000, "closing_cash": 905000, "low": 800000}, {"days": 30, "net": -20000, "closing_cash": 880000, "low": 700000}],
         "stress": [{"scenario": "Revenue -30%", "verdict": "fail", "min_cash": 1, "runway_days": 10}], "compliance": {"current_ratio": 1.4, "quick_ratio": 1.1, "lcr": 0.8, "lcr_status": "fail", "current_status": "pass", "quick_status": "pass"},
         "working_capital": {"ar": {}, "ap": {}, "inventory": {}, "ccc_days": 20, "net": 1000, "recommendations": [{"title": "Collect overdue invoices", "cash_release_kes": 40000}]}, "pooling": {"idle_cash": 30000, "proposals": []}}


def test_week_totals_and_actions():
    rows = [t(1, "payment", "success", 1000), t(2, "payment", "success", 2000), t(2, "refund", "success", 500)] + [t(1, "payment", "failed", 300, "timeout") for _ in range(4)] + [t(9, "payment", "success", 1500)]
    r = wr.build(rows, FACTS, {"actions_awaiting_approval": 2, "chunks_pending_review": 1, "emails_draft": 3, "incidents_active": 1}, NOW)
    w = r["week"]
    assert w["inflow"] == 3000 and w["outflow"] == 500 and w["net"] == 2500 and w["failed"] == 4
    assert r["previous_week"]["inflow"] == 1500 and r["change_pct"]["inflow"] == 100.0
    assert w["top_failure_reasons"][0] == {"reason": "timeout", "count": 4}
    titles = [a["title"] for a in r["required_actions"]]
    assert r["required_actions"][0]["priority"] == "high" and "Investigate failed payments" in titles and "Raise liquidity coverage" in titles and "Approve pending actions" in titles
    assert r["advice"] and "KES" in r["headline"]


def test_quiet_week_has_a_calm_message():
    calm = {**FACTS, "forecast": [{"days": 30, "net": 100, "closing_cash": 1, "low": 1}], "stress": [], "compliance": {**FACTS["compliance"], "lcr_status": "pass", "lcr": 2}, "pooling": {"idle_cash": 0, "proposals": []}, "working_capital": {**FACTS["working_capital"], "recommendations": []}}
    r = wr.build([t(1, "payment", "success", 100)], calm, {}, NOW)
    assert [a["title"] for a in r["required_actions"]] == ["No urgent actions"] and r["advice"][0]["title"] == "Stay the course"
