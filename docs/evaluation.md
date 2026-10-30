# Evaluation

Churnce reports strength of evidence, not just deltas, and must not claim a churn reduction until one has been demonstrated (spec §22.8).

## What exists

| Spec | Tool | Run |
|---|---|---|
| 22.3 Retrieval quality | `backend/app/evaluation.py`: Recall@K, Precision@K, MRR, graded NDCG@K over 8 labelled queries, scored on the passages that survive the real retrieval filters | `cd backend && python -m app.evaluation --k 5` |
| 22.4 Root-cause identification | `scripts/evaluate_diagnosis.py`: runs three scripted incidents with known causes end to end, compares incident type to label, plus a healthy-checkout negative control for false positives | `python scripts/evaluate_diagnosis.py` |
| 22.6 Operational | Retrieval latency is recorded per retrieval; `/metrics` and `/healthz` expose pipeline and scheduler health | — |
| 15.4 / 22.8 Outcomes | `feedback.py`: before/after journey-stage completion around a verified resolution, and emailed-vs-holdout comparison, each graded `insufficient / low / moderate / strong` with explicit caveats | Dashboard → Feedback |

## Rules-only baseline vs Gemma

The deterministic engine (`LLM_PROVIDER=rules`) *is* the baseline. Run `evaluate_diagnosis.py` once per provider and compare accuracy, false positives and latency:

```
LLM_PROVIDER=rules   (start backend)  python scripts/evaluate_diagnosis.py
LLM_PROVIDER=gemini  (restart backend) python scripts/evaluate_diagnosis.py
```

For retrieval, repeat `python -m app.evaluation` with `EMBEDDING_PROVIDER=local`/`nvidia` and `RERANK_PROVIDER=lexical`/`nvidia`.

## Limits you should state when presenting results

- The golden set is **8 queries over a 16-document seed knowledge base**, written alongside it. It guards against regressions; it is not a benchmark and says little about generalisation.
- Three scripted scenarios are a smoke test, not an accuracy estimate. With only three cases a single miss moves accuracy by 33 points.
- Scripted journeys are synthetic and labelled `simulated`; they say nothing about real customer behaviour.
- Model-reported confidence is not a calibrated probability. It should be compared against labelled historical incidents before any automated decision depends on it.
- Before/after comparisons are confounded by seasonality, traffic and other releases. Use the holdout percentage (`PATCH /config`) to get a counterfactual for re-engagement emails.

## Not built

Event-collection accuracy (missed/duplicated events against a ground-truth script), chunk-coherence scoring, recommendation-quality reviewer rubrics, and email deliverability metrics (needs a real provider) are specified in §22 but have no tooling yet.
