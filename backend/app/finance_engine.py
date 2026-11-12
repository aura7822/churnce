"""Financial cashflow and liquidity analytics. Pure Python (stdlib only) so it is fast to test and has no I/O.

Inputs are normalised transactions; outputs are JSON-ready dicts. All money crossing the API is in major units (e.g. 12.50),
all money inside the engine is integer minor units (1250) to avoid float drift.

Definitions
  inflow            successful `payment` + `subscription`
  outflow           successful `refund` + `chargeback` + `fee`           (payouts are settlements, tracked separately)
  net cashflow      inflow - outflow
  cash position     opening balance + net cashflow over all captured history - payouts (money moved out to the owner's bank is
                    not "lost", but it is no longer working capital, so the engine reports both `cash_position` and `settled`)
  success rate      successful payments / (successful + failed payments)
  runway (days)     cash position / daily operating burn, where burn = daily obligations - average daily net cashflow (if > 0)
  coverage ratio    (cash + projected 30-day inflow) / (monthly obligations + projected 30-day outflow)
  health score      0-100, see `_health`
Forecast: ordinary-least-squares trend over recent daily inflow, multiplied by shrunken weekday seasonality; the band is
+/- 1.28 residual standard deviations (about an 80% interval). It needs at least 7 days of history and says so when it does not.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

INFLOW_TYPES = {"payment", "subscription"}
OUTFLOW_TYPES = {"refund", "chargeback", "fee"}
TXN_TYPES = INFLOW_TYPES | OUTFLOW_TYPES | {"payout"}
STATUSES = {"success", "failed", "pending"}
METHODS = {"card", "mobile_money", "bank_transfer", "wallet", "cash_on_delivery", "other"}
MIN_FORECAST_DAYS = 7
HORIZON = 14


@dataclass(frozen=True)
class Txn:
    ts: datetime
    txn_type: str
    status: str
    amount_minor: int
    currency: str = "USD"
    method: str | None = None
    reason: str | None = None
    site_host: str = ""
    id: str = ""
    simulated: bool = False
    bank: str = ""
    due_at: datetime | None = None


def major(minor: float) -> float:
    return round(minor / 100.0, 2)


def _day(ts: datetime) -> date:
    return (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).date()


def _ok(t: Txn) -> bool:
    return t.status == "success"


def _pct(n: float, d: float) -> float | None:
    return round(100.0 * n / d, 1) if d else None


def _sum(rows: list[Txn], types: set[str]) -> int:
    return sum(t.amount_minor for t in rows if _ok(t) and t.txn_type in types)


# ───────────────────────── core metrics for one window ─────────────────────────
def window_metrics(rows: list[Txn]) -> dict[str, Any]:
    pays = [t for t in rows if t.txn_type in INFLOW_TYPES]
    good = [t for t in pays if _ok(t)]
    failed = [t for t in pays if t.status == "failed"]
    pending = [t for t in pays if t.status == "pending"]
    gross = _sum(rows, INFLOW_TYPES)
    refunds = _sum(rows, {"refund"})
    chargebacks = _sum(rows, {"chargeback"})
    fees = _sum(rows, {"fee"})
    payouts = _sum(rows, {"payout"})
    outflow = refunds + chargebacks + fees
    attempts = len(good) + len(failed)
    return {
        "transactions": len(rows), "payments_succeeded": len(good), "payments_failed": len(failed), "payments_pending": len(pending),
        "gross_revenue": major(gross), "refunds": major(refunds), "chargebacks": major(chargebacks), "fees": major(fees),
        "payouts": major(payouts), "outflow": major(outflow), "net_cashflow": major(gross - outflow),
        "success_rate": _pct(len(good), attempts),
        "avg_order_value": major(gross / len(good)) if good else None,
        "refund_rate": _pct(refunds, gross), "chargeback_rate": _pct(sum(1 for t in rows if _ok(t) and t.txn_type == "chargeback"), len(good)),
        "failed_value": major(sum(t.amount_minor for t in failed)), "pending_value": major(sum(t.amount_minor for t in pending)),
    }


def daily_series(rows: list[Txn], start: date, end: date) -> dict[str, list[Any]]:
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    idx = {d: i for i, d in enumerate(days)}
    inflow, outflow, failed_value, count, failed_count = ([0] * len(days) for _ in range(5))
    for t in rows:
        i = idx.get(_day(t.ts))
        if i is None:
            continue
        count[i] += 1
        if _ok(t) and t.txn_type in INFLOW_TYPES:
            inflow[i] += t.amount_minor
        elif _ok(t) and t.txn_type in OUTFLOW_TYPES:
            outflow[i] += t.amount_minor
        elif t.status == "failed" and t.txn_type in INFLOW_TYPES:
            failed_value[i] += t.amount_minor
            failed_count[i] += 1
    return {
        "dates": [d.isoformat() for d in days], "inflow": [major(x) for x in inflow], "outflow": [major(x) for x in outflow],
        "net": [major(a - b) for a, b in zip(inflow, outflow)], "failed_value": [major(x) for x in failed_value],
        "failed_count": failed_count, "count": count, "_inflow_minor": inflow, "_outflow_minor": outflow,
    }


# ───────────────────────── forecasting ─────────────────────────
def _ols(ys: list[float]) -> tuple[float, float]:
    n = len(ys)
    xs = list(range(n))
    mx, my = (n - 1) / 2, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    return my - slope * mx, slope


def forecast_daily(values: list[float], last_day: date, horizon: int = HORIZON) -> dict[str, Any]:
    """Trend x weekday seasonality with an ~80% band. `values` are daily totals ending on `last_day`."""
    ys = values[-56:]
    n = len(ys)
    if n < MIN_FORECAST_DAYS or sum(ys) <= 0:
        return {"ready": False, "reason": f"Needs at least {MIN_FORECAST_DAYS} days of captured revenue (have {sum(1 for v in ys if v > 0)}).", "days": []}
    a, b = _ols(ys)
    first = last_day - timedelta(days=n - 1)
    mean = sum(ys) / n
    by_wd: dict[int, list[float]] = defaultdict(list)
    for i, y in enumerate(ys):  # detrended ratio, so a rising or falling trend is not mistaken for a weekday effect
        t = a + b * i
        by_wd[(first + timedelta(days=i)).weekday()].append(y / t if t > mean * 0.05 else 1.0)
    season = {}
    for wd, vs in by_wd.items():
        raw = sum(vs) / len(vs)
        w = min(1.0, (len(vs) - 1) / 3.0) if len(vs) > 1 else 0.0  # shrink toward 1 when a weekday has few samples
        season[wd] = 1.0 + w * (raw - 1.0)
    fitted = [max(0.0, (a + b * i) * season.get((first + timedelta(days=i)).weekday(), 1.0)) for i in range(n)]
    resid = [y - f for y, f in zip(ys, fitted)]
    sigma = statistics.pstdev(resid) if n > 2 else 0.0
    out = []
    for h in range(1, horizon + 1):
        d = last_day + timedelta(days=h)
        mid = max(0.0, (a + b * (n - 1 + h)) * season.get(d.weekday(), 1.0))
        out.append({"date": d.isoformat(), "value": round(mid, 2), "low": round(max(0.0, mid - 1.28 * sigma), 2), "high": round(mid + 1.28 * sigma, 2)})
    return {"ready": True, "days": out, "trend_per_day": round(b, 2), "sigma": round(sigma, 2), "history_days": n}


# ───────────────────────── anomalies ─────────────────────────
def anomalies(dates: list[str], inflow: list[float], failed_count: list[int], count: list[int]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(len(inflow)):
        base = inflow[max(0, i - 14):i]
        if len(base) < 7:
            continue
        mu, sd = statistics.mean(base), statistics.pstdev(base)
        if sd <= 0:
            continue
        z = (inflow[i] - mu) / sd
        if abs(z) >= 2.5:
            out.append({"date": dates[i], "kind": "revenue_spike" if z > 0 else "revenue_drop", "value": inflow[i], "expected": round(mu, 2), "z": round(z, 1)})
    for i in range(len(count)):
        tot = count[i]
        if tot >= 10 and failed_count[i] / tot >= 0.25:
            out.append({"date": dates[i], "kind": "failure_spike", "value": failed_count[i], "expected": None, "z": None})
    return sorted(out, key=lambda a: a["date"], reverse=True)[:8]


# ───────────────────────── liquidity ─────────────────────────
def _health(runway: float | None, coverage: float | None, success: float | None, refund_rate: float | None) -> dict[str, Any]:
    """Weighted score: runway 40, coverage 30, payment success 20, refund pressure 10. Missing inputs are excluded and the rest rescaled."""
    parts: list[tuple[float, float]] = []
    parts.append((40, 1.0 if runway is None else max(0.0, min(1.0, runway / 90.0))))
    if coverage is not None:
        parts.append((30, max(0.0, min(1.0, coverage / 1.5))))
    if success is not None:
        parts.append((20, max(0.0, min(1.0, (success - 70) / 25))))
    if refund_rate is not None:
        parts.append((10, max(0.0, min(1.0, 1 - refund_rate / 15))))
    total = sum(w for w, _ in parts)
    score = round(100 * sum(w * v for w, v in parts) / total) if total else 0
    return {"score": score, "band": "healthy" if score >= 75 else "watch" if score >= 50 else "at_risk"}


def analyse(rows: list[Txn], *, now: datetime, days: int = 30, currency: str = "USD", opening_balance: float = 0.0, monthly_obligations: float = 0.0) -> dict[str, Any]:
    """Everything the finance dashboard shows, from one list of transactions (ideally the last ~400 days)."""
    other = [t for t in rows if t.currency != currency]
    rows = [t for t in rows if t.currency == currency]
    end = _day(now)
    start = end - timedelta(days=days - 1)
    prev_start = start - timedelta(days=days)
    cur = [t for t in rows if start <= _day(t.ts) <= end]
    prev = [t for t in rows if prev_start <= _day(t.ts) < start]
    m, pm = window_metrics(cur), window_metrics(prev)

    series = daily_series(rows, start, end)
    hist_start = end - timedelta(days=55)
    hist = daily_series(rows, hist_start, end)
    fc_in = forecast_daily(hist["inflow"], end)
    fc_out = forecast_daily(hist["outflow"], end) if sum(hist["outflow"]) > 0 else {"ready": fc_in["ready"], "days": [{"date": d["date"], "value": 0.0, "low": 0.0, "high": 0.0} for d in fc_in.get("days", [])]}

    # cash position over everything captured
    all_in, all_out, all_payout = _sum(rows, INFLOW_TYPES), _sum(rows, OUTFLOW_TYPES), _sum(rows, {"payout"})
    opening = round(opening_balance * 100)
    cash = opening + all_in - all_out - all_payout
    recent = daily_series(rows, end - timedelta(days=13), end)
    avg_net = sum(recent["_inflow_minor"]) / 14 - sum(recent["_outflow_minor"]) / 14
    daily_obl = round(monthly_obligations * 100) / 30.0
    burn = daily_obl - avg_net
    runway = round(cash / burn, 1) if burn > 0 and cash > 0 else (0.0 if burn > 0 else None)
    proj_in = sum(d["value"] for d in fc_in.get("days", [])) / max(1, len(fc_in.get("days", []))) * 30 if fc_in["ready"] else None
    proj_out = sum(d["value"] for d in fc_out.get("days", [])) / max(1, len(fc_out.get("days", []))) * 30 if fc_out["ready"] else None
    coverage = None
    if proj_in is not None and proj_out is not None:
        denom = monthly_obligations + proj_out
        coverage = round((major(cash) + proj_in) / denom, 2) if denom > 0 else None
    health = _health(runway, coverage, m["success_rate"], m["refund_rate"])

    forecast_days = []
    for i, d in enumerate(fc_in.get("days", [])):
        o = fc_out["days"][i]["value"] if i < len(fc_out.get("days", [])) else 0.0
        forecast_days.append({**d, "outflow": o, "net": round(d["value"] - o, 2)})
    f7 = round(sum(d["value"] for d in forecast_days[:7]), 2)
    f14 = round(sum(d["value"] for d in forecast_days), 2)

    # breakdowns
    reasons: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "value": 0})
    methods: dict[str, dict[str, int]] = defaultdict(lambda: {"ok": 0, "failed": 0, "value": 0})
    sites: dict[str, dict[str, int]] = defaultdict(lambda: {"gross": 0, "refunds": 0, "ok": 0, "failed": 0, "failed_value": 0})
    for t in cur:
        if t.txn_type in INFLOW_TYPES:
            s = sites[t.site_host or "unknown"]
            k = methods[t.method or "other"]
            if _ok(t):
                s["gross"] += t.amount_minor; s["ok"] += 1; k["ok"] += 1; k["value"] += t.amount_minor
            elif t.status == "failed":
                s["failed"] += 1; s["failed_value"] += t.amount_minor; k["failed"] += 1
                r = reasons[t.reason or "unspecified"]
                r["count"] += 1; r["value"] += t.amount_minor
        elif t.txn_type == "refund" and _ok(t):
            sites[t.site_host or "unknown"]["refunds"] += t.amount_minor
    nfail = sum(v["count"] for v in reasons.values())
    reason_rows = sorted(({"reason": k, "count": v["count"], "value": major(v["value"]), "share": _pct(v["count"], nfail)} for k, v in reasons.items()), key=lambda r: -r["count"])
    method_rows = sorted(({"method": k, "succeeded": v["ok"], "failed": v["failed"], "value": major(v["value"]), "success_rate": _pct(v["ok"], v["ok"] + v["failed"])} for k, v in methods.items()), key=lambda r: -r["value"])
    site_rows = sorted(({"host": k, "gross": major(v["gross"]), "refunds": major(v["refunds"]), "net": major(v["gross"] - v["refunds"]), "succeeded": v["ok"], "failed": v["failed"], "failed_value": major(v["failed_value"]), "success_rate": _pct(v["ok"], v["ok"] + v["failed"])} for k, v in sites.items()), key=lambda r: -r["gross"])

    def delta(a: float | None, b: float | None) -> float | None:
        return None if a is None or b is None or b == 0 else round(100.0 * (a - b) / abs(b), 1)

    deltas = {"gross_revenue": delta(m["gross_revenue"], pm["gross_revenue"]), "net_cashflow": delta(m["net_cashflow"], pm["net_cashflow"]),
              "failed": delta(m["payments_failed"], pm["payments_failed"]),
              "success_rate_pts": None if m["success_rate"] is None or pm["success_rate"] is None else round(m["success_rate"] - pm["success_rate"], 1)}
    return {
        "currency": currency, "days": days, "generated_at": now.astimezone(timezone.utc).isoformat(), "captured": len(rows), "excluded_other_currency": len(other),
        "kpis": m, "previous": pm, "deltas": deltas,
        "series": {k: v for k, v in series.items() if not k.startswith("_")},
        "liquidity": {"cash_position": major(cash), "opening_balance": round(opening_balance, 2), "monthly_obligations": round(monthly_obligations, 2),
                      "avg_daily_net": major(avg_net), "runway_days": runway, "self_funding": burn <= 0, "coverage_ratio": coverage,
                      "settled_to_owner": major(all_payout), "health": health},
        "forecast": {"ready": fc_in["ready"], "reason": fc_in.get("reason"), "horizon_days": HORIZON, "days": forecast_days,
                     "next_7_days_income": f7 if fc_in["ready"] else None, "next_14_days_income": f14 if fc_in["ready"] else None,
                     "trend_per_day": fc_in.get("trend_per_day"), "band": "about 80% interval"},
        "failure_reasons": reason_rows, "methods": method_rows, "sites": site_rows,
        "anomalies": anomalies(hist["dates"], hist["inflow"], hist["failed_count"], hist["count"]),
        "insights": _insights(m, deltas, reason_rows, runway, coverage, fc_in["ready"], f7),
    }


def _insights(m: dict[str, Any], d: dict[str, Any], reasons: list[dict[str, Any]], runway: float | None, coverage: float | None, fc_ready: bool, f7: float) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    sr = m["success_rate"]
    if sr is not None and d["success_rate_pts"] is not None and d["success_rate_pts"] <= -3:
        top = f" The leading cause is {reasons[0]['reason']} ({reasons[0]['share']}% of failures)." if reasons else ""
        out.append({"tone": "bad", "text": f"Payment success fell {abs(d['success_rate_pts'])} points to {sr}% versus the previous period.{top}"})
    elif sr is not None and sr < 90:
        out.append({"tone": "warn", "text": f"Payment success is {sr}%. Each failed attempt is revenue at risk: {m['failed_value']:.2f} this period."})
    if d["gross_revenue"] is not None and abs(d["gross_revenue"]) >= 10:
        out.append({"tone": "good" if d["gross_revenue"] > 0 else "warn", "text": f"Gross revenue is {'up' if d['gross_revenue'] > 0 else 'down'} {abs(d['gross_revenue'])}% on the previous period."})
    if m["refund_rate"] is not None and m["refund_rate"] > 8:
        out.append({"tone": "warn", "text": f"Refunds are {m['refund_rate']}% of gross revenue, which is high. Check product or fulfilment issues."})
    if runway is not None and runway < 45:
        out.append({"tone": "bad" if runway < 21 else "warn", "text": f"At the current pace the cash position covers about {runway:.0f} days of obligations."})
    if coverage is not None and coverage < 1:
        out.append({"tone": "bad", "text": f"Projected 30-day inflows do not cover obligations (coverage {coverage}x)."})
    if fc_ready:
        out.append({"tone": "info", "text": f"Expected income over the next 7 days: {f7:.2f}."})
    if not out:
        out.append({"tone": "info", "text": "Not enough captured activity yet to draw conclusions. Insights appear as transactions arrive."})
    return out
