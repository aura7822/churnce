from datetime import datetime, timedelta, timezone

from app import liquidity_suite as ls
from app.finance_engine import Txn

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


def mk(days_ago, typ, status, amt, cur="KES", bank="Equity Bank", due=None, reason=None):
    return Txn(ts=NOW - timedelta(days=days_ago, hours=1), txn_type=typ, status=status, amount_minor=int(amt * 100), currency=cur, bank=bank, due_at=due, reason=reason)


def rows():
    r = []
    for d in range(30):
        r += [mk(d, "payment", "success", 5000 + d * 20), mk(d, "payment", "success", 2000, bank="M-Pesa"), mk(d, "fee", "success", 150, bank="M-Pesa")]
        if d % 5 == 0:
            r.append(mk(d, "payment", "failed", 1800, reason="timeout"))
        if d % 9 == 0:
            r.append(mk(d, "refund", "success", 900))
    r += [mk(2, "payment", "success", 100, cur="USD", bank="Stanbic")]
    r += [mk(40, "invoice", "pending", 60000, due=NOW - timedelta(days=5)), mk(10, "invoice", "pending", 40000, due=NOW + timedelta(days=12)), mk(80, "invoice", "success", 50000)]
    r += [mk(20, "bill", "pending", 70000, due=NOW + timedelta(days=9)), mk(60, "bill", "success", 90000)]
    r += [mk(50, "inventory_in", "success", 300000), mk(30, "inventory_out", "success", 60000)]
    return r


def test_banks_currencies_and_fx():
    out = ls.build(rows(), NOW, opening=10000)
    names = {b["bank"] for b in out["banks"]}
    assert {"Equity Bank", "M-Pesa", "Stanbic", "Opening balance"} <= names
    usd = next(c for c in out["currencies"] if c["currency"] == "USD")
    assert usd["fx_rate_to_kes"] == 129.0 and usd["balance_kes"] == 12900.0
    assert abs(sum(b["share_pct"] for b in out["banks"]) - 100) < 0.5


def test_multi_horizon_forecast_is_monotone_and_banded():
    f = ls.build(rows(), NOW)["forecast"]
    assert f["ready"] and [h["days"] for h in f["horizons"]] == [7, 14, 30, 60, 90]
    assert all(h["low"] <= h["closing_cash"] <= h["high"] for h in f["horizons"])
    assert f["horizons"][0]["inflow"] < f["horizons"][-1]["inflow"] and len(f["series"]) == 90


def test_forecast_needs_history():
    out = ls.build([mk(0, "payment", "success", 100)], NOW)
    assert out["forecast"]["ready"] is False and out["stress"] == []


def test_working_capital():
    wc = ls.build(rows(), NOW)["working_capital"]
    assert wc["ar"]["balance"] == 100000.0 and wc["ar"]["overdue"] == 60000.0 and wc["ap"]["balance"] == 70000.0
    assert wc["inventory"]["value"] == 240000.0 and wc["ar"]["dso"] is not None
    assert wc["working_capital"] == 270000.0
    assert any(r["id"] == "collect" and r["cash_release_kes"] >= 60000 for r in wc["recommendations"])


def test_compliance_ratios_and_status():
    c = ls.build(rows(), NOW)["compliance"]
    assert c["current_ratio"]["value"] and c["quick_ratio"]["value"] <= c["current_ratio"]["value"]
    assert c["lcr"]["threshold"] == 1.0 and c["lcr"]["status"] in ("pass", "warn", "fail")


def test_stress_scenarios_ordering():
    s = {x["id"]: x for x in ls.build(rows(), NOW)["stress"]}
    assert set(s) == {"rev20", "rev40", "fail", "collect", "fx", "refund", "severe"}
    assert s["severe"]["min_cash"] <= s["rev40"]["min_cash"] <= s["rev20"]["min_cash"]
    assert all(x["verdict"] in ("pass", "warn", "fail") for x in s.values())


def test_sweeps_target_zero_and_threshold():
    banks = [{"bank": "A", "balance_kes": 100000.0}, {"bank": "B", "balance_kes": 5000.0}, {"bank": "H", "balance_kes": 0.0}]
    rules = [
        {"id": "r1", "enabled": True, "kind": "target_balance", "source_bank": "A", "dest_bank": "H", "target_kes": 30000},
        {"id": "r2", "enabled": True, "kind": "zero_balance", "source_bank": "B", "dest_bank": "H"},
        {"id": "r3", "enabled": False, "kind": "zero_balance", "source_bank": "H", "dest_bank": "A"},
        {"id": "r4", "enabled": True, "kind": "threshold", "source_bank": "H", "dest_bank": "A", "threshold_kes": 200000, "target_kes": 0},
    ]
    p = ls.proposals(banks, rules)
    assert [(x["rule_id"], x["amount_kes"]) for x in p] == [("r1", 70000.0), ("r2", 5000.0)]  # r4 not triggered, r3 disabled


def test_sweep_adjustments_move_positions():
    out = ls.build(rows(), NOW, adj={"Equity Bank": -1000.0, "M-Pesa": 1000.0})
    base = ls.build(rows(), NOW)
    d = {b["bank"]: b["balance_kes"] for b in out["banks"]}
    b0 = {b["bank"]: b["balance_kes"] for b in base["banks"]}
    assert round(d["Equity Bank"] - b0["Equity Bank"], 2) == -1000.0 and round(d["M-Pesa"] - b0["M-Pesa"], 2) == 1000.0
