"""Extension-facing customer outreach: list the per-issue win-back emails, edit them, send them (or let auto-send do it).

Security model
· The browser extension never sees a customer's address and never talks to a mail server. It asks the backend,
  which applies the same consent / suppression / frequency / resolved-issue checks as the dashboard before every send.
· It authenticates with a dedicated OUTREACH key (X-Churnce-Outreach-Key), separate from the write-only ingest key,
  derived from the server secret and the tenant's current ingest key (rotating the ingest key rotates this one too).
· The whole feature is off until the operator sets OUTREACH_ENABLED=true on the server.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from . import mailer
from .audit import audit
from .communications import customer_checks
from .config import get_settings
from .database import get_db, notify
from .llm.service import BANNED_EMAIL_TERMS
from .models import Communication, Customer, Incident, MonitoringConfig, Resolution
from .security import Principal, require
from .utils import utcnow

log = logging.getLogger("churnce.outreach")
settings = get_settings()
router = APIRouter()
MAX_PER_RUN = int(os.environ.get("OUTREACH_MAX_PER_RUN", "50"))


def enabled() -> bool:
    return os.environ.get("OUTREACH_ENABLED", "").lower() in ("1", "true", "yes")


# ── Key handling ──────────────────────────────────────────────────────────────
def _mac(cfg: MonitoringConfig) -> str:
    return hmac.new(settings.jwt_secret.encode(), f"outreach:{cfg.id}:{cfg.ingest_key_hash}".encode(), hashlib.sha256).hexdigest()[:40]


def outreach_key(cfg: MonitoringConfig) -> str:
    return f"chn_out_{cfg.id}_{_mac(cfg)}"


def outreach_cfg(x_churnce_outreach_key: str | None = Header(default=None), db: Session = Depends(get_db)) -> MonitoringConfig:
    if not enabled():
        raise HTTPException(403, "Outreach is disabled on this server (set OUTREACH_ENABLED=true)")
    key = x_churnce_outreach_key or ""
    prefix, _, mac = key.rpartition("_")
    cfg = db.get(MonitoringConfig, prefix.removeprefix("chn_out_")) if prefix.startswith("chn_out_") else None
    if not cfg or not hmac.compare_digest(mac, _mac(cfg)):
        raise HTTPException(401, "Invalid outreach key")
    return cfg


@router.get("/config/outreach-key")
def get_outreach_key(p: Principal = Depends(require("config:write")), db: Session = Depends(get_db)):
    cfg = db.scalar(select(MonitoringConfig).where(MonitoringConfig.org_id == p.org_id))
    audit(db, p.org_id, p.actor, "outreach_key_viewed", "config", cfg.id)
    db.commit()
    return {"outreach_key": outreach_key(cfg), "enabled": enabled(), "smtp_configured": mailer.smtp_configured()}


# ── Helpers ───────────────────────────────────────────────────────────────────
class EditIn(BaseModel):
    subject: str = Field(min_length=3, max_length=120)
    body: str = Field(min_length=20, max_length=1500)


def edit_problems(cfg: MonitoringConfig, subject: str, body: str) -> list[str]:
    problems = []
    if BANNED_EMAIL_TERMS.search(subject + " " + body):
        problems.append("mentions the technical defect or uses apologetic/failure language")
    if cfg.cta_url not in body:
        problems.append(f"must keep the call-to-action link {cfg.cta_url}")
    return problems


def _issues(db: Session, cfg: MonitoringConfig) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Communication).where(Communication.org_id == cfg.org_id, Communication.status.in_(["draft", "approved"]), Communication.holdout.is_(False))
        .order_by(Communication.created_at)
    ).all()
    grouped: dict[str, list[Communication]] = {}
    for c in rows:
        grouped.setdefault(c.incident_id, []).append(c)
    out = []
    for inc_id, comms in grouped.items():
        inc, res = db.get(Incident, inc_id), db.get(Resolution, comms[0].resolution_id)
        first = comms[0]
        out.append({
            "incident_id": inc_id, "title": inc.title if inc else inc_id, "journey_stage": inc.journey_stage if inc else "",
            "recipients": len(comms), "subject": first.subject, "body": first.body, "claims_used": first.claims_used,
            "resolution_verified": bool(res and res.status == "verified"), "generated_by": first.generated_by,
        })
    return out


def _send_one(db: Session, cfg: MonitoringConfig, comm: Communication, actor: str) -> str:
    """Returns sent | simulated | blocked | failed. Policy is re-checked at send time."""
    inc, res, cust = db.get(Incident, comm.incident_id), db.get(Resolution, comm.resolution_id), db.get(Customer, comm.customer_id)
    checks = customer_checks(db, cust, inc, res, cfg, inc.first_seen_at)
    if not cust.email:
        checks.append({"name": "email_address", "passed": False, "detail": "no email address on file"})
    failed = [c for c in checks if not c["passed"]]
    if failed:
        comm.status, comm.policy_result = "blocked", {"checks": checks}
        audit(db, cfg.org_id, actor, "email_blocked_at_send", "communication", comm.id, None, "blocked", {"failed": [c["name"] for c in failed]})
        notify(db, cfg.org_id, {"type": "communication_updated", "communication_id": comm.id})
        return "blocked"
    # Claim the row so two runs (manual + auto) can never send the same email twice.
    claimed = db.execute(update(Communication).where(Communication.id == comm.id, Communication.status.in_(["draft", "approved"])).values(status="sending"))
    if claimed.rowcount != 1:
        return "blocked"
    db.commit()
    try:
        mode = mailer.send(cust.email, comm.subject, comm.body)
    except Exception as exc:  # noqa: BLE001  (network, auth, rejected recipient)
        comm.status, comm.approved_by = "approved", actor
        comm.policy_result = {"checks": checks, "send_error": str(exc)[:200]}
        log.error("Email send failed for %s: %s", comm.id, str(exc)[:200])
        return "failed"
    comm.status = "sent" if mode == "smtp" else "sent_simulated"
    comm.approved_by, comm.approved_at, comm.sent_at = actor, comm.approved_at or utcnow(), utcnow()
    comm.policy_result = {"checks": checks}
    cust.last_contacted_at = comm.sent_at
    audit(db, cfg.org_id, actor, "email_sent" if mode == "smtp" else "email_sent_simulated", "communication", comm.id, "approved", comm.status, {"via": "extension"})
    notify(db, cfg.org_id, {"type": "communication_updated", "communication_id": comm.id})
    return "sent" if mode == "smtp" else "simulated"


def _send_issue(db: Session, cfg: MonitoringConfig, incident_id: str, actor: str, budget: int) -> dict[str, int]:
    tally = {"sent": 0, "simulated": 0, "blocked": 0, "failed": 0, "remaining": 0}
    comms = db.scalars(select(Communication).where(
        Communication.org_id == cfg.org_id, Communication.incident_id == incident_id,
        Communication.status.in_(["draft", "approved"]), Communication.holdout.is_(False))).all()
    for i, c in enumerate(comms):
        if i >= budget:
            tally["remaining"] += 1
            continue
        tally[_send_one(db, cfg, c, actor)] += 1
        db.commit()
    return tally


# ── Extension API ─────────────────────────────────────────────────────────────
@router.get("/ext/outreach")
def list_outreach(cfg: MonitoringConfig = Depends(outreach_cfg), db: Session = Depends(get_db)):
    return {"issues": _issues(db, cfg), "smtp_configured": mailer.smtp_configured(), "max_per_run": MAX_PER_RUN}


@router.patch("/ext/outreach/{incident_id}")
def edit_outreach(incident_id: str, body: EditIn, cfg: MonitoringConfig = Depends(outreach_cfg), db: Session = Depends(get_db)):
    problems = edit_problems(cfg, body.subject, body.body)
    if problems:
        raise HTTPException(422, "Email rejected: " + "; ".join(problems))
    res = db.execute(update(Communication).where(
        Communication.org_id == cfg.org_id, Communication.incident_id == incident_id, Communication.status == "draft",
    ).values(subject=body.subject.strip(), body=body.body.strip()))
    if res.rowcount == 0:
        raise HTTPException(404, "No editable drafts for this issue")
    audit(db, cfg.org_id, "extension", "outreach_edited", "incident", incident_id, None, None, {"drafts": res.rowcount})
    db.commit()
    return {"updated": res.rowcount}


@router.post("/ext/outreach/{incident_id}/send")
def send_outreach(incident_id: str, cfg: MonitoringConfig = Depends(outreach_cfg), db: Session = Depends(get_db)):
    tally = _send_issue(db, cfg, incident_id, "extension", MAX_PER_RUN)
    return {**tally, "mode": "smtp" if mailer.smtp_configured() else "simulated"}


@router.post("/ext/outreach/auto-send")
def auto_send(cfg: MonitoringConfig = Depends(outreach_cfg), db: Session = Depends(get_db)):
    """Called by the extension's auto-send timer. Same checks and the same per-run cap as a manual send."""
    total = {"sent": 0, "simulated": 0, "blocked": 0, "failed": 0, "remaining": 0}
    budget = MAX_PER_RUN
    for issue in _issues(db, cfg):
        if budget <= 0:
            break
        t = _send_issue(db, cfg, issue["incident_id"], "extension:auto", budget)
        budget -= t["sent"] + t["simulated"] + t["failed"]
        for k, v in t.items():
            total[k] += v
    return {**total, "mode": "smtp" if mailer.smtp_configured() else "simulated"}
