# RAG pipeline

## Collections

`customer_journey` (approved chunks) · `product_knowledge` · `engineering` · `support` · `intervention_memory` · `business_policy`. Seeded demo knowledge lives in `backend/seed_data/knowledge.json`; add more with `POST /rag/documents`.

## Ingestion

Approved chunk → schema + provenance validation → privacy re-scan → text normalization → embedding → vector + metadata row (`evidence_records`) → searchable. Upserts are idempotent on `(chunk_id, version)`; an edited chunk deactivates its older versions. Knowledge documents are split into ≤ 900-char passages, redacted, and re-ingesting identical text is a no-op while changed text supersedes the previous version of the same `source_ref`. Passages that look like prompt injection are **quarantined**: stored for audit, never retrieved.

Failed indexing retries with exponential backoff (2, 4 s) and rejects after 3 attempts, visibly, in the dashboard.

## Retrieval

1. Embed the question (query-side embedding).
2. Search each requested collection: tenant-scoped, active records only, same embedding model as the index. PostgreSQL uses pgvector (`embedding <=> query`, HNSW cosine index); other databases use a pure-Python cosine scan.
3. Rerank candidates (NVIDIA reranker, or local BM25 over the candidate set) using a short **focus** phrase — journey stage, signal, endpoint — so boilerplate words in the question cannot make unrelated passages look relevant.
4. Blend `0.7 × rerank + 0.3 × vector`; drop quarantined, below-threshold, near-duplicate (Jaccard > 0.85) and over-budget passages, recording *why* for each.
5. Assemble a bounded context of `<evidence id=… untrusted="true">` blocks.

The RAG window (Chunk lab & RAG page) shows the retrieval query, providers, latency and the exact context handed to the model; per-candidate scores and access decisions remain available from `GET /rag/retrievals/{id}`. The model is instructed to treat evidence as data, not instructions, and to separate observed facts from hypotheses.

## Embedding dimensions

`EMBEDDING_DIM` (default 1024) must match the provider (`nv-embedqa-e5-v5` is 1024-d) and the pgvector column. Retrieval is restricted to records embedded with the *current* model id, so changing providers means re-embedding rather than mixing incompatible vectors.

## Honest caveats

Semantic similarity is not causation. The local hashing embedder is a keyless fallback whose quality is lexical; measure the live pipeline with `python -m app.evaluation` ([evaluation](evaluation.md)) before trusting its rankings.
