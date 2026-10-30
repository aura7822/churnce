# Privacy and security

## Data minimisation, in layers

1. **Extension** reads no input values at all for `password`, `hidden`, `file`, `tel` or `email` fields, never logs keystrokes, strips query strings and fragments from routes, and redacts text client-side before anything leaves the browser. Observation starts only for origins the operator authorises through Chrome's own permission prompt, and the permission is revocable per origin.
2. **Collector** accepts only an allow-list of metadata keys (`error_code`, `http_status`, `element_label`, `search_query`, `step`, `endpoint`, …); everything else is dropped, not stored. Routes are normalised (identifiers collapsed).
3. **Server redaction** (`privacy.py`) removes emails, phone numbers, Luhn-valid card numbers, SSNs, labelled national-ID/passport numbers, Kenyan KRA PINs, mod-97-valid IBANs, JWTs, bearer tokens, API keys and `password=`-style pairs. Look-alike numbers (order ids, timings) are left alone.
4. **Validation and indexing** re-scan. A chunk with residual sensitive content is `REJECTED`, never embedded, and the review timer cannot override that.

Redaction is pattern-based and will miss things (names, addresses, free-text PII). It reduces risk; it does not remove the need for consent, minimisation at the source and retention limits.

## Authentication, authorisation, tenancy

JWT sessions (default 12 h), PBKDF2-HMAC-SHA256 password hashes (600,000 iterations, per-user salt; the count is stored in each hash so it can be raised without breaking old logins), role-based permissions (see [api.md](api.md)), per-tenant ingest keys stored as hashes and rotatable (`POST /config/rotate-key`). Every query is tenant-scoped, including retrieval. The WebSocket authenticates in its first message, never via URL.

## Secrets

Gemma/NVIDIA keys live only in backend environment variables. They are never sent to the dashboard or placed in the extension.

## Prompt injection

Retrieved text and customer-supplied text are wrapped as untrusted evidence; suspicious passages are quarantined at ingestion; model output must pass a strict schema; the action engine re-validates every proposed operation independently of the model.

## Governed external actions

Sending email, creating tickets and other external effects require human approval, pass policy checks (consent, suppression, contact frequency, duplicate prevention, approved-claims, and a verified non-regressed resolution before any outbound marketing) and are executed by the backend only. The model cannot send anything. **Email sending is simulated in this build**: approved drafts move to `sent_simulated`, are audited as such, and nothing leaves the system until a real provider is integrated. Customer-facing claims must come from a **verified** resolution's approved-claims list.

## Auditability

State transitions, edits, approvals, rejections and executions are recorded with actor and timestamp, without duplicating customer content. The retention sweep does **not** purge audit records; define your own audit-retention period (the seeded demo policy text says one year, but that is documentation, not enforcement).

## Retention

Events, chunks, their embeddings and idle sessions older than the configured `retention_days` are purged together by the retention sweep (every 6 h) and on demand (`POST /governance/retention/run`), so derived chunks and index entries do not outlive their source. Email drafts and audit records are not covered by the sweep.

## Production start-up guard

With `APP_ENV=production` the API **refuses to boot** if `JWT_SECRET` is short or a documented placeholder, if `SEED_DEMO` is true (the demo tenant has a published password and ingest key), or if `DATABASE_URL` is SQLite.

## Known gaps to close before real customer data

Passwords have no lockout or MFA (login is only rate-limited per IP); email delivery is simulated; rate limits are per-process; TLS termination is expected from a reverse proxy; there is no field-level encryption at rest beyond database/disk encryption; no formal DPIA or legal-basis workflow is built in. Treat consent and applicable law (e.g. Kenya's Data Protection Act, GDPR) as requirements to satisfy outside the code.
