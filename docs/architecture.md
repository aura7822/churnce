# Architecture

## Data flow

```
Authorised site → Extension (MV3) → POST /events (X-Churnce-Key)
  → collector: authorise domain + consent, allow-list fields, redact, dedupe by event_id
  → chunking: journey/time/error grouping → Chunk (PENDING_REVIEW, deadline = now + review_seconds)
  → review gate (operator edit / approve / discard, or backend timer)
  → validation: schema + provenance + privacy re-scan   ──fail──▶ REJECTED (never indexed)
  → QUEUED_FOR_INGESTION → EMBEDDING → INDEXED → AVAILABLE_FOR_RETRIEVAL
  → incident detection (signature + ≥ N sessions) → retrieval → Gemma/rules analysis → schema validation
  → action engine: score, policy check, approval → execution (idempotent)
  → resolution (verification sources, approved claims) → email draft → approval → outcome measurement
  → intervention memory → future retrieval
Dashboard observes every transition over WebSocket.
```

## Design decisions that carry weight

**The database is the work queue.** Each chunk, action and communication is a state machine. Every transition is `UPDATE … WHERE id = ? AND state IN (…)`; the row count says whether this worker won. Retried requests, restarts mid-sweep and extra replicas therefore cannot double-process anything (spec §7.5, §13.4: idempotent ingestion and execution).

**The timer is a column, not a `setTimeout`.** `review_deadline` is stored on the chunk; the scheduler's `sweep_review_gate` approves due chunks. Closing the dashboard never stalls the pipeline (spec §8.4). While an operator is editing, the dashboard sends a `hold` heartbeat that extends `hold_until` by 15 s, so the clock never approves a chunk mid-edit.

**The clock cannot approve what the scanner flags.** Auto-approval skips `sensitivity_status = flagged` and `review_mode = manual`. Validation re-scans on approval, and `index_chunk` scans once more before embedding. A timer expiry or a manual approval cannot put sensitive content in the index (spec §8.3).

**Edits are compare-and-swap.** `PATCH /chunks/{id}` carries the version it was based on; a stale or raced edit gets `409`, never a silent overwrite. An edit resets the countdown and the chunk is re-validated when it is next approved.

**Realtime uses a transactional outbox.** `notify()` queues messages on the session and publishes only after commit, and drops them on rollback, so the dashboard never refetches state that is not yet visible.

**The model proposes; deterministic code decides.** Gemma output must validate against a strict schema (known action types, bounded fields). The action engine independently scores actions, checks policy (consent, suppression, unresolved-issue suppression, claim verification, contact frequency), and requires human approval for anything external (spec §10.4, §21.8).

**Providers are adapters.** `llm/service.py`, `rag/embeddings.py` and `rag/rerank.py` hide provider differences. Every result records which provider produced it. Failures degrade (NVIDIA rerank → lexical) or are reported, never silently faked.

## Concurrency model

One API process runs the FastAPI app and one scheduler thread. Sync SQLAlchemy sessions, one per scheduler step so a failing sweep rolls back alone. Rate limiting is in-process (per worker); put a gateway limiter in front for multi-replica deployments.

## Tenancy

Every table carries `org_id`; every query filters on it; retrieval filters by tenant *before* ranking so semantic similarity can never cross tenants (spec §9.2).
