"""Next-best-action engine. The model proposes; this module decides what is permitted.

Scoring is a transparent weighted sum (no model-invented priorities) and every proposal is
passed through explicit policy checks before a human ever sees it.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .audit import audit
from .database import notify
from .enums import (
    ACTION_CATEGORY,
    AUTO_EXECUTE,
    OUTBOUND_MARKETING,
    PRIORITIES,
    STAGE_BUSINESS_WEIGHT,
    ActionStatus,
)
from .llm.schemas import IncidentAnalysis
from .models import Action, Chunk, Incident, Intervention, Resolution
from .privacy import injection_suspected
from .utils import new_id, sha256, utcnow

log = logging.getLogger("churnce.actions")

SEVERITY_VALUE = {"low": 0.25, "medium": 0.5, "high": 0.75, "critical": 1.0}
EFFORT_EASE = {  # higher = cheaper to do
    "track_metric": 0.95,
    "journey_summary": 0.9,
    "bug_reproduction_summary": 0.8,
    "create_issue_report": 0.75,
    "support_escalation": 0.7,
    "suppress_campaign": 0.85,
    "engineering_investigation": 0.6,
    "performance_investigation": 0.5,
    "ux_improvement": 0.4,
    "kb_improvement": 0.6,
    "feature_suggestion": 0.3,
    "segment_investigation": 0.7,
    "run_experiment": 0.4,
    "compare_interventions": 0.7,
    "reengagement_email": 0.8,
    "onboarding_reminder": 0.8,
    "feature_announcement": 0.7,
    "recovery_communication": 0.8,
}
WEIGHTS = {
    "severity": 0.22,
    "affected_journeys": 0.18,
    "evidence_strength": 0.16,
    "business_impact": 0.14,
    "customer_harm": 0.12,
    "diagnosis_confidence": 0.12,
    "ease_of_implementation": 0.06,
}


def top_confidence(inc: Incident) -> float:
    return max((h.get("confidence", 0.0) for h in inc.hypotheses), default=0.0)


def score_action(inc: Incident, action_type: str, eligible: bool) -> tuple[float, dict[str, Any]]:
    sev = SEVERITY_VALUE.get(inc.severity, 0.5)
    impact = STAGE_BUSINESS_WEIGHT.get(inc.journey_stage, 0.5)
    factors = {
        "severity": sev,
        "affected_journeys": min(inc.affected_sessions / 10, 1.0),
        "evidence_strength": min(len(inc.evidence_ids) / 5, 1.0),
        "business_impact": impact,
        "customer_harm": round((sev + impact) / 2, 3),
        "diagnosis_confidence": top_confidence(inc),
        "ease_of_implementation": EFFORT_EASE.get(action_type, 0.5),
    }
    total = sum(WEIGHTS[k] * v for k, v in factors.items()) * (1.0 if eligible else 0.0)
    breakdown = {
        "factors": {k: round(v, 3) for k, v in factors.items()},
        "weights": WEIGHTS,
        "eligible": eligible,
    }
    return round(total * 100, 1), breakdown


# ── Policy ─────────────────────────────────────────────────────────────────────
def evaluate_policy(db: Session, inc: Incident, action_type: str, reason: str = "") -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    category = ACTION_CATEGORY.get(action_type)
    add("known_action_type", category is not None, f"{action_type} → {category or 'unknown'}")
    if category is None:
        return {"allowed": False, "requires_approval": True, "checks": checks}

    if category in ("engineering", "support"):
        add("evidence_present", len(inc.evidence_ids) >= 1, f"{len(inc.evidence_ids)} supporting evidence id(s)")
    if action_type == "engineering_investigation":
        add("confidence_floor", top_confidence(inc) >= 0.4, f"top hypothesis confidence {top_confidence(inc):.2f} (minimum 0.40)")

    resolution = db.get(Resolution, inc.resolution_id) if inc.resolution_id else None
    verified = bool(resolution and resolution.status == "verified" and resolution.email_eligible)
    if action_type in OUTBOUND_MARKETING:
        add("issue_resolved_and_verified", verified and inc.status != "regression", "outbound messaging requires a verified, non-regressed resolution")
        add("approved_claims_available", bool(resolution and resolution.approved_claims), "message may only cite approved claims")
    if action_type == "suppress_campaign":
        add("issue_unresolved", not verified, "suppression only makes sense while the issue is open")

    add("no_injected_instructions", not injection_suspected(reason), "rationale scanned for instruction-like content")
    approval = action_type not in AUTO_EXECUTE
    add("approval_requirement", True, "human approval required" if approval else "internal, reversible: auto-executes")
    return {"allowed": all(c["passed"] for c in checks), "requires_approval": approval, "checks": checks}


# ── Payloads ───────────────────────────────────────────────────────────────────
def _repro(db: Session, inc: Incident) -> list[str]:
    for cid in inc.chunk_ids:
        c = db.get(Chunk, cid)
        if c and c.events:
            return [f"{i + 1}. {line}" for i, line in enumerate(c.events[:8])]
    return []


def build_payload(db: Session, inc: Incident, action_type: str, reason: str, resolution_id: str | None) -> dict[str, Any]:
    category = ACTION_CATEGORY[action_type]
    if category in ("engineering", "support"):
        facts = "\n".join(f"- {f}" for f in inc.observed_facts) or "- (none recorded)"
        hyps = "\n".join(f"- ({h.get('confidence', 0):.0%} model estimate) {h['description']}" for h in inc.hypotheses)
        steps = "\n".join(_repro(db, inc)) or "(no reproduction steps recorded)"
        body = (
            f"## Summary\n{inc.title}\n\n## Observed facts\n{facts}\n\n## Hypotheses (unverified)\n{hyps}\n\n"
            f"## Representative journey\n{steps}\n\n## Evidence\n" + ", ".join(inc.evidence_ids) +
            f"\n\n## Open questions\n" + "\n".join(f"- {q}" for q in inc.unresolved_questions)
        )
        return {"kind": "ticket", "title": inc.title[:200], "body": body, "labels": [inc.journey_stage, inc.signal, "churnce"], "target": "simulated_issue_tracker"}
    if action_type == "suppress_campaign":
        return {"kind": "suppression", "scope": inc.journey_stage, "until": "verified resolution", "reason": reason}
    if action_type == "track_metric":
        return {"kind": "metric", "metric": "workflow_completion_rate", "stage": inc.journey_stage}
    if action_type in OUTBOUND_MARKETING:
        return {"kind": "email_campaign", "resolution_id": resolution_id, "mode": "draft_for_approval"}
    return {"kind": "analysis", "note": reason}


def _make_action(db: Session, inc: Incident, action_type: str, reason: str, priority: str, resolution_id: str | None = None, role: str = "primary") -> Action | None:
    key = f"{inc.id}:{action_type}:{resolution_id or ''}"
    existing = db.scalar(select(Action).where(Action.org_id == inc.org_id, Action.idempotency_key == key))
    if existing:
        return existing  # idempotent: re-analysis never duplicates work

    category = ACTION_CATEGORY[action_type]
    policy = evaluate_policy(db, inc, action_type, reason)
    score, breakdown = score_action(inc, action_type, policy["allowed"])
    if not policy["allowed"]:
        status = ActionStatus.POLICY_REJECTED
    elif policy["requires_approval"]:
        status = ActionStatus.AWAITING
    else:
        status = ActionStatus.APPROVED
    act = Action(
        org_id=inc.org_id,
        incident_id=inc.id,
        resolution_id=resolution_id,
        type=action_type,
        category=category,
        title=_title(inc, action_type),
        rationale=reason,
        priority=priority if priority in PRIORITIES else "medium",
        score=score,
        score_breakdown=breakdown,
        payload={**build_payload(db, inc, action_type, reason, resolution_id), "role": role},
        status=status,
        policy_result=policy,
        idempotency_key=key,
    )
    db.add(act)
    db.flush()
    audit(db, inc.org_id, "system", "action_proposed", "action", act.id, None, status, {"type": action_type, "score": score})
    notify(db, inc.org_id, {"type": "action_updated", "action_id": act.id, "incident_id": inc.id})
    if status == ActionStatus.APPROVED:
        act.decided_by, act.decided_at = "auto-policy", utcnow()
        execute(db, act, "auto-policy")
    return act


TITLES = {
    "engineering_investigation": "Investigate {stage} reliability",
    "bug_reproduction_summary": "Reproduce and document {stage} failure",
    "performance_investigation": "Investigate {stage} performance",
    "ux_improvement": "Improve {stage} flow",
    "feature_suggestion": "Review missing capability in {stage}",
    "segment_investigation": "Investigate affected {stage} segment",
    "support_escalation": "Escalate {stage} issue to support",
    "suppress_campaign": "Pause {stage} campaigns until the fix is verified",
    "track_metric": "Track {stage} completion before and after",
    "reengagement_email": "Prepare benefit-focused re-engagement emails",
    "recovery_communication": "Prepare recovery communication",
    "onboarding_reminder": "Draft onboarding reminder",
    "feature_announcement": "Prepare feature announcement",
}


def _title(inc: Incident, action_type: str) -> str:
    return TITLES.get(action_type, action_type.replace("_", " ").capitalize() + " ({stage})").format(stage=inc.journey_stage.replace("_", " "))


def propose_actions(db: Session, inc: Incident, analysis: IncidentAnalysis) -> list[Action]:
    rec = analysis.recommended_action
    proposed: list[Action] = []

    # A changed recommendation supersedes the earlier primary proposal that nobody has acted on.
    for old in db.scalars(
        select(Action).where(Action.incident_id == inc.id, Action.status == ActionStatus.AWAITING)
    ):
        if old.payload.get("role") == "primary" and old.type != rec.type and not old.resolution_id:
            old.status = ActionStatus.DECLINED
            old.decided_by, old.decided_at = "system", utcnow()
            old.rationale += " [Superseded by a newer analysis]"
            audit(db, inc.org_id, "system", "action_superseded", "action", old.id, ActionStatus.AWAITING, ActionStatus.DECLINED)

    primary = _make_action(db, inc, rec.type, rec.reason, rec.priority)
    if primary and primary.status == ActionStatus.POLICY_REJECTED:
        # Fail safe: investigate rather than act on thin evidence.
        fallback = _make_action(
            db, inc, "segment_investigation",
            f"Policy blocked '{rec.type}' ({_failed(primary)}); gather more evidence first.", "medium", role="fallback",
        )
        proposed.append(primary)
        if fallback:
            proposed.append(fallback)
    elif primary:
        proposed.append(primary)

    if inc.severity in ("high", "critical") and inc.status != "resolved":
        sup = _make_action(db, inc, "suppress_campaign", "Customers hitting this friction should not receive promotions until it is fixed.", "medium", role="guard")
        if sup:
            proposed.append(sup)
    trk = _make_action(db, inc, "track_metric", "Capture a baseline now so the fix can be measured later.", "low", role="measure")
    if trk:
        proposed.append(trk)
    if any(a.status == ActionStatus.AWAITING for a in proposed):
        inc.status = "action_pending"
    return proposed


def _failed(act: Action) -> str:
    return "; ".join(c["name"] for c in act.policy_result.get("checks", []) if not c["passed"]) or "policy"


# ── Lifecycle ──────────────────────────────────────────────────────────────────
class ActionError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


def _claim(db: Session, action_id: str, from_states: list[str], to_state: str, actor: str) -> Action | None:
    prev = db.scalar(select(Action.status).where(Action.id == action_id))
    res = db.execute(
        update(Action)
        .where(Action.id == action_id, Action.status.in_(from_states))
        .values(status=to_state, updated_at=utcnow(), decided_by=actor, decided_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        return None
    act = db.get(Action, action_id)
    db.refresh(act)
    audit(db, act.org_id, actor, "action_state", "action", act.id, prev, to_state)
    notify(db, act.org_id, {"type": "action_updated", "action_id": act.id, "incident_id": act.incident_id})
    return act


def approve(db: Session, action_id: str, org_id: str, actor: str) -> Action:
    act = db.get(Action, action_id)
    if not act or act.org_id != org_id:
        raise ActionError("Action not found", 404)
    # Re-run policy at approval time: the world may have changed since it was proposed.
    inc = db.get(Incident, act.incident_id)
    policy = evaluate_policy(db, inc, act.type, act.rationale)
    if not policy["allowed"]:
        act.policy_result = policy
        act.status = ActionStatus.POLICY_REJECTED
        audit(db, org_id, "system", "action_policy_rejected", "action", act.id, ActionStatus.AWAITING, ActionStatus.POLICY_REJECTED)
        notify(db, org_id, {"type": "action_updated", "action_id": act.id, "incident_id": act.incident_id})
        db.commit()
        raise ActionError("Policy no longer allows this action: " + _failed(act))
    got = _claim(db, action_id, [ActionStatus.AWAITING, ActionStatus.FAILED], ActionStatus.APPROVED, actor)
    if got is None:
        raise ActionError(f"Action is {act.status} and cannot be approved")
    return execute(db, got, actor)


def decline(db: Session, action_id: str, org_id: str, actor: str) -> Action:
    act = db.get(Action, action_id)
    if not act or act.org_id != org_id:
        raise ActionError("Action not found", 404)
    got = _claim(db, action_id, [ActionStatus.AWAITING], ActionStatus.DECLINED, actor)
    if got is None:
        raise ActionError(f"Action is {act.status} and cannot be declined")
    return got


def execute(db: Session, act: Action, actor: str) -> Action:
    got = _claim(db, act.id, [ActionStatus.APPROVED], ActionStatus.EXECUTION, actor)
    if got is None:
        return act
    inc = db.get(Incident, got.incident_id)
    try:
        result = _run(db, got, inc, actor)
        got.execution_result = result
        got.executed_at = utcnow()
        got.error = None
        got.status = ActionStatus.COMPLETED
        db.add(
            Intervention(
                org_id=got.org_id,
                incident_id=got.incident_id,
                action_id=got.id,
                summary=f"{got.title}: {result.get('summary', 'completed')}",
                segment={"journey_stage": inc.journey_stage, "affected_sessions": inc.affected_sessions, "lifecycle_stage": inc.lifecycle_stage},
                result=result,
            )
        )
        audit(db, got.org_id, actor, "action_executed", "action", got.id, ActionStatus.EXECUTION, ActionStatus.COMPLETED)
        if got.category == "engineering" and inc.status == "action_pending":
            inc.status = "analyzed"
    except Exception as exc:
        log.exception("action %s failed", got.id)
        got.status, got.error = ActionStatus.FAILED, str(exc)[:500]
        audit(db, got.org_id, actor, "action_failed", "action", got.id, ActionStatus.EXECUTION, ActionStatus.FAILED, {"error": got.error})
    notify(db, got.org_id, {"type": "action_updated", "action_id": got.id, "incident_id": got.incident_id})
    return got


def _run(db: Session, act: Action, inc: Incident, actor: str) -> dict[str, Any]:
    kind = act.payload.get("kind")
    if kind == "ticket":
        # Deterministic from the action id so a retry can never mint a second ticket.
        ticket = f"CHN-{int(sha256(act.id)[:6], 16) % 9000 + 1000}"
        return {"summary": f"Ticket {ticket} prepared", "ticket_id": ticket, "target": "simulated_issue_tracker", "note": "Simulated: no external tracker is connected."}
    if kind == "suppression":
        return {"summary": f"Campaigns for {inc.journey_stage} flagged for suppression", "scope": inc.journey_stage, "until": "verified resolution"}
    if kind == "metric":
        from .feedback import stage_completion

        snap = stage_completion(db, inc.org_id, inc.journey_stage)
        return {"summary": f"Baseline completion {snap['rate']:.0%} over {snap['sessions']} session(s)" if snap["sessions"] else "Baseline captured (no sessions yet)", "baseline": snap}
    if kind == "email_campaign":
        from .communications import generate_drafts

        res = db.get(Resolution, act.resolution_id) if act.resolution_id else None
        if not res:
            raise ValueError("no resolution attached to this action")
        out = generate_drafts(db, res, actor)
        return {"summary": f"{out['drafted']} draft(s) prepared, {out['blocked']} customer(s) blocked by policy", **out}
    return {"summary": "Recorded", "note": act.payload.get("note", "")}


def propose_marketing_after_resolution(db: Session, inc: Incident, resolution: Resolution) -> Action | None:
    """Unlock outbound messaging once (and only once) a resolution is verified."""
    if resolution.status != "verified" or not resolution.email_eligible:
        return None
    return _make_action(
        db, inc, "reengagement_email",
        "A verified improvement is live for the affected segment; invite eligible customers back with a benefit-focused message.",
        "medium", resolution_id=resolution.id, role="reengage",
    )


def fresh_key() -> str:
    return new_id("key")
