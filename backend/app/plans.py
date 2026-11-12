"""Plans, the 72-hour per-website trial, and the small settings document kept on `OrgPlan.finance`.

Prices (KES): Free 0, Premium 333. Billing is not integrated, so "activating" Premium flips a flag; the trial is the only self-serve path.
A trial belongs to ONE website id and lasts 72 hours from the moment it starts; it can be started once per website id.
`OrgPlan.finance` is a JSON document: {currency, opening_balance, monthly_obligations, trials, capture, sweep_rules, sweep_log, sweep_adj, email_auto}.
JSON columns are not change-tracked in place, so every write goes through `save_finance` (assigns a new dict)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ConnectedSite, FinanceTxn, OrgPlan, SiteIdentity
from .utils import iso, utcnow

PLAN_NAME = "Churnce Pro"
PRICE_KES = {"free": 0, "premium": 333}
TRIAL_HOURS = 72
PREMIUM_FEATURES: list[dict[str, str]] = [
    {"id": "liquidity", "title": "Financial cashflow and liquidity engine", "text": "Real-time cash positions across banks and currencies, runway and coverage, built from every captured payment, refund, fee, chargeback, payout, invoice and bill."},
    {"id": "forecast", "title": "Multi-horizon cash forecast", "text": "7, 14, 30, 60 and 90-day forecasts of inflows, outflows and closing cash with a confidence band."},
    {"id": "stress", "title": "Scenario stress tests", "text": "Revenue shocks, payment-failure spikes, delayed collections, KES weakness and refund surges, each scored pass, warn or fail."},
    {"id": "working_capital", "title": "Working-capital optimisation", "text": "Receivables, payables and inventory cycles (DSO, DPO, DIO, cash conversion) with the cash each fix would release."},
    {"id": "pooling", "title": "Cash pooling and sweeping rules", "text": "Target-balance, zero-balance and threshold sweeps between banks, proposed continuously and run automatically."},
    {"id": "compliance", "title": "Compliance metrics", "text": "Current ratio, quick ratio and liquidity coverage ratio against thresholds."},
    {"id": "analyst", "title": "Cents AI virtual analyst", "text": "A Gemini-powered financial analyst that summarises your metrics, flags risks and answers questions in chat."},
    {"id": "dashboard", "title": "Finance and liquidity dashboard", "text": "KPIs, cashflow and forecast charts, per-site breakdowns and a live transaction ledger, in KES."},
]
FINANCE_DEFAULTS: dict[str, Any] = {"currency": "KES", "opening_balance": 0.0, "monthly_obligations": 0.0}


def get_plan(db: Session, org_id: str) -> OrgPlan:
    row = db.get(OrgPlan, org_id)
    if row is None:
        row = OrgPlan(org_id=org_id, plan="free", finance=dict(FINANCE_DEFAULTS))
        db.add(row)
        db.flush()
    return row


def finance_settings(row: OrgPlan) -> dict:
    """The three user-editable settings only (the rest of the document is internal state)."""
    f = {**FINANCE_DEFAULTS, **(row.finance or {})}
    return {k: f[k] for k in FINANCE_DEFAULTS}


def doc(row: OrgPlan) -> dict[str, Any]:
    return {**FINANCE_DEFAULTS, **(row.finance or {})}


def save_finance(row: OrgPlan, **updates: Any) -> None:
    row.finance = {**(row.finance or {}), **updates}


# ───────────────────────── trial ─────────────────────────
def _parse(v: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(v) if v else None
    except ValueError:
        return None


def code_for_host(db: Session, org_id: str, host: str) -> str | None:
    return db.scalar(select(SiteIdentity.website_code).join(ConnectedSite, ConnectedSite.id == SiteIdentity.site_id).where(ConnectedSite.org_id == org_id, ConnectedSite.host == host))


def trial_of(row: OrgPlan, code: str | None) -> dict[str, Any]:
    t = (doc(row).get("trials") or {}).get(code or "") if code else None
    ends = _parse(t.get("ends")) if t else None
    left = max(0, int((ends - utcnow()).total_seconds())) if ends else 0
    return {"available": bool(code) and not t, "active": left > 0, "used": bool(t), "ends_at": iso(ends) if ends else None, "seconds_left": left, "website_id": code}


def start_trial(db: Session, org_id: str, host: str) -> tuple[bool, dict[str, Any]]:
    """Returns (started, trial). Starting needs a website id; a second start for the same id is refused."""
    row = get_plan(db, org_id)
    code = code_for_host(db, org_id, host)
    if not code:
        raise ValueError("Generate a website ID for this site first")
    cur = trial_of(row, code)
    if cur["used"]:
        return False, cur
    now = utcnow()
    trials = dict(doc(row).get("trials") or {})
    trials[code] = {"host": host, "started": iso(now), "ends": iso(now + timedelta(hours=TRIAL_HOURS))}
    save_finance(row, trials=trials)
    return True, trial_of(row, code)


def subscribed_hosts(row: OrgPlan | None) -> set[str]:
    return {t["host"] for t in ((doc(row).get("subs") or {}).values() if row else []) if t.get("host")}


def subscribe(db: Session, org_id: str, host: str) -> dict[str, Any]:
    """Pro plan for ONE website id, kept in `finance.subs`. Billing is not integrated: this records the subscription (the caller audits it)."""
    row = get_plan(db, org_id)
    code = code_for_host(db, org_id, host)
    if not code:
        raise ValueError("Generate a website ID for this site first")
    subs = dict(doc(row).get("subs") or {})
    subs.setdefault(code, {"host": host, "since": iso(utcnow())})
    save_finance(row, subs=subs)
    return subs[code]


def active_trial_hosts(db: Session, org_id: str) -> set[str]:
    """Hosts with Premium privileges from a running 72-hour trial or a Pro subscription."""
    row = db.get(OrgPlan, org_id)
    if not row:
        return set()
    now = utcnow()
    return {t["host"] for t in (doc(row).get("trials") or {}).values() if (_parse(t.get("ends")) or now) > now} | subscribed_hosts(row)


# ───────────────────────── access ─────────────────────────
def is_premium(db: Session, org_id: str, host: str | None = None) -> bool:
    """Premium features are available when the organisation is on Premium, or the website has an active 72-hour trial.
    With no host (an administrator looking at the whole organisation) any active trial counts; data is then limited to those sites."""
    row = db.get(OrgPlan, org_id)
    if row and row.plan == "premium":
        return True
    hosts = active_trial_hosts(db, org_id)
    return (host in hosts) if host else bool(hosts)


def allowed_hosts(db: Session, org_id: str, host: str | None) -> set[str] | None:
    """None = every site (organisation is Premium). Otherwise the set of sites whose trial is active (limited to `host` when given)."""
    row = db.get(OrgPlan, org_id)
    if row and row.plan == "premium":
        return None if not host else {host}
    hosts = active_trial_hosts(db, org_id)
    return ({host} & hosts) if host else hosts


def access_info(db: Session, org_id: str, host: str | None = None, *, admin: bool = False) -> dict[str, Any]:
    row = get_plan(db, org_id)
    code = code_for_host(db, org_id, host) if host else None
    trial = trial_of(row, code) if host else {"available": False, "active": False, "used": False, "ends_at": None, "seconds_left": 0, "website_id": None}
    org_premium = row.plan == "premium"
    subscribed = bool(host) and host in subscribed_hosts(row)
    active = org_premium or subscribed or (trial["active"] if host else bool(active_trial_hosts(db, org_id)))
    out: dict[str, Any] = {"plan": row.plan, "active": active, "subscribed": subscribed, "source": "org" if org_premium else ("pro" if subscribed else ("trial" if active else None)), "price_kes": PRICE_KES, "trial": trial, "trial_sites": []}
    if admin:
        now = utcnow()
        out["trial_sites"] = [{"website_id": c, "host": t["host"], "ends_at": t["ends"], "seconds_left": int(((_parse(t["ends"]) or now) - now).total_seconds())}
                              for c, t in (doc(row).get("trials") or {}).items() if (_parse(t.get("ends")) or now) > now]
    return out


def premium_blob(db: Session, org_id: str, host: str) -> dict[str, Any]:
    """The `premium` object returned to the extension on every heartbeat."""
    info = access_info(db, org_id, host)
    return {"active": info["active"], "source": info["source"], "trial_ends_at": info["trial"]["ends_at"], "seconds_left": info["trial"]["seconds_left"], "trial_used": info["trial"]["used"]}


# ───────────────────────── capture state ─────────────────────────
def capture_state(db: Session, org_id: str) -> dict[str, Any]:
    row = get_plan(db, org_id)
    c = doc(row).get("capture")
    if c:
        return c
    return {"state": "running", "since": None, "syncing_until": None}  # capture follows Premium + consent until someone pauses or stops it


def set_capture(db: Session, org_id: str, state: str, syncing_seconds: int = 0) -> dict[str, Any]:
    row = get_plan(db, org_id)
    now = utcnow()
    c = {"state": state, "since": iso(now), "syncing_until": iso(now + timedelta(seconds=syncing_seconds)) if syncing_seconds else None}
    save_finance(row, capture=c)
    return c
