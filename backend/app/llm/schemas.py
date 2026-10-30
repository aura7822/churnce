from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from ..enums import ACTION_TYPES, LIFECYCLE_STAGES, PRIORITIES


class Hypothesis(BaseModel):
    description: str = Field(min_length=3, max_length=500)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)


class RecommendedAction(BaseModel):
    type: str
    priority: str = "medium"
    reason: str = Field(default="", max_length=600)

    @field_validator("type")
    @classmethod
    def _type(cls, v: str) -> str:
        if v not in ACTION_TYPES:
            raise ValueError(f"unknown action type '{v}'")
        return v

    @field_validator("priority")
    @classmethod
    def _priority(cls, v: str) -> str:
        if v not in PRIORITIES:
            raise ValueError(f"unknown priority '{v}'")
        return v


class IncidentAnalysis(BaseModel):
    incident_type: str = Field(min_length=2, max_length=80)
    lifecycle_stage: str = "unknown"
    observed_facts: list[str] = Field(default_factory=list, max_length=12)
    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=5)
    evidence_ids: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=6)
    recommended_action: RecommendedAction
    customer_message_eligible: bool = False

    @field_validator("lifecycle_stage")
    @classmethod
    def _stage(cls, v: str) -> str:
        return v if v in LIFECYCLE_STAGES else "unknown"


class EmailDraft(BaseModel):
    subject: str = Field(min_length=3, max_length=120)
    body: str = Field(min_length=20, max_length=1500)
    claims_used: list[str] = Field(default_factory=list)


class Cause(BaseModel):
    description: str = Field(min_length=3, max_length=500)
    kind: str = "root_cause"          # "symptom" | "root_cause"
    confidence: float = Field(default=0.3, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        return v if v in ("symptom", "root_cause") else "root_cause"


class Recommendation(BaseModel):
    action: str
    rationale: str = Field(min_length=3, max_length=600)
    priority: str = "medium"
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("action")
    @classmethod
    def _action(cls, v: str) -> str:
        if v not in ACTION_TYPES:
            raise ValueError(f"unknown action type '{v}'")
        return v

    @field_validator("priority")
    @classmethod
    def _priority(cls, v: str) -> str:
        return v if v in PRIORITIES else "medium"


class RagAnswer(BaseModel):
    """What Gemma returns when an operator runs a query: an evidence-grounded reading of the retrieved passages."""
    lifecycle_stage: str = "unknown"
    summary: str = Field(min_length=3, max_length=1200)
    recurring_patterns: list[str] = Field(default_factory=list, max_length=8)
    causes: list[Cause] = Field(default_factory=list, max_length=8)           # symptoms vs likely root causes
    feature_requests: list[str] = Field(default_factory=list, max_length=8)
    ux_problems: list[str] = Field(default_factory=list, max_length=8)
    recommendations: list[Recommendation] = Field(default_factory=list, max_length=6)
    marketing_draft_notes: list[str] = Field(default_factory=list, max_length=4)  # benefit-led angles, never defect language
    unresolved_questions: list[str] = Field(default_factory=list, max_length=6)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.3, ge=0.0, le=1.0)

    @field_validator("lifecycle_stage")
    @classmethod
    def _stage(cls, v: str) -> str:
        return v if v in LIFECYCLE_STAGES else "unknown"
