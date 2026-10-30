"""Retrieval evaluation (spec section 22.3): Recall@K, Precision@K, MRR and NDCG@K over a labelled query set.

The metric functions are pure and dependency-free. `run_retrieval_eval` drives the *real* retrieval
pipeline (`rag.retrieve`) so the numbers describe what the intelligence engine actually receives, and it
ranks only the passages that survived the access, relevance, de-duplication and budget filters.

Honest limits, repeated in docs/evaluation.md:
  * The golden set is small and was written against the seed knowledge base. It is a regression guard
    for retrieval changes (new embedder, new reranker, new thresholds), not a benchmark of the product.
  * With EMBEDDING_PROVIDER=local the vectors are hashed n-grams, so scores mainly reflect lexical overlap.
    Re-run with EMBEDDING_PROVIDER=nvidia and RERANK_PROVIDER=nvidia to measure the semantic pipeline.

Run:  python -m app.evaluation [--k 5]   (from backend/, against the configured DATABASE_URL)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Sequence


# ── Metrics ────────────────────────────────────────────────────────────────────
def _dedupe(ranked: Sequence[str]) -> list[str]:
    """Several passages can come from one source document; a source counts once, at its best rank."""
    seen: set[str] = set()
    out: list[str] = []
    for ref in ranked:
        if ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


def recall_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    top = set(_dedupe(ranked)[:k])
    return len(top & relevant) / len(relevant)


def precision_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    """Precision over the k slots. A short result list is penalised, not rescaled."""
    if k <= 0:
        return 0.0
    top = _dedupe(ranked)[:k]
    return sum(1 for r in top if r in relevant) / k


def reciprocal_rank(ranked: Sequence[str], relevant: set[str]) -> float:
    for i, ref in enumerate(_dedupe(ranked), start=1):
        if ref in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: Sequence[str], gains: dict[str, int], k: int) -> float:
    """Graded NDCG with linear gains (2 = primary evidence, 1 = supporting)."""
    if k <= 0 or not gains:
        return 0.0
    top = _dedupe(ranked)[:k]
    dcg = sum(gains.get(ref, 0) / math.log2(i + 2) for i, ref in enumerate(top))
    ideal = sorted(gains.values(), reverse=True)[:k]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


# ── Golden set ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class GoldenQuery:
    id: str
    query: str
    gains: dict[str, int] = field(default_factory=dict)  # source_ref -> graded relevance (1 or 2)

    @property
    def relevant(self) -> set[str]:
        return set(self.gains)


GOLDEN_QUERIES: list[GoldenQuery] = [
    GoldenQuery(
        "checkout_timeouts",
        "Repeated checkout payment timeouts on the primary action",
        {"log_000219": 2, "issue_000412": 2, "doc_release_notes_2_14": 2, "doc_checkout_guide": 1, "tkt_88123": 1, "int_hist_0007": 1},
    ),
    GoldenQuery(
        "onboarding_profile_errors",
        "Customers stuck on the onboarding profile step with server errors",
        {"log_000305": 2, "doc_onboarding_guide": 2, "tkt_88207": 1, "doc_release_notes_2_14": 1},
    ),
    GoldenQuery(
        "search_no_results",
        "Search returns no results for wide fit waterproof boots",
        {"doc_search_limits": 2, "tkt_87990": 2, "log_000118": 1},
    ),
    GoldenQuery(
        "discount_during_outage",
        "Can we email a discount to customers while an issue is still unresolved",
        {"pol_comms_001": 2, "int_hist_0011": 2},
    ),
    GoldenQuery(
        "approval_rules",
        "Which actions need human approval and which failures are high priority",
        {"pol_escalation_002": 2},
    ),
    GoldenQuery(
        "retention_period",
        "How long are raw events and embeddings kept before deletion",
        {"pol_retention_003": 2},
    ),
    GoldenQuery(
        "release_changes",
        "What changed in release 2.14 for payments and onboarding",
        {"doc_release_notes_2_14": 2, "log_000219": 1, "doc_onboarding_guide": 1},
    ),
    GoldenQuery(
        "gateway_latency",
        "Payments gateway latency alert and connection pool",
        {"log_000219": 2, "issue_000412": 1, "doc_release_notes_2_14": 2},
    ),
]


# ── Runner ─────────────────────────────────────────────────────────────────────
def score_ranking(q: GoldenQuery, ranked: Sequence[str], k: int) -> dict:
    return {
        "id": q.id,
        "query": q.query,
        "retrieved": _dedupe(ranked)[:k],
        "missed": sorted(q.relevant - set(_dedupe(ranked)[:k])),
        f"recall@{k}": round(recall_at_k(ranked, q.relevant, k), 4),
        f"precision@{k}": round(precision_at_k(ranked, q.relevant, k), 4),
        "mrr": round(reciprocal_rank(ranked, q.relevant), 4),
        f"ndcg@{k}": round(ndcg_at_k(ranked, q.gains, k), 4),
    }


def summarize(per_query: list[dict], k: int) -> dict:
    keys = [f"recall@{k}", f"precision@{k}", "mrr", f"ndcg@{k}"]
    n = len(per_query) or 1
    return {key: round(sum(r[key] for r in per_query) / n, 4) for key in keys}


def run_retrieval_eval(db, org_id: str, k: int = 5, queries: Sequence[GoldenQuery] = GOLDEN_QUERIES) -> dict:
    """Evaluate the live retrieval pipeline. Writes RetrievalRecord rows to `db`; the caller must roll back."""
    from .rag.embeddings import get_embedder  # lazy: keeps the metric functions importable on their own
    from .rag.retrieval import retrieve

    per_query: list[dict] = []
    providers: dict[str, str] = {}
    latencies: list[int] = []
    for q in queries:
        rec = retrieve(db, org_id, q.query, purpose="evaluation")
        ranked = [c["source_ref"] for c in rec.candidates if c.get("kept")]
        per_query.append({**score_ranking(q, ranked, k), "latency_ms": rec.latency_ms})
        providers = {"embedding": rec.embedding_provider, "rerank": rec.rerank_provider}
        latencies.append(rec.latency_ms)
    return {
        "k": k,
        "queries": len(per_query),
        "providers": providers or {"embedding": get_embedder().name},
        "aggregate": summarize(per_query, k),
        "p50_latency_ms": sorted(latencies)[len(latencies) // 2] if latencies else None,
        "per_query": per_query,
    }


def evaluate_isolated(session_factory: Callable, org_id: str, k: int = 5) -> dict:
    """Run the evaluation in its own session and always roll back, so no evaluation rows persist."""
    db = session_factory()
    try:
        return run_retrieval_eval(db, org_id, k)
    finally:
        db.rollback()
        db.close()


def main() -> None:  # pragma: no cover - thin CLI
    import argparse
    import json

    from sqlalchemy import select

    from .database import SessionLocal
    from .models import Organization

    parser = argparse.ArgumentParser(description="Evaluate Churnce retrieval against the golden query set")
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()
    with SessionLocal() as db:
        org_id = db.scalar(select(Organization.id).limit(1))
    if not org_id:
        raise SystemExit("No organization found. Start the API once with SEED_DEMO=true to seed the demo tenant.")
    print(json.dumps(evaluate_isolated(SessionLocal, org_id, args.k), indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
