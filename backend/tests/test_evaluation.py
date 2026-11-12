import json
import math
from pathlib import Path

from app.evaluation import (
    GOLDEN_QUERIES,
    GoldenQuery,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    score_ranking,
    summarize,
)

SEED = Path(__file__).resolve().parent.parent / "seed_data" / "knowledge.json"


def test_recall_and_precision_basics():
    ranked = ["a", "x", "b", "y", "z"]
    assert recall_at_k(ranked, {"a", "b", "c"}, 5) == 2 / 3
    assert recall_at_k(ranked, {"a", "b", "c"}, 1) == 1 / 3
    assert precision_at_k(ranked, {"a", "b"}, 5) == 2 / 5
    # A short result list is penalised against the k slots, not rescaled.
    assert precision_at_k(["a"], {"a"}, 5) == 1 / 5
    assert recall_at_k([], {"a"}, 5) == 0.0 and recall_at_k(["a"], set(), 5) == 0.0


def test_duplicate_passages_from_one_source_count_once():
    ranked = ["a", "a", "a", "b"]
    assert recall_at_k(ranked, {"a", "b"}, 2) == 1.0  # a, b are the top-2 distinct sources
    assert precision_at_k(ranked, {"a", "b"}, 2) == 1.0


def test_reciprocal_rank():
    assert reciprocal_rank(["x", "a"], {"a"}) == 0.5
    assert reciprocal_rank(["x", "y"], {"a"}) == 0.0


def test_ndcg_perfect_worse_and_graded():
    gains = {"a": 2, "b": 1}
    assert ndcg_at_k(["a", "b"], gains, 5) == 1.0
    # Putting the supporting passage above the primary one must score lower.
    worse = ndcg_at_k(["b", "a"], gains, 5)
    assert 0 < worse < 1.0
    expected = (1 / math.log2(2) + 2 / math.log2(3)) / (2 / math.log2(2) + 1 / math.log2(3))
    assert abs(worse - expected) < 1e-12
    assert ndcg_at_k(["x"], gains, 5) == 0.0


def test_score_ranking_reports_misses_and_summarizes():
    q = GoldenQuery("t", "q", {"a": 2, "b": 1})
    row = score_ranking(q, ["a", "x"], 3)
    assert row["missed"] == ["b"] and row["recall@3"] == 0.5
    agg = summarize([row, score_ranking(q, ["a", "b"], 3)], 3)
    assert 0.5 < agg["recall@3"] < 1.0 and agg["mrr"] == 1.0


def test_golden_labels_point_at_real_seed_documents():
    """Label rot guard: every relevant source_ref must exist in the seed knowledge base."""
    refs = {d["source_ref"] for d in json.loads(SEED.read_text())}
    ids = [q.id for q in GOLDEN_QUERIES]
    assert len(ids) == len(set(ids))
    for q in GOLDEN_QUERIES:
        assert q.gains and set(q.gains) <= refs, (q.id, set(q.gains) - refs)
        assert set(q.gains.values()) <= {1, 2}


def test_live_retrieval_eval_runs_end_to_end(client):  # `client` boots the app, seeds the demo tenant
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.evaluation import evaluate_isolated
    from app.models import Organization, RetrievalRecord

    with SessionLocal() as db:
        org_id = db.scalar(select(Organization.id).limit(1))
        before = db.query(RetrievalRecord).count()
    out = evaluate_isolated(SessionLocal, org_id, k=5)
    assert out["queries"] == len(GOLDEN_QUERIES)
    for v in out["aggregate"].values():
        assert 0.0 <= v <= 1.0
    with SessionLocal() as db:  # nothing the evaluation wrote may persist
        assert db.query(RetrievalRecord).count() == before
