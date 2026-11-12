"""Pure-engine tests: no database, no network."""
from datetime import datetime, timedelta, timezone

from app.finance_engine import Txn, analyse, forecast_daily, window_metrics

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def tx(days_ago: int, amt: float, kind="payment", status="success", **kw) -> Txn:
    return Txn(ts=NOW - timedelta(days=days_ago, hours=1), txn_type=kind, status=status, amount_minor=round(amt * 100), **kw)


def history(n=30, base=100.0, step=0.0):
    return [tx(d, base + step * (n - d)) for d in range(n)]


def test_window_metrics_core_numbers():
    rows = [tx(0, 100), tx(0, 50), tx(0, 80, status="failed", reason="timeout"), tx(0, 20, "refund"), tx(0, 5, "fee")]
    m = window_metrics(rows)
    assert m["gross_revenue"] == 150 and m["refunds"] == 20 and m["fees"] == 5 and m["net_cashflow"] == 125
    assert m["success_rate"] == 66.7 and m["payments_failed"] == 1 and m["failed_value"] == 80
    assert m["avg_order_value"] == 75 and m["refund_rate"] == 13.3


def test_empty_input_does_not_crash_and_forecast_declines():
    r = analyse([], now=NOW)
    assert r["kpis"]["gross_revenue"] == 0 and r["kpis"]["success_rate"] is None
    assert r["forecast"]["ready"] is False and "7 days" in r["forecast"]["reason"]
    assert r["liquidity"]["runway_days"] is None and r["liquidity"]["self_funding"] is True


def test_cash_position_runway_and_obligations():
    rows = history(14, 100) + [tx(1, 30, "refund")]
    r = analyse(rows, now=NOW, opening_balance=1000, monthly_obligations=6000)
    liq = r["liquidity"]
    assert liq["cash_position"] == 1000 + 1400 - 30
    # burn = 6000/30 - avg daily net (~97.9) = ~102.1/day; cash 2370 -> ~23 days
    assert 22 <= liq["runway_days"] <= 24.5 and liq["self_funding"] is False
    assert liq["health"]["band"] in {"watch", "at_risk"}


def test_self_funding_when_net_exceeds_obligations():
    r = analyse(history(30, 200), now=NOW, monthly_obligations=3000)
    assert r["liquidity"]["self_funding"] is True and r["liquidity"]["runway_days"] is None


def test_payouts_reduce_cash_but_not_revenue():
    rows = history(10, 100) + [tx(2, 500, "payout")]
    r = analyse(rows, now=NOW)
    assert r["kpis"]["gross_revenue"] == 1000 and r["liquidity"]["cash_position"] == 500 and r["liquidity"]["settled_to_owner"] == 500


def test_forecast_follows_a_rising_trend_and_has_a_band():
    f = forecast_daily([100 + 5 * i for i in range(28)], NOW.date())
    assert f["ready"] and len(f["days"]) == 14
    assert f["days"][0]["value"] > 230 and f["days"][-1]["value"] > f["days"][0]["value"]
    assert all(d["low"] <= d["value"] <= d["high"] for d in f["days"])


def test_forecast_respects_weekday_seasonality():
    vals, d0 = [], NOW.date() - timedelta(days=55)
    for i in range(56):
        vals.append(300.0 if (d0 + timedelta(days=i)).weekday() >= 5 else 100.0)
    f = forecast_daily(vals, NOW.date())
    by = {d["date"]: d["value"] for d in f["days"]}
    weekend = [v for k, v in by.items() if datetime.fromisoformat(k).weekday() >= 5]
    weekday = [v for k, v in by.items() if datetime.fromisoformat(k).weekday() < 5]
    assert min(weekend) > 2 * max(weekday)


def test_failure_breakdown_and_insight_on_success_drop():
    prev = [tx(d, 50) for d in range(30, 59) for _ in range(2)]
    cur = [tx(d, 50) for d in range(0, 10)] + [tx(d, 50, status="failed", reason="timeout") for d in range(0, 10)]
    r = analyse(prev + cur, now=NOW, days=30)
    assert r["failure_reasons"][0]["reason"] == "timeout" and r["failure_reasons"][0]["share"] == 100.0
    assert any(i["tone"] == "bad" and "success fell" in i["text"] for i in r["insights"])


def test_other_currencies_are_excluded_not_mixed():
    r = analyse([tx(0, 100), tx(0, 999, currency="EUR")], now=NOW, currency="USD")
    assert r["kpis"]["gross_revenue"] == 100 and r["excluded_other_currency"] == 1


def test_revenue_drop_is_flagged_as_anomaly():
    rows = [tx(d, 100) for d in range(1, 30)] + [tx(0, 100 + (d % 3)) for d in range(1)]
    rows = [t for t in rows if True]
    base = [tx(d, 100 + (d % 3) * 5) for d in range(1, 30)]
    r = analyse(base, now=NOW)  # last day (today) has no revenue at all
    assert any(a["kind"] == "revenue_drop" for a in r["anomalies"])
