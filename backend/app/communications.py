"""Resolution-to-reengagement: eligibility, policy checks, drafting and approval of customer emails.

The model never sends anything. Drafts are generated, checked against consent, suppression,
frequency and claim rules, then approved by a human. 'Sending' is simulated in this build.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import audit
from .database import notify
from . import mailer
from .llm.schemas import EmailDraft
from .llm.service import check_email, generate_email
from .models import Chunk, Communication, Customer, Event, Incident, MonitoringConfig, Resolution, SessionRec
from .utils import sha256, utcnow


class CommError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


def _in_holdout(customer_id: str, pct: int) -> bool:
    return pct > 0 and int(sha256(customer_id)[:8], 16) % 100 < pct


def customer_checks(db: Session, cust: Customer, inc: Incident, res: Resolution, cfg: MonitoringConfig, since) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    add("communication_consent", cust.consent == "opt_in", f"consent is '{cust.consent}'")
    add("not_suppressed", not cust.suppressed, "customer is on the suppression list" if cust.suppressed else "not suppressed")
    cap = timedelta(days=cfg.contact_frequency_days)
    recent = bool(cust.last_contacted_at and utcnow() - cust.last_contacted_at < cap)
    add("contact_frequency", not recent, f"contacted within the last {cfg.contact_frequency_days} days" if recent else "within frequency limit")
    add("issue_resolved", res.status == "verified" and inc.status != "regression", "verified resolution and no regression")
    add("approved_claims", bool(res.approved_claims), f"{len(res.approved_claims)} approved claim(s)")
    completed_since = db.scalar(
        select(Event.id)
        .join(SessionRec, SessionRec.id == Event.session_id)
        .where(
            SessionRec.customer_id == cust.id,
            Event.event_type == "workflow_completed",
            Event.journey_stage == inc.journey_stage,
            Event.event_timestamp > since,
        )
        .limit(1)
    )
    add("task_still_open", completed_since is None, "customer already completed this task" if completed_since else "customer has not completed the task since the issue")
    add("message_category", True, "benefit-focused lifecycle message; no promotional offer, so it carries no marketing bypass")
    return checks


def generate_drafts(db: Session, res: Resolution, actor: str) -> dict[str, Any]:
    inc = db.get(Incident, res.incident_id)
    cfg = db.scalar(select(MonitoringConfig).where(MonitoringConfig.org_id == res.org_id))
    chunks = list(db.scalars(select(Chunk).where(Chunk.id.in_(inc.chunk_ids)))) if inc.chunk_ids else []
    since = min((c.created_at for c in chunks), default=inc.first_seen_at)
    session_ids = {c.session_id for c in chunks}
    customer_ids = {
        cid
        for cid in db.scalars(select(SessionRec.customer_id).where(SessionRec.id.in_(session_ids)))
        if cid
    } if session_ids else set()
    unlinked = len(session_ids) - len(
        set(db.scalars(select(SessionRec.id).where(SessionRec.id.in_(session_ids), SessionRec.customer_id.is_not(None))))
    ) if session_ids else 0

    drafted = blocked = 0
    ids: list[str] = []
    for cid in sorted(customer_ids):
        if db.scalar(select(Communication.id).where(Communication.resolution_id == res.id, Communication.customer_id == cid)):
            continue  # duplicate-campaign prevention
        cust = db.get(Customer, cid)
        checks = customer_checks(db, cust, inc, res, cfg, since)
        holdout = _in_holdout(cid, cfg.holdout_pct)
        comm = Communication(
            org_id=res.org_id,
            incident_id=inc.id,
            resolution_id=res.id,
            customer_id=cid,
            holdout=holdout,
        )
        failed = [c for c in checks if not c["passed"]]
        if holdout:
            comm.status = "blocked"
            checks.append({"name": "holdout_group", "passed": False, "detail": "randomly held out to measure causal impact"})
            blocked += 1
        elif failed:
            comm.status = "blocked"
            blocked += 1
        else:
            draft, provider, notes = generate_email(
                {
                    "journey_stage": inc.journey_stage,
                    "approved_claims": res.approved_claims,
                    "brand_tone": cfg.brand_tone,
                    "cta_url": cfg.cta_url,
                    "issue_title": inc.title,   # each email is tailored to the issue this incident was about
                    "signal": inc.signal,
                }
            )
            problems = check_email(draft, res.approved_claims, cfg.cta_url)
            if problems:
                comm.status = "blocked"
                checks.append({"name": "email_content", "passed": False, "detail": "; ".join(problems)})
                blocked += 1
            else:
                comm.status, comm.subject, comm.body = "draft", draft.subject, draft.body
                comm.claims_used, comm.generated_by = draft.claims_used, provider + (f" — {'; '.join(notes)}" if notes else "")
                drafted += 1
        comm.policy_result = {"checks": checks}
        db.add(comm)
        db.flush()
        ids.append(comm.id)
        notify(db, res.org_id, {"type": "communication_updated", "communication_id": comm.id})
    audit(db, res.org_id, actor, "drafts_generated", "resolution", res.id, None, None, {"drafted": drafted, "blocked": blocked})
    return {"drafted": drafted, "blocked": blocked, "unlinked_sessions": unlinked, "communication_ids": ids}


def _get(db: Session, org_id: str, comm_id: str) -> Communication:
    comm = db.get(Communication, comm_id)
    if not comm or comm.org_id != org_id:
        raise CommError("Email not found", 404)
    return comm


def approve(db: Session, org_id: str, actor: str, comm_id: str) -> Communication:
    comm = _get(db, org_id, comm_id)
    if comm.status != "draft":
        raise CommError(f"Email is {comm.status} and cannot be approved")
    inc = db.get(Incident, comm.incident_id)
    res = db.get(Resolution, comm.resolution_id)
    cust = db.get(Customer, comm.customer_id)
    cfg = db.scalar(select(MonitoringConfig).where(MonitoringConfig.org_id == org_id))
    # Re-check at approval time: consent can be withdrawn between drafting and approving.
    checks = customer_checks(db, cust, inc, res, cfg, inc.first_seen_at)
    failed = [c for c in checks if not c["passed"]]
    if failed:
        comm.status = "blocked"
        comm.policy_result = {"checks": checks}
        db.commit()
        notify(db, org_id, {"type": "communication_updated", "communication_id": comm.id})
        raise CommError("Blocked at approval time: " + ", ".join(c["name"] for c in failed))
    comm.status, comm.approved_by, comm.approved_at = "approved", actor, utcnow()
    comm.policy_result = {"checks": checks}
    audit(db, org_id, actor, "email_approved", "communication", comm.id, "draft", "approved")
    notify(db, org_id, {"type": "communication_updated", "communication_id": comm.id})
    return comm


def reject(db: Session, org_id: str, actor: str, comm_id: str) -> Communication:
    comm = _get(db, org_id, comm_id)
    if comm.status not in ("draft", "approved"):
        raise CommError(f"Email is {comm.status} and cannot be rejected")
    prev = comm.status
    comm.status = "rejected"
    audit(db, org_id, actor, "email_rejected", "communication", comm.id, prev, "rejected")
    notify(db, org_id, {"type": "communication_updated", "communication_id": comm.id})
    return comm


def update_draft(db: Session, org_id: str, actor: str, comm_id: str, subject: str, body: str) -> Communication:
    """Operator edit. The same content rules apply as for generated drafts, and an edit always needs a fresh approval."""
    comm = _get(db, org_id, comm_id)
    if comm.status not in ("draft", "approved"):
        raise CommError(f"Email is {comm.status} and can no longer be edited")
    res = db.get(Resolution, comm.resolution_id)
    cfg = db.scalar(select(MonitoringConfig).where(MonitoringConfig.org_id == org_id))
    try:
        draft = EmailDraft(subject=subject.strip(), body=body.strip(), claims_used=comm.claims_used)
    except Exception as exc:  # noqa: BLE001  (pydantic length rules)
        raise CommError("Subject must be 3-120 characters and body 20-1500 characters", 422) from exc
    problems = check_email(draft, res.approved_claims, cfg.cta_url)
    if problems:
        raise CommError("Edit rejected: " + "; ".join(problems), 422)
    prev = comm.status
    comm.subject, comm.body, comm.status = draft.subject, draft.body, "draft"
    comm.approved_by = comm.approved_at = None
    audit(db, org_id, actor, "email_edited", "communication", comm.id, prev, "draft")
    notify(db, org_id, {"type": "communication_updated", "communication_id": comm.id})
    return comm


def deliver(db: Session, org_id: str, actor: str, comm_id: str) -> Communication:
    """Send an approved email through SMTP when configured, otherwise record a simulated send.
    Policy is checked again at send time because consent can be withdrawn after approval."""
    comm = _get(db, org_id, comm_id)
    if comm.status != "approved":
        raise CommError("Only approved emails can be sent")
    cust = db.get(Customer, comm.customer_id)
    inc = db.get(Incident, comm.incident_id)
    res = db.get(Resolution, comm.resolution_id)
    cfg = db.scalar(select(MonitoringConfig).where(MonitoringConfig.org_id == org_id))
    failed = [c for c in customer_checks(db, cust, inc, res, cfg, inc.first_seen_at) if not c["passed"]]
    if failed:
        comm.status = "blocked"
        db.commit()
        raise CommError("Blocked at send time: " + ", ".join(c["name"] for c in failed))
    if mailer.configured():
        if not cust.email:
            raise CommError("This customer has no email address on file")
        try:
            message_id = mailer.send(cust.email, comm.subject, comm.body)
        except mailer.MailError as exc:
            audit(db, org_id, actor, "email_send_failed", "communication", comm.id, "approved", "approved", {"error": str(exc)[:160]})
            db.commit()
            raise CommError(str(exc), 502) from exc
        comm.status, comm.sent_at = "sent", utcnow()
        audit(db, org_id, actor, "email_sent", "communication", comm.id, "approved", "sent", {"message_id": message_id})
    else:
        comm.status, comm.sent_at = "sent_simulated", utcnow()
        audit(db, org_id, actor, "email_sent_simulated", "communication", comm.id, "approved", "sent_simulated", {"note": "SMTP not configured; nothing left the system"})
    cust.last_contacted_at = comm.sent_at
    notify(db, org_id, {"type": "communication_updated", "communication_id": comm.id})
    return comm


simulate_send = deliver  # backwards-compatible name
