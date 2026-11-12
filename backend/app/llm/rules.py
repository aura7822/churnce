"""Deterministic baseline analyzer and email templates.

Serves three purposes: (1) the offline default so Churnce runs without API keys, (2) the
safety net when a hosted model fails validation twice, and (3) the "rules-only baseline" the
specification asks to compare AI-assisted diagnosis against.
"""

from __future__ import annotations

import re
from typing import Any

from ..enums import PRIORITIES
from .schemas import EmailDraft, Hypothesis, IncidentAnalysis, RecommendedAction

BASE_CONFIDENCE = {
    "timeout": 0.55,
    "error": 0.55,
    "unresponsive": 0.45,
    "slow": 0.5,
    "validation_failure": 0.45,
    "no_results": 0.45,
    "abandoned": 0.3,
}

STAGE_TO_LIFECYCLE = {
    "browse": "awareness",
    "registration": "acquisition",
    "checkout": "acquisition",
    "onboarding": "activation",
    "search": "engagement",
    "dashboard": "engagement",
}


def _incident_type(stage: str, signal: str) -> str:
    if signal in ("timeout", "error", "unresponsive"):
        return f"{stage}_reliability"
    if signal == "slow":
        return f"{stage}_performance"
    if signal == "validation_failure":
        return f"{stage}_form_usability"
    if signal == "no_results":
        return "search_discovery"
    return f"{stage}_abandonment"


def _hypothesis_text(stage: str, signal: str, endpoint: str | None) -> str:
    target = f"the {endpoint} request" if endpoint else f"the primary {stage} action"
    return {
        "timeout": f"A {stage} reliability issue (backend timeouts on {target}) may be preventing completion",
        "error": f"A {stage} reliability issue (server errors on {target}) may be preventing completion",
        "unresponsive": f"The primary {stage} control may be unresponsive because of a client-side handler or blocked request",
        "slow": f"Slow responses during {stage} may be discouraging customers from completing the workflow",
        "validation_failure": f"Form validation rules or unclear field guidance may be blocking {stage} completion",
        "no_results": "Search relevance gaps or missing catalogue entries may be leaving customers without results",
        "abandoned": f"Customers may be abandoning {stage} because of friction that produced no explicit failure signal",
    }.get(signal, f"Unexplained friction during {stage}")


def _action_for(signal: str, stage: str, corroborated: bool) -> str:
    if signal in ("timeout", "error", "unresponsive"):
        return "engineering_investigation" if corroborated else "bug_reproduction_summary"
    if signal == "slow":
        return "performance_investigation"
    if signal in ("validation_failure",) or (signal == "abandoned" and stage in ("onboarding", "registration")):
        return "ux_improvement"
    if signal == "no_results":
        return "feature_suggestion"
    return "segment_investigation"


def _priority(severity: str) -> str:
    return severity if severity in PRIORITIES else "medium"


def _first_sentence(text: str, limit: int = 220) -> str:
    s = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
    return s[:limit]


def analyze(ctx: dict[str, Any]) -> IncidentAnalysis:
    inc = ctx["incident"]
    stage, signal = inc["journey_stage"], inc["signal"]
    sessions = max(1, inc["affected_sessions"])
    evidence = ctx["evidence"]
    other = [e for e in evidence if e["collection"] != "customer_journey" and e.get("rerank_score", 0) >= 0.3]
    eng = [e for e in other if e["collection"] == "engineering"]
    sup = [e for e in other if e["collection"] == "support"]
    prod = [e for e in other if e["collection"] == "product_knowledge"]
    corroborated = bool(eng)

    conf = BASE_CONFIDENCE.get(signal, 0.35)
    conf += 0.15 if eng else 0.0
    conf += 0.07 if sup else 0.0
    conf += 0.05 if prod else 0.0
    conf += min(0.1, 0.03 * (sessions - 1))
    if not other:
        conf = min(conf, 0.5)
    conf = round(min(conf, 0.9), 2)

    primary_ids = [e["source_ref"] for e in (eng[:2] + sup[:1] + prod[:1])] or []
    journey_ids = [e["source_ref"] for e in evidence if e["collection"] == "customer_journey"][:3]
    hyps = [
        Hypothesis(
            description=_hypothesis_text(stage, signal, inc.get("endpoint")),
            confidence=conf,
            evidence_ids=primary_ids + journey_ids,
        )
    ]
    if signal in ("timeout", "error", "unresponsive", "slow"):
        hyps.append(
            Hypothesis(
                description="Isolated client or network conditions explain the failures (less likely as more sessions are affected)",
                confidence=round(max(0.08, 0.35 - 0.08 * (sessions - 1) - (0.1 if eng else 0.0)), 2),
                evidence_ids=journey_ids[:1],
            )
        )

    facts = list(ctx.get("facts", []))
    for e in eng[:2]:
        facts.append(f"Engineering record {e['source_ref']}: {_first_sentence(e['content'])}")
    for e in sup[:1]:
        facts.append(f"Support record {e['source_ref']}: {_first_sentence(e['content'])}")

    questions = [
        "Has the suspected cause been confirmed by engineering verification or a controlled test? Correlation alone does not establish causation."
    ]
    if not eng:
        questions.insert(0, "No engineering or log evidence corroborates this pattern; instrumentation may be needed to confirm the backend cause.")
    if sessions < 3:
        questions.append(f"Only {sessions} session(s) are affected so far; confidence will change as more evidence arrives.")

    action_type = _action_for(signal, stage, corroborated)
    reason = {
        "engineering_investigation": f"{sessions} session(s) hit repeated {signal} events in {stage}, corroborated by engineering records",
        "bug_reproduction_summary": f"Repeated {signal} events in {stage} lack corroborating logs; a reproduction summary is the cheapest next step",
        "performance_investigation": f"Slow responses recorded during {stage} across {sessions} session(s)",
        "ux_improvement": f"Customers stall in {stage} without a technical failure; the flow itself likely needs work",
        "feature_suggestion": "Repeated searches with no useful results suggest missing catalogue or search capability",
        "segment_investigation": "Pattern is not yet specific enough to attribute to a cause",
    }[action_type]

    return IncidentAnalysis(
        incident_type=_incident_type(stage, signal),
        lifecycle_stage=STAGE_TO_LIFECYCLE.get(stage, "unknown"),
        observed_facts=facts[:12],
        hypotheses=hyps,
        evidence_ids=list(dict.fromkeys(primary_ids + journey_ids)),
        unresolved_questions=questions[:6],
        recommended_action=RecommendedAction(type=action_type, priority=_priority(inc["severity"]), reason=reason),
        customer_message_eligible=False,
    )


# ── Email templates (benefit-focused, never describe the defect) ──────────────
TEMPLATES: dict[str, tuple[str, str]] = {
    "checkout": (
        "Your next checkout could be easier",
        "Hi there,\n\nWe're always working to make shopping with us smoother. {claim}.\n\n"
        "When you're ready, pick up where you left off and finish your order.\n\n{cta}\n\nThanks for being with us.",
    ),
    "onboarding": (
        "Pick up where you left off",
        "Hi there,\n\nGetting started is simpler now. {claim}.\n\n"
        "Jump back in and finish setting up in a few minutes.\n\n{cta}\n\nThanks for being with us.",
    ),
    "search": (
        "Find what you're looking for, faster",
        "Hi there,\n\n{claim}.\n\nTake another look and discover what's new.\n\n{cta}\n\nThanks for being with us.",
    ),
    "dashboard": (
        "Get back to your work with a smoother experience",
        "Hi there,\n\n{claim}.\n\nYour work is right where you left it.\n\n{cta}\n\nThanks for being with us.",
    ),
    "default": (
        "Something better is waiting for you",
        "Hi there,\n\n{claim}.\n\nCome back and see for yourself.\n\n{cta}\n\nThanks for being with us.",
    ),
}


def render_email(stage: str, approved_claims: list[str], cta_url: str) -> EmailDraft:
    subject, body = TEMPLATES.get(stage, TEMPLATES["default"])
    claim = (approved_claims[0] if approved_claims else "We've made improvements").rstrip(".")
    return EmailDraft(
        subject=subject,
        body=body.format(claim=claim, cta=f"Continue: {cta_url}"),
        claims_used=approved_claims[:1],
    )
