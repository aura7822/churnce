"""Dashboard email hub for website-ID sessions: how many emails were sent and to whom, plus the auto-send switch.

Settings live in `OrgPlan.finance["email_auto"]` keyed by website host ("*" for the whole organisation), so a website owner's choice never
changes another website's behaviour. Sending reuses `outreach._send_one`, which re-checks consent, suppression, contact frequency and
resolved-issue policy at send time and claims the row so no email can go out twice."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import mailer, scope as scp
from .audit import audit
from .database import get_db, notify
from .models import Communication, Customer, Incident, MonitoringConfig, OrgPlan, SessionRec
from .plans import doc, get_plan, save_finance
from .security import Principal, require
from .utils import iso, utcnow

log = logging.getLogger("churnce.emailhub")
router = APIRouter()
MAX_PER_RUN = 25


def _key(p: Principal) -> str:
    return p.site_host or "*"


def _mask(email: str | None) -> str:
    if not email or "@" not in email:
        return email or ""
    u, _, h = email.partition("@")
    return f"{u[:1]}***@{h}"


def _auto(row: OrgPlan, key: str) -> dict[str, Any]:
    a = (doc(row).get("email_auto") or {}).get(key) or {}
    return {"enabled": bool(a.get("enabled", False)), "delay_minutes": int(a.get("delay_minutes", 15)), "smtp_configured": mailer.configured()}


def _base(p: Principal, db: Session):
    q = select(Communication).where(Communication.org_id == p.org_id)
    if p.scoped:
        q = q.where(Communication.customer_id.in_(scp.customer_ids(db, p) or {"-"}))
    return q


@router.get("/emails/summary")
def emails_summary(p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    base = _base(p, db).subquery()
    counts = dict(db.execute(select(base.c.status, func.count()).group_by(base.c.status)).all())
    sent = db.scalars(_base(p, db).where(Communication.status.in_(["sent", "sent_simulated"])).order_by(Communication.sent_at.desc()).limit(100)).all()
    custs = {c.id: c for c in db.scalars(select(Customer).where(Customer.id.in_({s.customer_id for s in sent}))).all()} if sent else {}
    incs = {i.id: i for i in db.scalars(select(Incident).where(Incident.id.in_({s.incident_id for s in sent}))).all()} if sent else {}
    full = p.role in ("administrator", "website_owner")
    recipients = [{"id": s.id, "customer_ref": custs[s.customer_id].ref if s.customer_id in custs else "", "email_masked": _mask(custs[s.customer_id].email) if s.customer_id in custs else "",
                   "email": (custs[s.customer_id].email if full and s.customer_id in custs else None), "subject": s.subject, "sent_at": iso(s.sent_at),
                   "delivery": "smtp" if s.status == "sent" else "simulated", "issue": incs[s.incident_id].title if s.incident_id in incs else ""} for s in sent]
    row = get_plan(db, p.org_id)
    db.commit()
    return {"sent_count": counts.get("sent", 0) + counts.get("sent_simulated", 0), "simulated_count": counts.get("sent_simulated", 0), "draft_count": counts.get("draft", 0) + counts.get("approved", 0),
            "blocked_count": counts.get("blocked", 0), "auto_send": _auto(row, _key(p)), "recipients": recipients, "server_time": iso(utcnow())}


class AutoIn(BaseModel):
    enabled: bool
    delay_minutes: int = Field(default=15, ge=0, le=1440)


@router.put("/emails/auto-send")
def set_auto_send(body: AutoIn, p: Principal = Depends(require("emails:approve")), db: Session = Depends(get_db)):
    row = get_plan(db, p.org_id)
    allm = dict(doc(row).get("email_auto") or {})
    allm[_key(p)] = {"enabled": body.enabled, "delay_minutes": body.delay_minutes}
    save_finance(row, email_auto=allm)
    audit(db, p.org_id, p.actor, "email_auto_send_changed", "plan", p.org_id, None, None, {"scope": _key(p), "enabled": body.enabled, "delay_minutes": body.delay_minutes})
    db.commit()
    return _auto(row, _key(p))


def auto_send_all(db: Session) -> int:
    """Scheduler step: send drafts that are older than the configured delay for every scope with auto-send switched on."""
    from .outreach import _send_one

    sent = 0
    for row in db.scalars(select(OrgPlan)).all():
        rules = {k: v for k, v in (doc(row).get("email_auto") or {}).items() if v.get("enabled")}
        if not rules:
            continue
        cfg = db.scalar(select(MonitoringConfig).where(MonitoringConfig.org_id == row.org_id))
        if not cfg:
            continue
        for key, rule in rules.items():
            cutoff = utcnow() - timedelta(minutes=int(rule.get("delay_minutes", 15)))
            q = select(Communication).where(Communication.org_id == row.org_id, Communication.status.in_(["draft", "approved"]), Communication.holdout.is_(False), Communication.created_at <= cutoff)
            if key != "*":
                cids = {c for c in db.scalars(select(SessionRec.customer_id).where(SessionRec.org_id == row.org_id, SessionRec.site_host == key, SessionRec.customer_id.is_not(None))).all() if c}
                q = q.where(Communication.customer_id.in_(cids or {"-"}))
            for c in db.scalars(q.order_by(Communication.created_at).limit(MAX_PER_RUN)).all():
                try:
                    if _send_one(db, cfg, c, "auto-send") in ("sent", "simulated"):
                        sent += 1
                except Exception:  # noqa: BLE001 - one bad recipient must not stop the batch
                    log.exception("auto-send failed for %s", c.id)
                    db.rollback()
                db.commit()
    return sent
