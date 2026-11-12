"""Gemma reasoning over retrieved evidence, and Nemotron vector slicing. No network: transports are stubbed."""
import math
from types import SimpleNamespace

from app.llm import service as svc
from app.llm.schemas import RagAnswer
from app.rag.embeddings import slice_and_normalise

REC = SimpleNamespace(
    context='<evidence id="eng_1" collection="engineering" untrusted="true">Checkout timeout\nPayment gateway timeouts at checkout.</evidence>',
    candidates=[{"source_ref": "eng_1", "collection": "engineering", "title": "Checkout timeout", "snippet": "Payment gateway timeouts at checkout.", "kept": True}],
)


def test_slice_and_normalise_returns_unit_vector_of_requested_size():
    v = slice_and_normalise([3.0, 4.0, 12.0, 5.0], 2)
    assert len(v) == 2 and math.isclose(math.sqrt(sum(x * x for x in v)), 1.0)


def test_baseline_without_model_is_labelled_and_cites_evidence(monkeypatch):
    monkeypatch.setattr(svc, "hosted_enabled", lambda: False)
    out = svc.reason_over_retrieval("why do checkouts fail", REC)
    assert out["provider"] == "rules baseline" and out["answer"]["evidence_ids"] == ["eng_1"]
    assert out["answer"]["lifecycle_stage"] == "acquisition"


def test_model_answer_is_validated_and_unknown_citations_are_stripped(monkeypatch):
    raw = ('{"lifecycle_stage":"acquisition","summary":"Checkout payments time out.","recurring_patterns":["timeouts"],'
           '"causes":[{"description":"Gateway timeout","kind":"root_cause","confidence":0.9,"evidence_ids":["made_up"]}],'
           '"recommendations":[{"action":"engineering_investigation","rationale":"Repeated timeouts","priority":"high","evidence_ids":["eng_1","nope"]}],'
           '"marketing_draft_notes":["Faster checkout is here","Sorry about the bug"],"evidence_ids":["eng_1","ghost"],"confidence":0.8}')
    monkeypatch.setattr(svc, "hosted_enabled", lambda: True)
    monkeypatch.setattr(svc, "_generate", lambda system, prompt: ("```json\n" + raw + "\n```", "gemma-test"))
    out = svc.reason_over_retrieval("why do checkouts fail", REC)
    a = RagAnswer.model_validate(out["answer"])
    assert out["provider"] == "gemma-test" and a.evidence_ids == ["eng_1"]
    assert a.causes[0].confidence <= 0.35                       # uncited claim is capped
    assert a.recommendations[0].evidence_ids == ["eng_1"]
    assert a.marketing_draft_notes == ["Faster checkout is here"]  # defect language removed


def test_model_failure_falls_back_instead_of_raising(monkeypatch):
    def boom(system, prompt):
        raise RuntimeError("HTTP 429")
    monkeypatch.setattr(svc, "hosted_enabled", lambda: True)
    monkeypatch.setattr(svc, "_generate", boom)
    out = svc.reason_over_retrieval("anything", REC)
    assert out["provider"].endswith("(model fallback)") and out["answer"]["summary"]


def test_email_preview_is_issue_specific_promotional_and_free_of_defect_language(monkeypatch):
    raw = '{"subject":"Buttons that respond instantly","body":"We have improved our button responsiveness, so finishing your order takes a moment. Come back and enjoy it: {{cta_url}}"}'
    ans = RagAnswer(summary="Checkout buttons were slow to respond.", marketing_draft_notes=["Faster buttons"])
    monkeypatch.setattr(svc, "hosted_enabled", lambda: True)
    monkeypatch.setattr(svc, "_generate", lambda system, prompt: (raw, "gemma-test"))
    out = svc.preview_email_from_findings("button responsiveness at checkout", ans, {"eng_1"})
    assert out and out["generated_by"] == "gemma-test" and "{{cta_url}}" in out["body"] and out["preview"] is True


def test_email_preview_rejects_defect_wording_and_falls_back_to_template(monkeypatch):
    raw = '{"subject":"Sorry about the bug","body":"We apologise for the error you hit. Come back: {{cta_url}} and try again today please."}'
    ans = RagAnswer(summary="Checkout buttons were slow.", marketing_draft_notes=["Faster buttons"])
    monkeypatch.setattr(svc, "hosted_enabled", lambda: True)
    monkeypatch.setattr(svc, "_generate", lambda system, prompt: (raw, "gemma-test"))
    out = svc.preview_email_from_findings("buttons", ans, {"eng_1"})
    assert out["generated_by"] == "template"
