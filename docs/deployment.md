# Deployment

## Local (Docker Compose)

`docker compose up --build` starts PostgreSQL 16 with pgvector, the API, the dashboard (nginx, proxying `/api` and the WebSocket so the browser sees one origin) and the demo shop. The first start creates the schema, enables the `vector` extension, builds the HNSW index and seeds the demo tenant.

## First-run checklist

The authoring environment had no package registry access, so run these once and fix anything that surfaces:

1. `docker compose build` — backend and dashboard images (the dashboard has no lockfile yet; commit `package-lock.json` after the first `npm install`, and consider `pip-compile` for `requirements.txt`).
2. `cd backend && pytest` — includes the end-to-end review-gate, tenancy and live retrieval-eval tests.
3. `cd dashboard && npm run build` (type-checks, then bundles) · `cd extension && npm run typecheck && npm test && npm run build`.
4. Confirm the **PostgreSQL path**: `docker compose up`, run `python scripts/simulate_journey.py`, then `python -m app.evaluation` inside the backend container. SQLite is what the tests use; the pgvector query is only exercised here.
5. Load `extension/dist` in Chrome, authorise `http://localhost:8081`, use the demo shop's checkout and confirm events reach **Live Events**.
6. With real keys set, repeat step 4 and compare `python -m app.evaluation` for `local` vs `nvidia`.

## Production

Set `APP_ENV=production`; the API refuses to start unless:

- `JWT_SECRET` is a random value of ≥ 32 characters (generate with `python -c "import secrets;print(secrets.token_urlsafe(48))"`)
- `SEED_DEMO=false`
- `DATABASE_URL` points at PostgreSQL with pgvector

Then: terminate TLS at a reverse proxy; do **not** publish port 5432 (the compose file maps it for local convenience only); set a strong `POSTGRES_PASSWORD`; restrict `CORS_ORIGINS` to your dashboard origin; create real users and rotate the ingest key; back up PostgreSQL; set retention via `PATCH /config` (the Governance page was removed from the dashboard). Single replica is the supported default (the scheduler is in-process). Extra replicas are safe because every transition is claim-based, but they duplicate sweep work and have separate rate-limit counters.

## Configuration

See `.env.example` for every variable. Provider keys are optional; without them everything runs on deterministic fallbacks and the UI says so. Verify model ids, endpoints, quotas and pricing with Google and NVIDIA before enabling a live provider.

## Hosting the database on Neon

1. Create a Neon project and database (`churnce`). pgvector is enabled automatically at start-up (`CREATE EXTENSION IF NOT EXISTS vector`).
2. Set `DATABASE_URL` to the **pooled** connection string (host contains `-pooler`) and `DATABASE_URL_DIRECT` to the non-pooled one. DDL runs on the direct endpoint only.
3. `sslmode=require` is appended automatically for `*.neon.tech`; production boot refuses a remote database without TLS.
4. The engine pre-pings, recycles connections every 240 s (before scale-to-zero drops them), disables prepared statements behind the pooler, and waits up to 8 attempts for a suspended compute to wake.
5. The **Backend logs** page shows the database ping, pool occupancy, scheduler and provider status, and recent backend log lines (errors included).
