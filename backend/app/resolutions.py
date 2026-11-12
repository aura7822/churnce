"""Resolution verification: a fix only unlocks customer messaging when evidence supports it."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .action_engine import propose_marketing_after_resolution
from .audit import audit
from .database import notify
from .llm.service import BANNED_EMAIL_TERMS
from .models import Incident, Resolution
from .utils import utcnow


class SourceIn(BaseModel):
    type: Literal["release", "test_run", "telemetry", "engineering_approval"]
    ref: str = Field(min_length=1, max_length=120)
    status: str = Field(default="passed", max_length=30)  # deployed | passed | improved | failed
    detail: str = Field(default="", max_length=400)


class ResolutionIn(BaseModel):
    incident_id: str
    issue_category: str = Field(min_length=2, max_length=80)
    sources: list[SourceIn] = Field(default_factory=list, max_length=20)
    approved_claims: list[str] = Field(default_factory=list, max_length=10)
    segment_available: bool = False


class ResolutionError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


GOOD = {"deployed", "passed", "improved", "success"}


def verify(sources: list[dict], claims: list[str], segment_available: bool) -> tuple[str, bool, list[str], list[str]]:
    """Returns (status, email_eligible, notes, accepted_claims)."""
    notes: list[str] = []
    has_release = any(s["type"] == "release" and s["status"] in GOOD for s in sources)
    has_proof = any(s["type"] in ("test_run", "telemetry") and s["status"] in GOOD for s in sources)
    failed = [s for s in sources if s["status"] == "failed"]

    if not has_release:
        notes.append("Missing: a deployed release associated with the issue")
    if not has_proof:
        notes.append("Missing: a passing test run or improved telemetry for the affected workflow")
    if failed:
        notes.append("Blocked: " + ", ".join(f"{s['type']} {s['ref']} failed" for s in failed))
    if not segment_available:
        notes.append("Missing: confirmation that the improvement reaches the intended customer segment")

    accepted: list[str] = []
    for c in claims:
        c = c.strip()
        if not c:
            continue
        if BANNED_EMAIL_TERMS.search(c) or len(c) > 140:
            notes.append(f"Claim rejected (must be benefit-focused and under 140 characters): “{c[:60]}”")
            continue
        accepted.append(c)
    if not accepted:
        notes.append("No usable approved customer-facing claim")

    verified = has_release and has_proof and not failed and segment_available
    status = "verified" if verified else "pending_verification"
    if verified:
        notes.insert(0, "Verified: release deployed, workflow proof present, segment confirmed")
    return status, verified and bool(accepted), notes, accepted


def create(db: Session, org_id: str, actor: str, data: ResolutionIn) -> Resolution:
    inc = db.get(Incident, data.incident_id)
    if not inc or inc.org_id != org_id:
        raise ResolutionError("Incident not found", 404)
    srcs = [s.model_dump() for s in data.sources]
    status, eligible, notes, claims = verify(srcs, data.approved_claims, data.segment_available)
    res = Resolution(
        org_id=org_id,
        incident_id=inc.id,
        issue_category=data.issue_category,
        status=status,
        sources=srcs,
        approved_claims=claims,
        segment_available=data.segment_available,
        email_eligible=eligible,
        verification_notes=notes,
        created_by=actor,
        verified_at=utcnow() if status == "verified" else None,
    )
    db.add(res)
    db.flush()
    _apply(db, inc, res, actor)
    return res


def add_source(db: Session, org_id: str, actor: str, resolution_id: str, source: SourceIn, claims: list[str] | None = None, segment_available: bool | None = None) -> Resolution:
    res = db.get(Resolution, resolution_id)
    if not res or res.org_id != org_id:
        raise ResolutionError("Resolution not found", 404)
    inc = db.get(Incident, res.incident_id)
    res.sources = [*res.sources, source.model_dump()]
    if claims is not None:
        res.approved_claims = claims
    if segment_available is not None:
        res.segment_available = segment_available
    status, eligible, notes, accepted = verify(res.sources, res.approved_claims, res.segment_available)
    res.status, res.email_eligible, res.verification_notes, res.approved_claims = status, eligible, notes, accepted
    if status == "verified" and not res.verified_at:
        res.verified_at = utcnow()
    _apply(db, inc, res, actor)
    return res


def _apply(db: Session, inc: Incident, res: Resolution, actor: str) -> None:
    audit(db, res.org_id, actor, "resolution_recorded", "resolution", res.id, None, res.status, {"incident": inc.id})
    if res.status == "verified":
        prev = inc.status
        inc.status = "resolved"
        inc.resolved_at = res.verified_at
        inc.resolution_id = res.id
        inc.customer_message_eligible = res.email_eligible
        audit(db, res.org_id, actor, "incident_resolved", "incident", inc.id, prev, "resolved")
        propose_marketing_after_resolution(db, inc, res)
    notify(db, res.org_id, {"type": "incident_updated", "incident_id": inc.id})
    notify(db, res.org_id, {"type": "resolution_updated", "resolution_id": res.id, "incident_id": inc.id})
