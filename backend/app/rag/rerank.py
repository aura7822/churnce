"""Candidate reranking. NVIDIA reranker when configured; lexical BM25-style fallback otherwise."""

from __future__ import annotations

import logging
import math
from collections import Counter

import httpx

from ..config import get_settings
from .embeddings import tokenize

log = logging.getLogger("churnce.rerank")
settings = get_settings()


def lexical_rerank(query: str, passages: list[str]) -> list[float]:
    """BM25 over the candidate set only (idf is computed locally). Scores are in [0, 1]."""
    q = tokenize(query)
    docs = [tokenize(p) for p in passages]
    n = len(docs) or 1
    avgdl = (sum(len(d) for d in docs) / n) or 1.0
    df: Counter[str] = Counter()
    for d in docs:
        df.update(set(d))
    k1, b = 1.5, 0.75
    raw: list[float] = []
    for d in docs:
        tf = Counter(d)
        score = 0.0
        for term in set(q):
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * (tf[term] * (k1 + 1)) / (tf[term] + k1 * (1 - b + b * len(d) / avgdl))
        raw.append(score)
    top = max(raw) if raw else 0.0
    return [s / top if top else 0.0 for s in raw]


def rerank(query: str, passages: list[str]) -> tuple[list[float], str]:
    """Return (scores aligned to passages, provider name actually used)."""
    if settings.rerank_provider == "nvidia" and settings.nvidia_api_key and passages:
        try:
            with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
                r = client.post(
                    settings.nvidia_rerank_url,
                    headers={"Authorization": f"Bearer {settings.nvidia_api_key}", "Accept": "application/json"},
                    json={
                        "model": settings.nvidia_rerank_model,
                        "query": {"text": query},
                        "passages": [{"text": p[:2000]} for p in passages],
                        "truncate": "END",
                    },
                )
                r.raise_for_status()
                logits = {int(x["index"]): float(x["logit"]) for x in r.json()["rankings"]}
            vals = [logits.get(i, -20.0) for i in range(len(passages))]
            # Squash logits to (0, 1) so downstream thresholds are provider-agnostic.
            return [1 / (1 + math.exp(-v)) for v in vals], settings.nvidia_rerank_model
        except Exception as exc:  # reranking is advisory, so degrade rather than fail the analysis
            log.warning("NVIDIA rerank failed (%s); falling back to lexical", exc)
            return lexical_rerank(query, passages), "lexical (nvidia fallback)"
    return lexical_rerank(query, passages), "lexical"
