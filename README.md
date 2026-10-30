
# churnce
# ────────────────────────── AI providers ────────────────────────
# Reasoning: rules (deterministic baseline, no key) | gemini (Gemma via Gemini API) | nvidia (OpenAI-compatible NIM endpoint)
# Set to gemini for Gemma reasoning (incident analysis, Retrieve button, email drafts)
LLM_PROVIDER=rules
GEMINI_API_KEY=AQ.Ab8RN6In8XCUfo049j_GtecDDaM8fJlB0nhPGCDwo2TZ4RzEPw
# Gemma via the Gemini API (key from Google AI Studio). Models: gemma-4-26b-a4b-it | gemma-4-31b-it
GEMMA_MODEL=gemma-4-26b-a4b-it
GEMMA_THINKING_LEVEL=minimal   # minimal | high
LLM_MAX_RETRIES=2
LLM_TIMEOUT_SECONDS=45
NVIDIA_LLM_MODEL=google/gemma-2-27b-it

# Embeddings: local (hashing embedder, no key) | nvidia
EMBEDDING_PROVIDER=local
# Nemotron-3-Embed-1B returns 2048 floats; 2048, 1024 or 512 are valid (sliced + re-normalised). 1024 keeps pgvector HNSW indexing (limit 2000).
EMBEDDING_DIM=1024
# Reranking: lexical | nvidia  (nvidia degrades to lexical if the call fails)
RERANK_PROVIDER=lexical

NVIDIA_API_KEY=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
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_EMBED_MODEL=nvidia/nemotron-3-embed-1b
NVIDIA_EMBED_SEND_INPUT_TYPE=true
NVIDIA_RERANK_URL=https://ai.api.nvidia.com/v1/retrieval/nvidia/nv-rerankqa-mistral-4b-v3/reranking
NVIDIA_RERANK_MODEL=nv-rerank-qa-mistral-4b:1


# Uvicorn access lines for 2xx/3xx are hidden (the dashboard polls constantly). Set true to show them.
LOG_ACCESS=true

# ── Outbound email (optional). Without SMTP_HOST + EMAIL_FROM, sending is simulated and nothing leaves the system. ──
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_STARTTLS=true
EMAIL_FROM=
EMAIL_REPLY_TO=
EMAIL_FOOTER=You are receiving this because you opted in to updates. Reply STOP to unsubscribe.

# aura MOTHERFUCKER
# ── Neon (hosted PostgreSQL) ──
# Use the POOLED string for the app and the DIRECT string for start-up DDL. sslmode=require is added automatically for *.neon.tech.
# DATABASE_URL=postgresql://USER:PASSWORD@ep-xxxx-pooler.REGION.aws.neon.tech/churnce
# DATABASE_URL_DIRECT=postgresql://USER:PASSWORD@ep-xxxx.REGION.aws.neon.tech/churnce
# APP_ENV=production  SEED_DEMO=false  JWT_SECRET=<48+ random chars>







