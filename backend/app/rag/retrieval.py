"""Retrieval pipeline: search → access filter → rerank → dedupe → bounded evidence package."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from ..config import get_settings
from ..enums import COLLECTIONS
from ..models import RetrievalRecord
from ..utils import iso, utcnow
from .embeddings import get_embedder, tokenize
from .rerank import rerank
from .store import search

settings = get_settings()

MAX_PASSAGES = 8
MAX_CONTEXT_CHARS = 6500
PASSAGE_CHARS = 900
PER_COLLECTION_K = 6
MIN_VECTOR_SCORE = 0.02


def _jaccard(a: str, b: str) -> float:
    sa, sb = set(tokenize(a)), set(tokenize(b))
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


def retrieve(
    db: Session,
    org_id: str,
    query: str,
    incident_id: str | None = None,
    purpose: str = "incident_analysis",
    collections: list[str] | None = None,
    focus: str | None = None,
) -> RetrievalRecord:
    """`query` is the natural-language question embedded for vector search. `focus` is a short,
    specific phrase (journey stage, signal, endpoint) used for reranking so that boilerplate words in
    the question ("known issues", "documentation") cannot make unrelated passages look relevant."""
    started = time.perf_counter()
    embedder = get_embedder()
    allowed = [c for c in (collections or COLLECTIONS) if c in COLLECTIONS]
    qv = embedder.embed_query(query)

    hits = search(db, org_id, qv, allowed, PER_COLLECTION_K, embedder.name)
    scores, rr_name = rerank(focus or query, [f"{h.record.title}\n{h.record.content}" for h in hits]) if hits else ([], "lexical")

    # Blend: reranker is the primary relevance signal; vector score breaks ties and anchors recall.
    ranked = sorted(
        zip(hits, scores), key=lambda t: -(0.7 * t[1] + 0.3 * max(0.0, t[0].vector_score))
    )

    candidates: list[dict[str, Any]] = []
    kept: list[tuple[Any, float]] = []
    for hit, rr in ranked:
        rec = hit.record
        entry: dict[str, Any] = {
            "evidence_id": rec.id,
            "collection": rec.collection,
            "source_ref": rec.source_ref,
            "title": rec.title,
            "snippet": rec.content[:PASSAGE_CHARS],
            "vector_score": round(hit.vector_score, 4),
            "rerank_score": round(rr, 4),
            "effective_at": iso(rec.effective_at),
            "age_days": max(0, (utcnow() - rec.effective_at).days),
            "access": "allowed:tenant_scope",
            "kept": False,
            "dropped_reason": None,
        }
        if rec.quarantined:
            entry["dropped_reason"] = "quarantined: possible prompt injection"
        elif hit.vector_score < MIN_VECTOR_SCORE and rr <= 0:
            entry["dropped_reason"] = "below relevance threshold"
        elif any(_jaccard(rec.content, k[0].record.content) > 0.85 for k in kept):
            entry["dropped_reason"] = "near-duplicate of a higher-ranked passage"
        elif len(kept) >= MAX_PASSAGES:
            entry["dropped_reason"] = "outside evidence budget"
        else:
            kept.append((hit, rr))
            entry["kept"] = True
        candidates.append(entry)

    blocks: list[str] = []
    used = 0
    for hit, _ in kept:
        rec = hit.record
        block = (
            f'<evidence id="{rec.source_ref}" collection="{rec.collection}" untrusted="true">\n'
            f"{rec.title}\n{rec.content[:PASSAGE_CHARS]}\n</evidence>"
        )
        if used + len(block) > MAX_CONTEXT_CHARS:
            break
        blocks.append(block)
        used += len(block)

    record = RetrievalRecord(
        org_id=org_id,
        incident_id=incident_id,
        purpose=purpose,
        query=query,
        filters={
            "tenant": org_id,
            "collections": allowed,
            "excluded_collections": [c for c in COLLECTIONS if c not in allowed],
            "embedding_model": embedder.name,
            "per_collection_k": PER_COLLECTION_K,
            "max_passages": MAX_PASSAGES,
            "access_policy": "tenant-scoped; inactive and quarantined records excluded",
        },
        candidates=candidates,
        context="\n\n".join(blocks),
        embedding_provider=embedder.name,
        rerank_provider=rr_name,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    db.add(record)
    db.flush()
    return record
