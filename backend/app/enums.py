from __future__ import annotations


class ChunkState:
    CREATED = "CREATED"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    VALIDATING = "VALIDATING"
    REJECTED = "REJECTED"
    DISCARDED = "DISCARDED"
    QUEUED = "QUEUED_FOR_INGESTION"
    EMBEDDING = "EMBEDDING"
    INDEXED = "INDEXED"
    AVAILABLE = "AVAILABLE_FOR_RETRIEVAL"

    ALL = [CREATED, PENDING_REVIEW, APPROVED, VALIDATING, REJECTED, DISCARDED, QUEUED, EMBEDDING, INDEXED, AVAILABLE]


# Pipeline stage names published to the dashboard (coarser than states).
STAGE_OF_STATE = {
    ChunkState.CREATED: "created",
    ChunkState.PENDING_REVIEW: "review",
    ChunkState.APPROVED: "review",
    ChunkState.VALIDATING: "validation",
    ChunkState.REJECTED: "rejected",
    ChunkState.DISCARDED: "discarded",
    ChunkState.QUEUED: "embedding",
    ChunkState.EMBEDDING: "embedding",
    ChunkState.INDEXED: "indexed",
    ChunkState.AVAILABLE: "available",
}


class ActionStatus:
    PROPOSED = "PROPOSED"
    POLICY_REJECTED = "REJECTED"
    AWAITING = "AWAITING_APPROVAL"
    DECLINED = "DECLINED"
    APPROVED = "APPROVED"
    EXECUTION = "EXECUTION"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    OUTCOME = "OUTCOME_EVALUATION"


COLLECTIONS = [
    "customer_journey",
    "product_knowledge",
    "engineering",
    "support",
    "intervention_memory",
    "business_policy",
]

LIFECYCLE_STAGES = [
    "awareness",
    "acquisition",
    "activation",
    "engagement",
    "retention",
    "reactivation",
    "advocacy",
    "unknown",
]

ACTION_CATEGORY = {
    # engineering
    "engineering_investigation": "engineering",
    "create_issue_report": "engineering",
    "bug_reproduction_summary": "engineering",
    "performance_investigation": "engineering",
    "ux_improvement": "engineering",
    "feature_suggestion": "engineering",
    # support
    "support_escalation": "support",
    "journey_summary": "support",
    "kb_improvement": "support",
    # lifecycle marketing
    "reengagement_email": "marketing",
    "onboarding_reminder": "marketing",
    "feature_announcement": "marketing",
    "recovery_communication": "marketing",
    "suppress_campaign": "marketing",
    # analytical
    "track_metric": "analytical",
    "segment_investigation": "analytical",
    "run_experiment": "analytical",
    "compare_interventions": "analytical",
}
ACTION_TYPES = sorted(ACTION_CATEGORY)

# Marketing actions that put a message in front of a customer.
OUTBOUND_MARKETING = {"reengagement_email", "onboarding_reminder", "feature_announcement", "recovery_communication"}
# Internal and reversible: safe to execute without a human click.
AUTO_EXECUTE = {"track_metric"}

PRIORITIES = ["low", "medium", "high", "critical"]

EVENT_TYPES = {
    "page_view",
    "page_load",
    "click",
    "repeated_click",
    "interaction_failure",
    "form_validation_failure",
    "search",
    "search_no_results",
    "abandonment",
    "error_message",
    "workflow_completed",
    "slow_response",
    "inactivity",
}

DEFAULT_JOURNEY_MAP = {
    "/checkout": "checkout",
    "/cart": "checkout",
    "/payment": "checkout",
    "/signup": "registration",
    "/register": "registration",
    "/onboarding": "onboarding",
    "/welcome": "onboarding",
    "/search": "search",
    "/dashboard": "dashboard",
    "/reports": "dashboard",
    "/products": "browse",
    "/": "browse",
}

# Relative business weight of a journey stage when ranking issues.
STAGE_BUSINESS_WEIGHT = {
    "checkout": 1.0,
    "registration": 0.9,
    "onboarding": 0.8,
    "dashboard": 0.65,
    "search": 0.6,
    "browse": 0.4,
}
