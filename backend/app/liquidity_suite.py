"""Liquidity suite: multi-bank and multi-currency cash positions, multi-horizon forecast, stress tests, working capital,
cash pooling and sweeping, and liquidity compliance ratios. Pure Python (stdlib only); every money value in and out is KES (major units).

Input rows are `finance_engine.Txn` with NATIVE currency amounts (minor units); they are converted here with `fx`.
Transaction semantics
  cash in   payment | subscription (success) and invoice (success = collected)
  cash out  refund | chargeback | fee | payout | bill (success = paid supplier)
  AR        invoice with status pending (outstanding); overdue when `due_at` has passed, or older than 30 days when no due date
  AP        bill with status pending; overdue by the same rule
  stock     inventory_in minus inventory_out (valuation movements, not cash: purchases are paid through bills)
Ratios (indicative, management-accounts basis, not a regulatory filing)
  current ratio   (cash + AR + stock) / current liabilities, liabilities = AP + 30-day refund/chargeback/fee run-rate + monthly obligations
  quick ratio     (cash + AR) / current liabilities
  LCR             high-quality liquid assets / net 30-day outflows, HQLA = KES cash at 100% + foreign cash at 85%,
                  net outflows = outflows - min(inflows, 75% of outflows)  (the Basel III inflow cap)"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import fx
from .finance_engine import Txn

CASH_IN = {"payment", "subscription"}
CASH_OUT = {"refund", "chargeback", "fee", "payout"}
HORIZONS = (7, 14, 30, 60, 90)
DEFAULT_BANK = "Primary account"


def _k(t: Txn) -> float:
    """Transaction amount in KES major units."""
    return fx.to_kes_minor(t.amount_minor, t.currency) / 100.0


def _day(ts: datetime) -> date:
    return (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).date()


def _utc(ts: datetime | None) -> datetime | None:
    return None if ts is None else (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc))


def _bank(t: Txn) -> str:
    return (t.bank or "").strip() or DEFAULT_BANK


def _signed(t: Txn) -> float:
    """Settled cash effect of one transaction in KES (0 when it does not move cash)."""
    if t.status != "success":
        return 0.0
    if t.txn_type in CASH_IN or t.txn_type == "invoice":
        return _k(t)
    if t.txn_type in CASH_OUT or t.txn_type == "bill":
        return -_k(t)
    return 0.0


def _r(x: float) -> float:
    return round(x, 2)


def _overdue(t: Txn, now: datetime) -> bool:
    due = _utc(t.due_at)
    return (due < now) if due else (now - _utc(t.ts) > timedelta(days=30))


# ───────────────────────── positions ─────────────────────────
def positions(rows: list[Txn], now: datetime, opening: float, adj: dict[str, float]) -> tuple[list[dict], list[dict], float]:
    native: dict[tuple[str, str], float] = defaultdict(float)
    kes: dict[str, float] = defaultdict(float)
    inflow30: dict[str, float] = defaultdict(float)
    outflow30: dict[str, float] = defaultdict(float)
    cutoff = now - timedelta(days=30)
    for t in rows:
        v = _signed(t)
        if not v:
            continue
        b = _bank(t)
        kes[b] += v
        native[(b, t.currency.upper())] += (t.amount_minor / 100.0) * (1 if v > 0 else -1)
        if t.ts >= cutoff:
            (inflow30 if v > 0 else outflow30)[b] += abs(v)
    for b, d in adj.items():
        kes[b] += d
    if opening:
        kes["Opening balance"] += opening
    total = sum(kes.values())
    banks = []
    for b, bal in sorted(kes.items(), key=lambda x: -x[1]):
        cur = [(c, n) for (bb, c), n in native.items() if bb == b]
        main = max(cur, key=lambda x: abs(x[1]))[0] if cur else "KES"
        banks.append({"bank": b, "currency": main if len(cur) <= 1 else "MIXED", "native_balance": _r(sum(n for _, n in cur) if len(cur) == 1 else bal), "balance_kes": _r(bal),
                      "inflow_kes_30d": _r(inflow30[b]), "outflow_kes_30d": _r(outflow30[b]), "share_pct": _r(100 * bal / total) if total > 0 else 0.0})
    per_cur: dict[str, float] = defaultdict(float)
    for (b, c), n in native.items():
        per_cur[c] += n
    currencies = [{"currency": c, "balance_native": _r(n), "balance_kes": _r(n * fx.rate(c)), "fx_rate_to_kes": fx.rate(c)} for c, n in sorted(per_cur.items(), key=lambda x: -abs(x[1] * fx.rate(x[0])))]
    return banks, currencies, total


# ───────────────────────── daily series and forecast ─────────────────────────
def _daily(rows: list[Txn], now: datetime, days: int = 30) -> tuple[list[float], list[float]]:
    start = _day(now) - timedelta(days=days - 1)
    inn, out = [0.0] * days, [0.0] * days
    for t in rows:
        v = _signed(t)
        if not v or t.txn_type in ("invoice", "bill"):
            continue  # AR/AP settle on their own schedule in the forecast
        i = (_day(t.ts) - start).days
        if 0 <= i < days:
            (inn if v > 0 else out)[i] += abs(v)
    return inn, out


def _weekday_factors(series: list[float], now: datetime) -> list[float]:
    start = _day(now) - timedelta(days=len(series) - 1)
    buckets: dict[int, list[float]] = defaultdict(list)
    for i, v in enumerate(series):
        buckets[(start + timedelta(days=i)).weekday()].append(v)
    mean = statistics.fmean(series) or 1.0
    return [0.5 + 0.5 * (statistics.fmean(buckets[d]) / mean if buckets[d] and mean else 1.0) for d in range(7)]  # shrunk 50% toward flat


def _scheduled(rows: list[Txn], now: datetime) -> tuple[dict[int, float], dict[int, float]]:
    """AR collections (85% likely) and AP payments by day offset (1..90). Overdue items spread over the next 14 days."""
    ar: dict[int, float] = defaultdict(float)
    ap: dict[int, float] = defaultdict(float)
    for t in rows:
        if t.status != "pending" or t.txn_type not in ("invoice", "bill"):
            continue
        amt = _k(t) * (0.85 if t.txn_type == "invoice" else 1.0)
        tgt = ar if t.txn_type == "invoice" else ap
        due = _utc(t.due_at) or (_utc(t.ts) + timedelta(days=30))
        off = (due.date() - now.date()).days
        if off <= 0:
            for d in range(1, 15):
                tgt[d] += amt / 14
        elif off <= 90:
            tgt[off] += amt
    return ar, ap


def forecast(rows: list[Txn], now: datetime, cash0: float, monthly_obligations: float) -> dict[str, Any]:
    inn, out = _daily(rows, now, 30)
    active = sum(1 for a, b in zip(inn, out) if a or b)
    if active < 3:
        return {"ready": False, "horizons": [], "series": [], "_inflow": [], "_outflow": [], "_sigma": 0.0}
    li, lo = inn[-14:], out[-14:]
    level_i, level_o = statistics.fmean(li), statistics.fmean(lo)
    n = len(li)
    xs = list(range(n))
    xm = statistics.fmean(xs)
    slope_i = sum((x - xm) * (y - level_i) for x, y in zip(xs, li)) / (sum((x - xm) ** 2 for x in xs) or 1)
    fi, fo = _weekday_factors(inn, now), _weekday_factors(out, now)
    ar, ap = _scheduled(rows, now)
    obligations = monthly_obligations / 30.0
    nets = [a - b for a, b in zip(inn, out)]
    sigma = statistics.pstdev(nets) if len(nets) > 1 else 0.0
    series, cash, cum_in, cum_out = [], cash0, 0.0, 0.0
    inflows, outflows = [], []
    for h in range(1, 91):
        d = _day(now) + timedelta(days=h)
        trend = level_i + slope_i * (n / 2 + 0.9 * min(h, 30))  # damped trend
        i_h = max(0.0, trend) * fi[d.weekday()] + ar.get(h, 0.0)
        o_h = level_o * fo[d.weekday()] + obligations + ap.get(h, 0.0)
        inflows.append(i_h)
        outflows.append(o_h)
        cash += i_h - o_h
        cum_in += i_h
        cum_out += o_h
        band = 1.28 * sigma * math.sqrt(h)
        series.append({"date": d.isoformat(), "inflow": _r(i_h), "outflow": _r(o_h), "net": _r(i_h - o_h), "cash": _r(cash), "low": _r(cash - band), "high": _r(cash + band)})
    horizons = []
    for hz in HORIZONS:
        row = series[hz - 1]
        horizons.append({"days": hz, "inflow": _r(sum(inflows[:hz])), "outflow": _r(sum(outflows[:hz])), "net": _r(sum(inflows[:hz]) - sum(outflows[:hz])),
                         "low": row["low"], "high": row["high"], "closing_cash": row["cash"]})
    return {"ready": True, "horizons": horizons, "series": series[:90], "_inflow": inflows, "_outflow": outflows, "_sigma": sigma}


# ───────────────────────── working capital ─────────────────────────
def working_capital(rows: list[Txn], now: datetime, failed_retryable: float = 0.0) -> dict[str, Any]:
    ar_open = [t for t in rows if t.txn_type == "invoice" and t.status == "pending"]
    ap_open = [t for t in rows if t.txn_type == "bill" and t.status == "pending"]
    ar, ap = sum(_k(t) for t in ar_open), sum(_k(t) for t in ap_open)
    ar_od, ap_od = sum(_k(t) for t in ar_open if _overdue(t, now)), sum(_k(t) for t in ap_open if _overdue(t, now))
    cut = now - timedelta(days=90)
    credit_sales = sum(_k(t) for t in rows if t.txn_type == "invoice" and t.ts >= cut)
    purchases = sum(_k(t) for t in rows if t.txn_type == "bill" and t.ts >= cut)
    cogs = sum(_k(t) for t in rows if t.txn_type == "inventory_out" and t.status == "success" and t.ts >= cut)
    stock = sum(_k(t) for t in rows if t.txn_type == "inventory_in" and t.status == "success") - sum(_k(t) for t in rows if t.txn_type == "inventory_out" and t.status == "success")
    stock = max(0.0, stock)
    dso = _r(ar / (credit_sales / 90)) if credit_sales else None
    dpo = _r(ap / (purchases / 90)) if purchases else None
    dio = _r(stock / (cogs / 90)) if cogs else None
    parts = [x for x in (dso, dio) if x is not None]
    ccc = _r(sum(parts) - (dpo or 0)) if (parts or dpo is not None) else None
    recs: list[dict[str, Any]] = []
    if dso is not None and dso > 30 and ar:
        recs.append({"id": "collect", "title": f"Collect receivables faster (DSO {dso:.0f} days)", "detail": "Send reminders on invoices past terms, offer early-payment discounts and enable mobile-money or card payment links on invoices.", "cash_release_kes": _r(max(ar_od, ar * (1 - 30 / dso)))})
    if dpo is not None and dpo < 45 and purchases:
        recs.append({"id": "terms", "title": f"Negotiate supplier terms toward 45 days (DPO {dpo:.0f})", "detail": "Paying suppliers earlier than needed drains cash. Agree 45-day terms with the largest suppliers and pay on the due date, not before.", "cash_release_kes": _r(purchases / 90 * (45 - dpo))})
    if dio is not None and dio > 60 and stock:
        recs.append({"id": "stock", "title": f"Reduce slow-moving stock (DIO {dio:.0f} days)", "detail": "Run a clearance on the slowest lines and reorder in smaller batches so stock turns over in about 60 days.", "cash_release_kes": _r(stock * (1 - 60 / dio))})
    if failed_retryable > 0:
        recs.append({"id": "retry", "title": "Recover retryable failed payments", "detail": "Timeouts, network and issuer errors are usually temporary. Offer a one-tap retry or an alternative method (mobile money) to the affected customers.", "cash_release_kes": _r(failed_retryable * 0.35)})
    if not recs:
        recs.append({"id": "none", "title": "Working capital looks efficient", "detail": "No receivable, payable or stock cycle exceeds its target. Keep capturing invoices, bills and inventory events to track it.", "cash_release_kes": 0.0})
    return {"ar": {"balance": _r(ar), "overdue": _r(ar_od), "count": len(ar_open), "dso": dso}, "ap": {"balance": _r(ap), "overdue": _r(ap_od), "count": len(ap_open), "dpo": dpo},
            "inventory": {"value": _r(stock), "dio": dio}, "ccc": ccc, "working_capital": _r(ar + stock - ap), "recommendations": recs}


# ───────────────────────── ratios ─────────────────────────
def _status(v: float | None, good: float, ok: float) -> str:
    if v is None:
        return "pass"
    return "pass" if v >= good else "warn" if v >= ok else "fail"


def compliance(cash: float, foreign_cash: float, wc: dict, out30: float, in30: float, runrate_liab: float, monthly_obligations: float) -> dict[str, Any]:
    liabilities = wc["ap"]["balance"] + runrate_liab + monthly_obligations
    cur = _r((cash + wc["ar"]["balance"] + wc["inventory"]["value"]) / liabilities) if liabilities > 0 else None
    quick = _r((cash + wc["ar"]["balance"]) / liabilities) if liabilities > 0 else None
    hqla = max(0.0, cash - 0.15 * max(0.0, foreign_cash))
    net_out = out30 - min(in30, 0.75 * out30)
    lcr = _r(hqla / net_out) if net_out > 0 else None
    notes = []
    if liabilities <= 0:
        notes.append("No current liabilities are recorded yet, so the current and quick ratios are not defined.")
    if net_out <= 0:
        notes.append("No net 30-day outflow is projected, so the liquidity coverage ratio is not binding.")
    if cur is not None and cur < 1:
        notes.append("Current ratio is below 1: short-term obligations exceed short-term assets.")
    if lcr is not None and lcr < 1:
        notes.append("Liquidity coverage is below 100%: cash would not cover projected net outflows for 30 days.")
    notes.append("Ratios are indicative management metrics computed from captured events, not a regulatory filing.")
    return {"current_ratio": {"value": cur, "threshold": 1.5, "status": _status(cur, 1.5, 1.0), "label": "Current ratio"},
            "quick_ratio": {"value": quick, "threshold": 1.0, "status": _status(quick, 1.0, 0.7), "label": "Quick ratio"},
            "lcr": {"value": lcr, "threshold": 1.0, "status": _status(lcr, 1.0, 0.8), "label": "Liquidity coverage ratio"},
            "hqla": _r(hqla), "net_outflow_30d": _r(max(0.0, net_out)), "notes": notes}


# ───────────────────────── stress tests ─────────────────────────
def stress(cash0: float, fc: dict, wc: dict, foreign_cash: float, foreign_out30: float, fail_rate: float, refund30: float, ar15: float, monthly_obligations: float) -> list[dict]:
    if not fc["ready"]:
        return []
    base_in, base_out = fc["_inflow"][:30], fc["_outflow"][:30]
    cl = wc["ap"]["balance"] + monthly_obligations + refund30
    scenarios = [
        ("rev20", "Revenue falls 20%", "Sales volume drops one fifth for 30 days.", ["inflow x0.80"], dict(i=0.8)),
        ("rev40", "Revenue falls 40%", "A severe demand shock.", ["inflow x0.60"], dict(i=0.6)),
        ("fail", "Payment failures spike", "Failed payments rise to double the current rate with no recovery.", [f"extra {min(0.5, fail_rate) * 100:.0f}% of inflow lost"], dict(i=1 - min(0.5, fail_rate))),
        ("collect", "Collections delayed 15 days", "Customers pay invoices two weeks late.", [f"KES {ar15:,.0f} of receivables slip"], dict(shift=ar15)),
        ("fx", "KES weakens 10%", "Foreign-currency cash gains value; foreign-currency costs rise.", ["USD/EUR cash +10%", "foreign outflows +10%"], dict(fx=True)),
        ("refund", "Refund and chargeback surge x3", "Refunds triple against the 30-day run-rate.", ["refunds x3"], dict(refund=2 * refund30)),
        ("severe", "Severe combined stress", "Revenue -40%, refunds x3 and delayed collections together.", ["inflow x0.60", "refunds x3", "collections slip"], dict(i=0.6, refund=2 * refund30, shift=ar15)),
    ]
    out = []
    for sid, name, desc, shocks, p in scenarios:
        cash, low = cash0 + (foreign_cash * 0.10 if p.get("fx") else 0.0), cash0
        tot_in = tot_out = 0.0
        slip_left = p.get("shift", 0.0)
        for d in range(30):
            i_d = base_in[d] * p.get("i", 1.0)
            if slip_left > 0 and d < 15:
                cut = min(slip_left / 15, i_d)
                i_d -= cut
            o_d = base_out[d] + p.get("refund", 0.0) / 30 + (foreign_out_d(foreign_out30) if p.get("fx") else 0.0)
            cash += i_d - o_d
            low = min(low, cash)
            tot_in += i_d
            tot_out += o_d
        net_out = tot_out - min(tot_in, 0.75 * tot_out)
        burn = (cash0 - cash) / 30
        runway = _r(cash0 / burn) if burn > 0 and cash0 > 0 else None
        lcr = _r(max(0.0, cash0 - 0.15 * max(0, foreign_cash)) / net_out) if net_out > 0 else None
        cr = _r((cash + wc["ar"]["balance"] + wc["inventory"]["value"]) / cl) if cl > 0 else None
        verdict = "fail" if low <= 0 else ("warn" if (lcr is not None and lcr < 1.0) or (cr is not None and cr < 1.0) else "pass")
        out.append({"id": sid, "name": name, "description": desc, "shocks": shocks, "min_cash": _r(low), "closing_cash": _r(cash), "runway_days": runway, "lcr": lcr, "current_ratio": cr, "verdict": verdict})
    return out


def foreign_out_d(foreign_out30: float) -> float:
    return foreign_out30 * 0.10 / 30


# ───────────────────────── pooling and sweeping ─────────────────────────
def proposals(banks: list[dict], rules: list[dict]) -> list[dict]:
    bal = {b["bank"]: b["balance_kes"] for b in banks}
    out = []
    for r in rules:
        if not r.get("enabled"):
            continue
        src, dst = r.get("source_bank"), r.get("dest_bank")
        if src not in bal or dst not in bal or src == dst:
            continue
        have, kind = bal[src], r.get("kind")
        if kind == "zero_balance":
            amt, why = have, "Zero-balance: move the entire balance to the header account"
        elif kind == "target_balance":
            amt, why = have - float(r.get("target_kes", 0)), f"Target-balance: keep KES {float(r.get('target_kes', 0)):,.0f} in {src}"
        else:  # threshold
            thr = float(r.get("threshold_kes", 0))
            amt, why = (have - float(r.get("target_kes", 0)) if have > thr else 0.0), f"Threshold: balance exceeded KES {thr:,.0f}"
        amt = _r(min(max(0.0, amt), max(0.0, have)))
        if amt >= 1:
            bal[src] -= amt
            bal[dst] += amt
            out.append({"rule_id": r["id"], "from_bank": src, "to_bank": dst, "amount_kes": amt, "reason": why})
    return out


def pooling(banks: list[dict], rules: list[dict], log: list[dict], total: float, out30: float) -> dict[str, Any]:
    return {"rules": rules, "proposals": proposals(banks, rules), "pooled_balance_kes": _r(total), "idle_cash_kes": _r(max(0.0, total - out30)), "sweep_log": log[-50:][::-1]}


# ───────────────────────── entry point ─────────────────────────
def build(rows: list[Txn], now: datetime, *, opening: float = 0.0, monthly_obligations: float = 0.0, rules: list[dict] | None = None,
          log: list[dict] | None = None, adj: dict[str, float] | None = None) -> dict[str, Any]:
    banks, currencies, cash = positions(rows, now, opening, adj or {})
    fc = forecast(rows, now, cash, monthly_obligations)
    cut30 = now - timedelta(days=30)
    refund30 = sum(_k(t) for t in rows if t.status == "success" and t.txn_type in ("refund", "chargeback", "fee") and t.ts >= cut30)
    pay_ok = sum(_k(t) for t in rows if t.status == "success" and t.txn_type in CASH_IN and t.ts >= cut30)
    pay_bad = sum(_k(t) for t in rows if t.status == "failed" and t.txn_type in CASH_IN and t.ts >= cut30)
    retryable = sum(_k(t) for t in rows if t.status == "failed" and t.txn_type in CASH_IN and t.reason in ("timeout", "network", "issuer_unavailable", "processing_error") and t.ts >= cut30)
    wc = working_capital(rows, now, retryable)
    fail_rate = pay_bad / (pay_ok + pay_bad) if (pay_ok + pay_bad) else 0.0
    foreign_cash = sum(c["balance_kes"] for c in currencies if c["currency"] != "KES")
    foreign_out30 = sum(_k(t) for t in rows if t.currency.upper() != "KES" and _signed(t) < 0 and t.ts >= cut30)
    in30 = sum(fc["_inflow"][:30]) if fc["ready"] else pay_ok
    out30 = sum(fc["_outflow"][:30]) if fc["ready"] else refund30 + monthly_obligations
    ar15 = min(wc["ar"]["balance"], sum(_scheduled(rows, now)[0].get(d, 0.0) for d in range(1, 16)))
    comp = compliance(cash, foreign_cash, wc, out30, in30, refund30, monthly_obligations)
    public_fc = {k: v for k, v in fc.items() if not k.startswith("_")}
    return {"currency": "KES", "as_of": now.isoformat(), "banks": banks, "currencies": currencies, "forecast": public_fc,
            "stress": stress(cash, fc, wc, foreign_cash, foreign_out30, fail_rate, refund30, ar15, monthly_obligations), "working_capital": wc,
            "pooling": pooling(banks, rules or [], log or [], cash, out30), "compliance": comp}
