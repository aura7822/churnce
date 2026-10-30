# API

Base path `/api/v1`. Interactive docs at `/api/docs`. Dashboard routes use `Authorization: Bearer <jwt>` from `POST /auth/login`; the extension uses `X-Churnce-Key`. Domain errors return `{"detail": "..."}` with `404`/`409`/`422`; unauthorised access returns `401`/`403`. Cross-tenant ids return `404`.

## Roles

| Role | Can |
|---|---|
| administrator | everything |
| product_analyst | read, review chunks, analyze incidents, approve engineering/support/analytical actions, write knowledge, evaluate outcomes, run simulations |
| engineer | read, review chunks, analyze, approve engineering/support/analytical actions, record resolutions, write knowledge |
| marketing_operator | read, approve marketing/analytical actions, approve emails, evaluate outcomes |
| reviewer | read-only |

## Routes

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/login` · GET `/me` | Sign in; current user, permissions |
| POST | `/events` | **Ingest key.** Submit up to 100 normalized events |
| GET | `/events` | Authorised event records (sensitive fields never returned) |
| GET | `/chunks` · `/chunks/pending` · `/chunks/{id}` | List by state (`?state=A,B`); pending review; detail |
| POST | `/chunks` | Create or submit a chunk |
| PATCH | `/chunks/{id}` | Edit `{version, summary?, events?}`; `409` if stale |
| POST | `/chunks/{id}/hold` | Heartbeat: pause the countdown while editing |
| POST | `/chunks/{id}/approve` · `/discard` | Approve for validation (optional `version`); discard |
| GET | `/rag/retrievals` · `/rag/retrievals/{id}` | Inspect a retrieval: query, candidates, scores, access decisions, context sent to the model |
| POST | `/rag/search` | Ad-hoc tenant-scoped search |
| GET | `/rag/collections` · POST `/rag/documents` | Collection counts; add a knowledge document |
| GET | `/incidents` · `/incidents/{id}` | List; evidence, actions, retrieval, resolution, outcomes |
| POST | `/incidents/{id}/analyze` | Queue (re)analysis → `202` |
| POST | `/incidents/{id}/evaluate` | Measure outcome against a verified resolution |
| GET | `/recommendations` | Ranked proposed actions |
| POST | `/actions/{id}/approve` · `/reject` | Approval lifecycle; category-scoped permission |
| GET | `/resolutions` · POST `/resolutions` · POST `/resolutions/{id}/sources` | Record a fix and attach verification evidence |
| GET | `/emails` · POST `/emails/{id}/approve` · `/reject` · `/send` | Drafts, approval, backend-controlled send (**simulated**: status `sent_simulated`, no provider connected) |
| GET | `/metrics` · `/outcomes` · `/audit` | Dashboard metrics from real backend state; outcomes; audit trail |
| POST | `/chunks/{id}/extend` | Add 30 s (max 10 min ahead) to an auto-review countdown; audited as `chunk_extended` |
| GET/PATCH | `/config` · POST `/config/rotate-key` · POST `/governance/retention/run` | Monitoring, review policy, holdout %, retention |
| GET/PATCH | `/customers`, `/users` (+ POST `/users`) | Consent/suppression; role management |
| GET | `/demo/scenarios` · POST `/demo/simulate` | Demo tenants only |
| WS | `/stream` | Realtime pipeline events |

## WebSocket

Open `/api/v1/stream`, then send `{"type":"auth","token":"<jwt>"}` within 8 s (the token never appears in a URL or log). Server replies `hello`, then pushes JSON events, `ping` every 25 s of silence. Close code `4401` means unauthenticated.

```json
{"type":"pipeline_stage_changed","chunk_id":"chk_000087","previous_stage":"review",
 "current_stage":"embedding","state":"EMBEDDING","version":2,"timestamp":"2026-10-27T10:15:40Z"}
```

Chunk states: `PENDING_REVIEW → APPROVED → VALIDATING → QUEUED_FOR_INGESTION → EMBEDDING → INDEXED → AVAILABLE_FOR_RETRIEVAL`, with `DISCARDED` and `REJECTED` as side exits (a rejected chunk can be edited and resubmitted).

## Limits

Ingest: 100 events per request, 1200 requests/min per site (configurable). Login: 20/min per IP. Summaries ≤ 600 chars; ≤ 40 event lines of ≤ 240 chars per chunk.
