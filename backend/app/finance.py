"""Premium finance and liquidity: plan access, extension ingestion, capture control, the liquidity suite, sweeping and Cents AI.

Analytics live in `finance_engine` and `liquidity_suite` (pure). This module authenticates, enforces plan + consent + role + website scope,
stores and serves. Every money value returned to the dashboard is KES (`fx.py` converts other currencies; amounts are stored in their
native currency and minor units). Stored data is metadata only: type, status, amount, currency, method category, bank label, failure
reason, due date, time. `TxnIn` forbids every other field, so a site that accidentally sends a card number or an email gets a 422."""
from __future__ import annotations

import json
import logging
import random
import re
import secrets
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import feedback, fx, liquidity_suite, plans, weekly_report, workspace
from .audit import audit
from .config import get_settings
from .database import get_db, notify
from .finance_engine import Txn, analyse, major
from .models import ConnectedSite, FinanceTxn, MonitoringConfig, OrgPlan
from .plans import PLAN_NAME, PREMIUM_FEATURES, doc, finance_settings, get_plan, save_finance
from .security import Principal, ingest_config, limiter, require, require_unscoped
from .utils import iso, utcnow

log = logging.getLogger("churnce.finance")
router = APIRouter()
TxnType = Literal["payment", "subscription", "refund", "chargeback", "fee", "payout", "invoice", "bill", "inventory_in", "inventory_out"]
Status = Literal["success", "failed", "pending"]
Method = Literal["card", "mobile_money", "bank_transfer", "wallet", "cash_on_delivery", "other"]
Reason = Literal["insufficient_funds", "card_declined", "expired_card", "fraud_check", "timeout", "network", "issuer_unavailable", "processing_error", "cancelled_by_user", "other"]
RETRYABLE = {"timeout", "network", "issuer_unavailable", "processing_error"}
ANALYST = "Cents AI"


# ───────────────────────── access ─────────────────────────
def _host(p: Principal) -> str | None:
    return p.site_host if p.scoped else None


def _gate(db: Session, p: Principal) -> set[str] | None:
    """Raise 402 unless Premium (or an active trial) covers this session. Returns the set of sites the session may see (None = all)."""
    host = _host(p)
    if p.viewing:  # an administrator inspecting one website keeps full access to its data
        return {p.site_host}
    if not plans.is_premium(db, p.org_id, host):
        raise HTTPException(402, f"The finance and liquidity engine is part of {PLAN_NAME}. Start the 72-hour free trial or activate Premium from the extension settings.")
    return plans.allowed_hosts(db, p.org_id, host)


def _minor(x: float) -> int:
    return int((Decimal(str(x)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ser_plan(row: OrgPlan) -> dict[str, Any]:
    return {"plan": row.plan, "name": PLAN_NAME, "features": PREMIUM_FEATURES, "price_kes": plans.PRICE_KES, "activated_at": iso(row.activated_at) if row.activated_at else None,
            "activated_by": row.activated_by, "billing": "not_integrated", "finance": finance_settings(row)}


# ───────────────────────── plan ─────────────────────────
@router.get("/plan")
def read_plan(p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    row = get_plan(db, p.org_id)
    db.commit()
    return ser_plan(row)


@router.get("/plan/access")
def plan_access(p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    """What this session may use: Premium by organisation plan or by an active 72-hour trial on its website id."""
    out = plans.access_info(db, p.org_id, _host(p), admin=(not p.scoped and p.can("users:manage")))
    db.commit()
    return out


@router.post("/plan/subscribe")
def subscribe_pro(p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    """A website-ID session subscribes its own website to Pro (KES 333) once the free trial has ended. Billing is not integrated yet,
    so this records the subscription and is audited; wire a payment provider here before charging anyone."""
    host = _host(p)
    if not host:
        raise HTTPException(409, "Subscribe from a website-ID session, or use the organisation plan as an administrator.")
    try:
        sub = plans.subscribe(db, p.org_id, host)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    audit(db, p.org_id, p.actor, "plan_subscribed", "site", host, None, "pro")
    notify(db, p.org_id, {"type": "finance_update"})
    out = plans.access_info(db, p.org_id, host)
    db.commit()
    return {"subscription": sub, "access": out}


class PlanIn(BaseModel):
    plan: Literal["free", "premium"]


@router.post("/plan")
def change_plan(body: PlanIn, p: Principal = Depends(require_unscoped("users:manage")), db: Session = Depends(get_db)):
    """Billing is not integrated: this flips the feature flag and is audited. Wire a payment provider here before charging anyone."""
    row = get_plan(db, p.org_id)
    old, row.plan = row.plan, body.plan
    row.activated_at, row.activated_by = utcnow(), p.name
    audit(db, p.org_id, p.actor, "plan_changed", "plan", p.org_id, old, body.plan)
    notify(db, p.org_id, {"type": "finance_update"})
    db.commit()
    return ser_plan(row)


# ───────────────────────── extension → backend ─────────────────────────
class TxnIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=3, max_length=80)  # the site's own opaque reference; idempotency key per (txn_type, status)
    txn_type: TxnType
    status: Status
    amount: float = Field(ge=0, le=1_000_000_000)
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    method: Method = "other"
    reason: Reason | None = None
    occurred_at: datetime | None = None
    due_at: datetime | None = None
    bank: str | None = Field(default=None, max_length=40)
    session_ref: str | None = Field(default=None, max_length=80)

    @field_validator("bank")
    @classmethod
    def _bank_label(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f<>]", "", v)).strip()
        if re.search(r"\d{6,}", v.replace(" ", "")):
            raise ValueError("bank must be a label such as 'Equity Bank', never an account number")
        return v or None


class TxnBatch(BaseModel):
    site_host: str = Field(max_length=200)
    events: list[TxnIn] = Field(min_length=1, max_length=100)


def _utc(d: datetime | None) -> datetime | None:
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


@router.post("/finance/events")
def ingest(body: TxnBatch, cfg: MonitoringConfig = Depends(ingest_config), db: Session = Depends(get_db)):
    limiter.check(f"fin:{cfg.id}", 120)
    host = workspace._clean_host(body.site_host.split(":")[0])
    domains = [d.lower() for d in (cfg.authorized_domains or [])]
    if not host or not any(host == d or (d.startswith("*.") and host.endswith(d[1:])) for d in domains):
        raise HTTPException(403, "That domain is not authorised for this tenant")
    if not plans.is_premium(db, cfg.org_id, host):
        raise HTTPException(402, f"Finance capture is part of {PLAN_NAME}. Start the free trial from the extension settings.")
    site = workspace._site(db, cfg.org_id, host)
    if "finance" not in (site.consent or {}).get("scopes", []):
        raise HTTPException(403, "The site owner has not granted finance consent in the extension")
    capture = plans.capture_state(db, cfg.org_id)
    if capture["state"] != "running":  # paused or stopped from the dashboard: the extension keeps nothing back, the server drops it
        db.commit()
        return {"accepted": 0, "duplicates": 0, "capture": capture["state"]}
    now, added = utcnow(), 0
    for e in body.events:
        key = f"{e.event_id}:{e.txn_type}:{e.status}"[:80]
        if db.scalar(select(FinanceTxn.id).where(FinanceTxn.org_id == cfg.org_id, FinanceTxn.client_event_id == key)):
            continue
        at = _utc(e.occurred_at)
        db.add(FinanceTxn(org_id=cfg.org_id, client_event_id=key, site_host=host, session_ref=e.session_ref, txn_type=e.txn_type, status=e.status, amount_minor=_minor(e.amount),
                          currency=e.currency.upper(), method=e.method, reason=e.reason if e.status == "failed" else None, bank=e.bank or "", due_at=_utc(e.due_at),
                          ts=min(at, now) if at else now))
        added += 1
        workspace.feed.add(cfg.org_id, host, "activity", "WARNING" if e.status == "failed" else "INFO",
                           f"{e.txn_type} · {e.status} · {e.amount:,.2f} {e.currency.upper()}" + (f" · {e.bank}" if e.bank else "") + (f" · {e.reason}" if e.status == "failed" and e.reason else ""))
    site.last_seen = now
    if added:
        notify(db, cfg.org_id, {"type": "finance_update", "added": added, "sites": [host]})
        notify(db, cfg.org_id, {"type": "site_activity", "sites": [host], "accepted": added})
    db.commit()
    return {"accepted": added, "duplicates": len(body.events) - added, "capture": "running"}


# ───────────────────────── queries ─────────────────────────
def _query(org_id: str, hosts: set[str] | None, site: str | None):
    q = select(FinanceTxn).where(FinanceTxn.org_id == org_id)
    if hosts is not None:
        q = q.where(FinanceTxn.site_host.in_(hosts or {"-"}))
    if site:
        q = q.where(FinanceTxn.site_host == site)
    return q


def _rows(db: Session, org_id: str, hosts: set[str] | None, site: str | None, *, kes: bool) -> list[Txn]:
    q = _query(org_id, hosts, site).where(FinanceTxn.ts >= utcnow() - timedelta(days=400))
    out = []
    for t in db.scalars(q.order_by(FinanceTxn.ts.desc()).limit(50000)):
        amt, cur = (fx.to_kes_minor(t.amount_minor, t.currency), "KES") if kes else (t.amount_minor, t.currency)
        out.append(Txn(ts=t.ts, txn_type=t.txn_type, status=t.status, amount_minor=amt, currency=cur, method=t.method, reason=t.reason, site_host=t.site_host, id=t.id,
                       simulated=t.simulated, bank=t.bank or "", due_at=t.due_at))
    return out


def _site_filter(p: Principal, site: str | None) -> str | None:
    return p.site_host if p.scoped else site


@router.get("/finance/summary")
def summary(days: int = Query(30, ge=7, le=90), site: str | None = None, p: Principal = Depends(require("finance:read")), db: Session = Depends(get_db)):
    hosts = _gate(db, p)
    cfg = finance_settings(get_plan(db, p.org_id))
    rows = _rows(db, p.org_id, hosts, _site_filter(p, site), kes=True)
    out = analyse(rows, now=utcnow(), days=days, currency="KES", opening_balance=float(cfg["opening_balance"]), monthly_obligations=float(cfg["monthly_obligations"]))
    avail = sorted({h for h in db.scalars(_query(p.org_id, hosts, None).with_only_columns(FinanceTxn.site_host).distinct()).all() if h})
    out.update({"sites_available": avail, "site": _site_filter(p, site), "simulated": any(r.simulated for r in rows), "settings": {**cfg, "currency": "KES"}, "server_time": iso(utcnow())})
    db.commit()
    return out


@router.get("/finance/transactions")
def transactions(status_: Literal["all", "failed", "success", "pending"] = Query("all", alias="status"), site: str | None = None, limit: int = Query(60, ge=1, le=200),
                 p: Principal = Depends(require("finance:read")), db: Session = Depends(get_db)):
    hosts = _gate(db, p)
    q = _query(p.org_id, hosts, _site_filter(p, site))
    if status_ != "all":
        q = q.where(FinanceTxn.status == status_)
    rows = db.scalars(q.order_by(FinanceTxn.ts.desc()).limit(limit)).all()
    return {"transactions": [{"id": t.id, "site_host": t.site_host, "txn_type": t.txn_type, "status": t.status, "amount": major(fx.to_kes_minor(t.amount_minor, t.currency)), "currency": "KES",
                              "native_amount": major(t.amount_minor), "native_currency": t.currency, "bank": t.bank or None, "due_at": iso(t.due_at) if t.due_at else None,
                              "method": t.method, "reason": t.reason, "retryable": t.reason in RETRYABLE, "ts": iso(t.ts), "simulated": t.simulated} for t in rows]}


class SettingsIn(BaseModel):
    currency: str = Field(default="KES", min_length=3, max_length=3)
    opening_balance: float = Field(ge=-1e9, le=1e9)
    monthly_obligations: float = Field(ge=0, le=1e9)


@router.put("/finance/settings")
def put_settings(body: SettingsIn, p: Principal = Depends(require_unscoped("finance:control")), db: Session = Depends(get_db)):
    _gate(db, p)
    row = get_plan(db, p.org_id)
    new = {"currency": "KES", "opening_balance": body.opening_balance, "monthly_obligations": body.monthly_obligations}
    save_finance(row, **new)  # merge: trials, capture state and sweep rules live in the same document and must survive
    audit(db, p.org_id, p.actor, "finance_settings_changed", "plan", p.org_id, None, None, new)
    notify(db, p.org_id, {"type": "finance_update"})
    db.commit()
    return {"finance": finance_settings(row)}


# ───────────────────────── capture control ─────────────────────────
SYNC_SECONDS = 6


def _visible_site_rows(db: Session, p: Principal, hosts: set[str] | None) -> list[ConnectedSite]:
    q = select(ConnectedSite).where(ConnectedSite.org_id == p.org_id)
    if p.scoped:
        q = q.where(ConnectedSite.host == p.site_host)
    elif hosts is not None:
        q = q.where(ConnectedSite.host.in_(hosts or {"-"}))
    return list(db.scalars(q.order_by(ConnectedSite.host)).all())


def _capture_status(db: Session, p: Principal, hosts: set[str] | None) -> dict[str, Any]:
    cap = plans.capture_state(db, p.org_id)
    now = utcnow()
    syncing_until = plans._parse(cap.get("syncing_until"))
    syncing = bool(syncing_until and syncing_until > now)
    sites_rows = _visible_site_rows(db, p, hosts)
    counts = {h: (n, last) for h, n, last in db.execute(select(FinanceTxn.site_host, func.count(), func.max(FinanceTxn.ts)).where(FinanceTxn.org_id == p.org_id).group_by(FinanceTxn.site_host)).all()}
    sites: list[dict[str, Any]] = []
    for s in sites_rows:
        seen = s.last_seen
        if seen is not None and seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        ago = int((now - seen).total_seconds()) if seen else None
        online = ago is not None and ago <= workspace.ONLINE_SECONDS
        ident = workspace.ident_for(db, s.id)
        n, last = counts.get(s.host, (0, None))
        sync = "paused" if cap["state"] == "paused" else "stopped" if cap["state"] == "stopped" else "syncing" if syncing else ("live" if online else "idle")
        sites.append({"host": s.host, "name": (ident.name if ident and ident.name else s.host), "website_id": ident.website_code if ident else None, "online": online, "last_seen": iso(seen) if seen else None,
                      "seconds_since_seen": ago, "rtt_ms": workspace.RTT.get((p.org_id, s.host)), "txn_count": n, "last_txn_at": iso(last) if last else None, "sync": sync})
    logs: list[dict[str, Any]] = []
    for s in sites_rows:
        for r in workspace.feed.since(p.org_id, s.host, 0, None, 40):
            logs.append({"id": r["id"], "ts": r["ts"], "level": r["level"], "host": s.host, "msg": r["message"]})
    logs.sort(key=lambda r: r["id"], reverse=True)
    for r in logs:
        r.pop("id")
    return {"state": cap["state"], "since": cap.get("since"), "sites": sites, "logs": logs[:60], "syncing_until": iso(syncing_until) if syncing else None, "server_time": iso(now)}


@router.get("/finance/capture")
def capture_status(p: Principal = Depends(require("finance:read")), db: Session = Depends(get_db)):
    hosts = _gate(db, p)
    out = _capture_status(db, p, hosts)
    db.commit()
    return out


class CaptureIn(BaseModel):
    action: Literal["start", "pause", "restart", "stop"]


@router.post("/finance/capture")
def capture_action(body: CaptureIn, p: Principal = Depends(require("finance:control")), db: Session = Depends(get_db)):
    """Start, pause, restart or stop real-time capture. The extension reads the state on every heartbeat; the server also drops events while it is not running."""
    hosts = _gate(db, p)
    state = {"start": "running", "restart": "running", "pause": "paused", "stop": "stopped"}[body.action]
    plans.set_capture(db, p.org_id, state, SYNC_SECONDS if body.action in ("start", "restart") else 0)
    for s in _visible_site_rows(db, p, hosts):
        msg = {"start": "Finance capture started: syncing website data", "restart": "Finance capture restarted: re-syncing website data",
               "pause": "Finance capture paused from the dashboard", "stop": "Finance capture stopped from the dashboard"}[body.action]
        workspace.feed.add(p.org_id, s.host, "log", "INFO", msg)
    audit(db, p.org_id, p.actor, f"finance_capture_{body.action}", "plan", p.org_id, None, state)
    notify(db, p.org_id, {"type": "finance_update", "capture": state})
    db.commit()
    return _capture_status(db, p, hosts)


# ───────────────────────── liquidity suite ─────────────────────────
def _liquidity(db: Session, p: Principal, hosts: set[str] | None, site: str | None) -> dict[str, Any]:
    row = get_plan(db, p.org_id)
    d = doc(row)
    rows = _rows(db, p.org_id, hosts, _site_filter(p, site), kes=False)
    out = liquidity_suite.build(rows, utcnow(), opening=float(d["opening_balance"]), monthly_obligations=float(d["monthly_obligations"]), rules=d.get("sweep_rules") or [],
                                log=d.get("sweep_log") or [], adj=d.get("sweep_adj") or {})
    out["simulated"] = any(r.simulated for r in rows)
    out["transactions"] = len(rows)
    return out


@router.get("/finance/liquidity")
def liquidity(site: str | None = None, p: Principal = Depends(require("finance:read")), db: Session = Depends(get_db)):
    hosts = _gate(db, p)
    out = _liquidity(db, p, hosts, site)
    db.commit()
    return out


# ───────────────────────── cash pooling and sweeping ─────────────────────────
class SweepIn(BaseModel):
    id: str | None = Field(default=None, max_length=40)
    name: str = Field(min_length=2, max_length=80)
    kind: Literal["target_balance", "zero_balance", "threshold"] = "target_balance"
    source_bank: str = Field(min_length=1, max_length=40)
    dest_bank: str = Field(min_length=1, max_length=40)
    threshold_kes: float = Field(default=0, ge=0, le=1e10)
    target_kes: float = Field(default=0, ge=0, le=1e10)
    enabled: bool = True


def _write_scope(p: Principal) -> None:
    if p.scoped:
        raise HTTPException(403, "Sweeping rules move cash organisation-wide. Ask an administrator to change them; you can still view the proposals.")


@router.get("/finance/sweeps")
def sweeps(p: Principal = Depends(require("finance:read")), db: Session = Depends(get_db)):
    hosts = _gate(db, p)
    suite = _liquidity(db, p, hosts, None)
    d = doc(get_plan(db, p.org_id))
    return {"rules": d.get("sweep_rules") or [], "proposals": suite["pooling"]["proposals"], "log": (d.get("sweep_log") or [])[-50:][::-1]}


@router.post("/finance/sweeps")
def save_sweep(body: SweepIn, p: Principal = Depends(require("finance:control")), db: Session = Depends(get_db)):
    _write_scope(p)
    _gate(db, p)
    if body.source_bank == body.dest_bank:
        raise HTTPException(422, "Source and destination must be different accounts")
    row = get_plan(db, p.org_id)
    rules = list(doc(row).get("sweep_rules") or [])
    rule = {**body.model_dump(), "id": body.id or "sw_" + secrets.token_hex(4), "last_run_at": None}
    for i, r in enumerate(rules):
        if r["id"] == rule["id"]:
            rule["last_run_at"] = r.get("last_run_at")
            rules[i] = rule
            break
    else:
        if len(rules) >= 20:
            raise HTTPException(409, "At most 20 sweeping rules")
        rules.append(rule)
    save_finance(row, sweep_rules=rules)
    audit(db, p.org_id, p.actor, "sweep_rule_saved", "plan", p.org_id, None, None, {"rule": rule["id"], "kind": rule["kind"]})
    db.commit()
    return {"rule": rule}


@router.delete("/finance/sweeps/{rule_id}")
def delete_sweep(rule_id: str, p: Principal = Depends(require("finance:control")), db: Session = Depends(get_db)):
    _write_scope(p)
    row = get_plan(db, p.org_id)
    rules = [r for r in (doc(row).get("sweep_rules") or []) if r["id"] != rule_id]
    save_finance(row, sweep_rules=rules)
    audit(db, p.org_id, p.actor, "sweep_rule_deleted", "plan", p.org_id, None, None, {"rule": rule_id})
    db.commit()
    return {"ok": True}


def execute_sweeps(db: Session, org_id: str, mode: Literal["auto", "manual"], hosts: set[str] | None = None) -> list[dict[str, Any]]:
    """Apply every proposal as a recorded internal transfer. Transfers are position adjustments (`sweep_adj`), so the transaction ledger is never altered."""
    row = get_plan(db, org_id)
    d = doc(row)
    rules = d.get("sweep_rules") or []
    if not any(r.get("enabled") for r in rules):
        return []
    rows = _rows(db, org_id, hosts, None, kes=False)
    banks, _, _ = liquidity_suite.positions(rows, utcnow(), float(d["opening_balance"]), d.get("sweep_adj") or {})
    proposals = liquidity_suite.proposals(banks, rules)
    if not proposals:
        return []
    adj, log_rows, now = dict(d.get("sweep_adj") or {}), list(d.get("sweep_log") or []), utcnow()
    names = {r["id"]: r["name"] for r in rules}
    done = []
    for pr in proposals:
        adj[pr["from_bank"]] = round(adj.get(pr["from_bank"], 0.0) - pr["amount_kes"], 2)
        adj[pr["to_bank"]] = round(adj.get(pr["to_bank"], 0.0) + pr["amount_kes"], 2)
        entry = {"id": "sx_" + secrets.token_hex(4), "at": iso(now), "rule_id": pr["rule_id"], "rule_name": names.get(pr["rule_id"], ""), "from_bank": pr["from_bank"], "to_bank": pr["to_bank"],
                 "amount_kes": pr["amount_kes"], "mode": mode}
        log_rows.append(entry)
        done.append(entry)
    for r in rules:
        if any(x["rule_id"] == r["id"] for x in done):
            r["last_run_at"] = iso(now)
    save_finance(row, sweep_adj=adj, sweep_log=log_rows[-200:], sweep_rules=rules)
    return done


@router.post("/finance/sweeps/run")
def run_sweeps(p: Principal = Depends(require("finance:control")), db: Session = Depends(get_db)):
    _write_scope(p)
    hosts = _gate(db, p)
    done = execute_sweeps(db, p.org_id, "manual", hosts)
    if done:
        audit(db, p.org_id, p.actor, "sweeps_run", "plan", p.org_id, None, None, {"transfers": len(done), "total_kes": round(sum(x["amount_kes"] for x in done), 2)})
        notify(db, p.org_id, {"type": "finance_update"})
    db.commit()
    return {"executed": done}


def auto_sweep_all(db: Session) -> int:
    """Scheduler step: run the enabled sweeping rules of every organisation that has Premium or an active trial, while capture is running."""
    n = 0
    for row in db.scalars(select(OrgPlan)).all():
        try:
            if not (doc(row).get("sweep_rules")) or not plans.is_premium(db, row.org_id):
                continue
            if plans.capture_state(db, row.org_id)["state"] != "running":
                continue
            done = execute_sweeps(db, row.org_id, "auto", plans.allowed_hosts(db, row.org_id, None))
            if done:
                audit(db, row.org_id, "scheduler", "sweeps_auto", "plan", row.org_id, None, None, {"transfers": len(done)})
                notify(db, row.org_id, {"type": "finance_update"})
                n += len(done)
        except Exception:  # noqa: BLE001 - one tenant's bad data must not stop the others
            log.exception("auto sweep failed for %s", row.org_id)
            db.rollback()
    db.commit()
    return n


# ───────────────────────── Cents AI ─────────────────────────
def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"KES {x:,.0f}"


def _facts(db: Session, p: Principal, hosts: set[str] | None) -> dict[str, Any]:
    suite = _liquidity(db, p, hosts, None)
    cfg = finance_settings(get_plan(db, p.org_id))
    s = analyse(_rows(db, p.org_id, hosts, _site_filter(p, None), kes=True), now=utcnow(), days=30, currency="KES", opening_balance=float(cfg["opening_balance"]), monthly_obligations=float(cfg["monthly_obligations"]))
    comp, wc = suite["compliance"], suite["working_capital"]
    cash = sum(b["balance_kes"] for b in suite["banks"])
    f = {
        "currency": "KES", "cash_total": round(cash), "banks": [{"bank": re.sub(r"[^\w .&'-]", "", b["bank"])[:40], "balance_kes": round(b["balance_kes"]), "share_pct": b["share_pct"]} for b in suite["banks"][:8]],
        "currencies": [{"currency": c["currency"], "balance_kes": round(c["balance_kes"])} for c in suite["currencies"][:6]],
        "forecast": [{"days": h["days"], "net": round(h["net"]), "closing_cash": round(h["closing_cash"]), "low": round(h["low"])} for h in suite["forecast"]["horizons"]],
        "stress": [{"scenario": r["name"], "verdict": r["verdict"], "min_cash": round(r["min_cash"]), "runway_days": r["runway_days"]} for r in suite["stress"]],
        "working_capital": {"ar": wc["ar"], "ap": wc["ap"], "inventory": wc["inventory"], "ccc_days": wc["ccc"], "net": round(wc["working_capital"]),
                            "recommendations": [{"title": r["title"], "cash_release_kes": round(r["cash_release_kes"])} for r in wc["recommendations"]]},
        "compliance": {"current_ratio": comp["current_ratio"]["value"], "quick_ratio": comp["quick_ratio"]["value"], "lcr": comp["lcr"]["value"],
                       "current_status": comp["current_ratio"]["status"], "quick_status": comp["quick_ratio"]["status"], "lcr_status": comp["lcr"]["status"]},
        "pooling": {"idle_cash": round(suite["pooling"]["idle_cash_kes"]), "proposals": suite["pooling"]["proposals"][:5]},
        "kpis": {k: s.get(k) for k in ("health", "kpis") if k in s},
    }
    return f


def _fallback_summary(f: dict[str, Any]) -> dict[str, Any]:
    comp, wc = f["compliance"], f["working_capital"]
    fails = [r for r in f["stress"] if r["verdict"] == "fail"]
    warns = [r for r in f["stress"] if r["verdict"] == "warn"]
    adv, risks, hi = [], [], []
    hi.append(f"Cash across {len(f['banks'])} account(s): {_fmt(f['cash_total'])}.")
    if f["forecast"]:
        h30 = next((h for h in f["forecast"] if h["days"] == 30), f["forecast"][0])
        hi.append(f"30-day forecast: net {_fmt(h30['net'])}, closing cash {_fmt(h30['closing_cash'])} (low case {_fmt(h30['low'])}).")
        if h30["net"] < 0:
            risks.append("Outflows are forecast to exceed inflows over the next 30 days.")
            adv.append({"title": "Close the 30-day cash gap", "detail": "Delay discretionary spend, chase overdue receivables and pause non-essential payouts until net cash turns positive.", "priority": "high"})
    for key, label in (("current_ratio", "Current ratio"), ("quick_ratio", "Quick ratio"), ("lcr", "Liquidity coverage ratio")):
        v = comp[key]
        hi.append(f"{label}: {'n/a' if v is None else f'{v:.2f}'}.")
    if comp["lcr_status"] != "pass":
        risks.append("Liquidity coverage is below the comfortable threshold.")
        adv.append({"title": "Raise high-quality liquid assets", "detail": "Hold more of your cash in KES and in accounts you can access the same day; reduce reliance on foreign-currency balances.", "priority": "high"})
    if fails:
        risks.append("Failed stress tests: " + ", ".join(r["scenario"] for r in fails) + ".")
        adv.append({"title": "Prepare for the failed stress scenarios", "detail": "Arrange a standby overdraft or credit line and keep a buffer sized for the worst failed scenario.", "priority": "high"})
    elif warns:
        risks.append("Stress warnings: " + ", ".join(r["scenario"] for r in warns) + ".")
    for r in wc["recommendations"][:3]:
        if r["cash_release_kes"] > 0:
            adv.append({"title": r["title"], "detail": f"Could release about {_fmt(r['cash_release_kes'])} of working capital.", "priority": "medium"})
    if f["pooling"]["idle_cash"] > 0 and len(f["banks"]) > 1:
        adv.append({"title": "Pool idle cash", "detail": f"About {_fmt(f['pooling']['idle_cash'])} is idle. Add a target-balance sweep to concentrate it in your main account.", "priority": "low"})
    if not adv:
        adv.append({"title": "Keep capturing", "detail": "Metrics look healthy. Keep invoices, bills and bank labels flowing so the forecasts stay accurate.", "priority": "low"})
    if not f["cash_total"] and not f["banks"]:
        hi = ["No financial events have been captured yet. Press Start capture and let the extension sync, or add demo data."]
    return {"summary": " ".join(hi[:3]), "highlights": hi, "advice": adv[:6], "risks": risks}


SYSTEM = (f"You are {ANALYST}, a virtual financial analyst inside Churnce for a website owner in Kenya. All money is in Kenyan shillings (KES). "
          "Use ONLY the figures in the JSON context; never invent numbers, accounts, customers or laws. Be concise, concrete and professional. "
          "Ratios are indicative management metrics, not regulatory filings; say so if asked for compliance certainty. Do not give legal or tax advice.")


def _llm(prompt: str) -> tuple[str, str]:
    from .llm import service as llm

    if not llm.hosted_enabled():
        raise RuntimeError("no hosted LLM configured")
    return llm._generate(SYSTEM, prompt)


@router.get("/finance/weekly-report")
def weekly(p: Principal = Depends(require("finance:read")), db: Session = Depends(get_db)):
    """Seven-day summary of every captured metric, the actions it calls for and advice. Every role may read it; website sessions see their own website only."""
    hosts = _gate(db, p)
    now = utcnow()
    rows = _rows(db, p.org_id, hosts, _site_filter(p, None), kes=True)
    facts = _facts(db, p, hosts)
    metrics = feedback.dashboard_metrics(db, p.org_id, p.site_host if p.scoped else None)
    out = weekly_report.build(rows, facts, metrics, now)
    out["scope"] = {"site_host": p.site_host, "website_id": p.website_id} if p.scoped else None
    out["server_time"] = iso(now)
    return out


@router.post("/finance/analyst/summary")
def analyst_summary(p: Principal = Depends(require("finance:read")), db: Session = Depends(get_db)):
    hosts = _gate(db, p)
    limiter.check(f"cents:{p.id}", 12)
    f = _facts(db, p, hosts)
    base = _fallback_summary(f)
    provider, model = "rules", "deterministic"
    try:
        raw, model = _llm("CONTEXT (JSON)\n" + json.dumps(f, default=str) + "\n\nReturn JSON only with exactly: {\"summary\": string (<=60 words), \"highlights\": [string x3-5], "
                          "\"advice\": [{\"title\": string, \"detail\": string, \"priority\": \"high\"|\"medium\"|\"low\"} x3-5], \"risks\": [string x0-4]}")
        from .llm.service import extract_json

        j = extract_json(raw)
        adv = [{"title": str(a.get("title", ""))[:120], "detail": str(a.get("detail", ""))[:400], "priority": a.get("priority") if a.get("priority") in ("high", "medium", "low") else "medium"}
               for a in (j.get("advice") or []) if isinstance(a, dict)][:6]
        if j.get("summary") and adv:
            base = {"summary": str(j["summary"])[:600], "highlights": [str(x)[:240] for x in (j.get("highlights") or [])][:6] or base["highlights"], "advice": adv,
                    "risks": [str(x)[:240] for x in (j.get("risks") or [])][:5]}
            provider = "gemini"
    except Exception as exc:  # noqa: BLE001 - any model/network failure falls back to the deterministic analyst
        log.warning("Cents AI summary fell back to rules: %s", str(exc)[:160])
    db.commit()
    return {**base, "provider": provider, "model": model, "analyst": ANALYST, "generated_at": iso(utcnow())}


class ChatTurn(BaseModel):
    role: Literal["user", "analyst"]
    text: str = Field(max_length=2000)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=800)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


def _fallback_chat(msg: str, f: dict[str, Any]) -> str:
    m, comp, wc = msg.lower(), f["compliance"], f["working_capital"]
    h = {x["days"]: x for x in f["forecast"]}
    if any(w in m for w in ("lcr", "liquidity coverage", "ratio", "compliance", "quick", "current")):
        fm = lambda v: "n/a" if v is None else f"{v:.2f}"  # noqa: E731
        return f"Current ratio {fm(comp['current_ratio'])} ({comp['current_status']}), quick ratio {fm(comp['quick_ratio'])} ({comp['quick_status']}), liquidity coverage ratio {fm(comp['lcr'])} ({comp['lcr_status']}). These are indicative management metrics, not a regulatory filing."
    if any(w in m for w in ("forecast", "predict", "next", "future", "project")):
        parts = [f"{d} days: net {_fmt(h[d]['net'])}, closing {_fmt(h[d]['closing_cash'])}" for d in (7, 30, 90) if d in h]
        return "Forecast, " + "; ".join(parts) + "." if parts else "There is not enough captured history to forecast yet."
    if any(w in m for w in ("stress", "scenario", "shock", "risk")):
        return "Stress tests: " + "; ".join(f"{r['scenario']} is {r['verdict']}" for r in f["stress"]) + "." if f["stress"] else "No stress results yet."
    if any(w in m for w in ("receivable", "payable", "invoice", "bill", "dso", "dpo", "dio", "inventory", "stock", "working capital")):
        ar, ap = wc["ar"], wc["ap"]
        return (f"Receivables {_fmt(ar['balance'])} (overdue {_fmt(ar['overdue'])}, DSO {ar['dso']}), payables {_fmt(ap['balance'])} (overdue {_fmt(ap['overdue'])}, DPO {ap['dpo']}), "
                f"stock {_fmt(wc['inventory']['value'])} (DIO {wc['inventory']['dio']}). " + (wc["recommendations"][0]["title"] + "." if wc["recommendations"] else ""))
    if any(w in m for w in ("sweep", "pool", "idle")):
        return f"Idle cash is about {_fmt(f['pooling']['idle_cash'])}. " + (f"{len(f['pooling']['proposals'])} sweep(s) are proposed." if f["pooling"]["proposals"] else "No sweeps are proposed; add a rule on the Pooling tab.")
    if any(w in m for w in ("cash", "balance", "bank", "position")):
        return f"Total cash is {_fmt(f['cash_total'])}: " + ", ".join(f"{b['bank']} {_fmt(b['balance_kes'])}" for b in f["banks"][:4]) + "."
    s = _fallback_summary(f)
    return s["summary"] + " Ask me about cash, forecasts, stress tests, working capital, sweeps or ratios."


@router.post("/finance/analyst/chat")
def analyst_chat(body: ChatIn, p: Principal = Depends(require("finance:read")), db: Session = Depends(get_db)):
    hosts = _gate(db, p)
    limiter.check(f"cents:{p.id}", 30)
    f = _facts(db, p, hosts)
    hist = "\n".join(f"{'User' if t.role == 'user' else ANALYST}: {t.text}" for t in body.history[-8:])
    provider, model = "rules", "deterministic"
    try:
        reply, model = _llm("CONTEXT (JSON)\n" + json.dumps(f, default=str) + "\n\nCONVERSATION\n" + hist + f"\nUser: {body.message}\n\nAnswer as {ANALYST} in at most 120 words, plain text, no markdown headings.")
        reply, provider = reply.strip()[:1500], "gemini"
        if not reply:
            raise RuntimeError("empty reply")
    except Exception as exc:  # noqa: BLE001
        log.warning("Cents AI chat fell back to rules: %s", str(exc)[:160])
        reply = _fallback_chat(body.message, f)
    db.commit()
    return {"reply": reply, "provider": provider, "model": model, "analyst": ANALYST}


# ───────────────────────── demo data ─────────────────────────
@router.post("/finance/simulate")
def simulate(days: int = Query(30, ge=7, le=60), p: Principal = Depends(require("finance:control")), db: Session = Depends(get_db)):
    """Flagged, synthetic KES transactions across several banks, with invoices, bills and stock movements, so the page can be explored before a real site reports. Disabled in production."""
    if get_settings().environment == "production":
        raise HTTPException(403, "Simulation is disabled in production")
    _gate(db, p)
    rnd, now = random.Random(7), utcnow()
    q = select(ConnectedSite.host).where(ConnectedSite.org_id == p.org_id)
    if p.scoped:
        q = q.where(ConnectedSite.host == p.site_host)
    sites = list(db.scalars(q).all()) or [p.site_host or "shop.example.com"]
    banks = {"mobile_money": "M-Pesa Paybill", "card": "Equity Bank", "bank_transfer": "KCB Bank", "wallet": "M-Pesa Paybill"}
    n = 0

    def add(key: str, host: str, typ: str, status: str, kes: float, at: datetime, *, cur: str = "KES", method: str | None = None, reason: str | None = None, bank: str = "", due: datetime | None = None) -> None:
        nonlocal n
        amt = kes / fx.rate(cur)
        db.add(FinanceTxn(org_id=p.org_id, client_event_id=key[:80], site_host=host, txn_type=typ, status=status, amount_minor=_minor(amt), currency=cur, method=method, reason=reason,
                          simulated=True, bank=bank, due_at=due, ts=at))
        n += 1

    for host in sites:
        tag = host[:6]
        for d in range(days, -1, -1):
            day = now - timedelta(days=d)
            for i in range(int((10 + (days - d) * 0.35) * (1.25 if day.weekday() in (4, 5) else 0.85) * rnd.uniform(0.8, 1.2))):
                ok = rnd.random() > (0.2 if d < 3 else 0.07)
                at = min(day.replace(hour=rnd.randint(6, 22), minute=rnd.randint(0, 59), second=rnd.randint(0, 59), microsecond=0), now)
                m = rnd.choice(["mobile_money", "mobile_money", "mobile_money", "card", "bank_transfer", "wallet"])
                usd = rnd.random() < 0.08
                kes = round(rnd.lognormvariate(8.1, 0.6), -1)
                add(f"s{tag}{d}-{i}-p", host, "payment", "success" if ok else "failed", kes, at, cur="USD" if usd else "KES", method=m if not usd else "card",
                    reason=None if ok else rnd.choice(["timeout", "card_declined", "insufficient_funds", "network", "fraud_check", "expired_card"]), bank="Stanbic USD" if usd else banks[m])
                if ok and rnd.random() < 0.05:
                    add(f"s{tag}{d}-{i}-r", host, "refund", "success", kes * rnd.uniform(0.3, 1), at, bank=banks[m])
                if ok and rnd.random() < 0.04:
                    add(f"s{tag}{d}-{i}-f", host, "fee", "success", kes * 0.029, at, bank=banks[m])
            if d % 7 == 0 and d:
                add(f"s{tag}{d}-po", host, "payout", "success", rnd.uniform(60000, 140000), day, bank="KCB Bank")
            if d % 10 == 0:  # supplier stock purchase, valued and billed
                v = round(rnd.uniform(90000, 220000), -2)
                add(f"s{tag}{d}-ii", host, "inventory_in", "success", v, day)
                st = "pending" if d < 25 and rnd.random() < 0.6 else "success"
                add(f"s{tag}{d}-bill", host, "bill", st, v * 0.9, day, bank="KCB Bank", due=day + timedelta(days=rnd.choice([14, 30, 45])))
            if d % 3 == 0:
                add(f"s{tag}{d}-io", host, "inventory_out", "success", rnd.uniform(25000, 70000), day)
            if d % 5 == 0:  # credit sale to a business customer
                v = round(rnd.uniform(45000, 380000), -2)
                paid = d > 22 or rnd.random() < 0.35
                add(f"s{tag}{d}-inv", host, "invoice", "success" if paid else "pending", v, day, bank="Equity Bank", due=day + timedelta(days=30))
    audit(db, p.org_id, p.actor, "finance_simulated", "plan", p.org_id, None, None, {"transactions": n})
    notify(db, p.org_id, {"type": "finance_update"})
    db.commit()
    return {"transactions": n, "simulated": True}
