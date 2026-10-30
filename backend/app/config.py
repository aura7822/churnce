from __future__ import annotations

from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


# Substrings that mark a secret as a placeholder shipped in docs, defaults or .env.example.
_PLACEHOLDER_SECRET_MARKERS = ("dev-only", "replace-with", "change-me", "changeme", "example", "secret-test")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./churnce.db"
    # Optional NON-pooled connection string (Neon: the host without "-pooler"). Used only for DDL at start-up
    # (CREATE EXTENSION / create_all / index), which transaction-pooled connections handle poorly.
    database_url_direct: str = ""
    db_pool_size: int = 5          # Neon free/launch plans have a small connection budget; keep this modest
    db_max_overflow: int = 5
    db_pool_recycle_seconds: int = 240   # Neon closes idle connections on scale-to-zero; recycle before that
    db_pool_timeout_seconds: int = 30
    db_connect_timeout_seconds: int = 15
    db_startup_attempts: int = 8         # a suspended Neon compute needs a few seconds to wake
    jwt_secret: str = "dev-only-secret-change-me-before-deploying-anywhere"
    jwt_ttl_minutes: int = 720
    cors_origins: str = "http://localhost:8080,http://localhost:5173"
    seed_demo: bool = True

    # Review gate and chunking
    review_seconds: int = 30
    scheduler_tick_seconds: float = 1.0
    chunk_idle_seconds: int = 20
    slow_threshold_ms: int = 3000

    # Embeddings / reranking
    embedding_provider: str = "local"  # local | nvidia
    embedding_dim: int = 1024
    rerank_provider: str = "lexical"  # lexical | nvidia
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_embed_model: str = "nvidia/nemotron-3-embed-1b"   # confirm the exact id on build.nvidia.com
    nvidia_embed_send_input_type: bool = True   # set false if the endpoint rejects input_type/truncate
    nvidia_rerank_url: str = "https://ai.api.nvidia.com/v1/retrieval/nvidia/nv-rerankqa-mistral-4b-v3/reranking"
    nvidia_rerank_model: str = "nv-rerank-qa-mistral-4b:1"

    # Reasoning
    llm_provider: str = "rules"  # rules | gemini | nvidia
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemma_model: str = "gemma-4-26b-a4b-it"   # or gemma-4-31b-it
    gemma_thinking_level: str = "minimal"      # minimal | high (Gemma 4 only; ignored for older models)
    llm_max_retries: int = 2
    nvidia_llm_model: str = "google/gemma-2-27b-it"
    llm_timeout_seconds: float = 45.0

    # Outbound email (optional). Without SMTP_HOST + EMAIL_FROM, "send" is simulated and nothing leaves the system.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    email_from: str = ""          # e.g. "Acme <hello@acme.com>"
    email_reply_to: str = ""
    email_footer: str = "You are receiving this because you opted in to updates. Reply STOP to unsubscribe."

    # Incident detection
    incident_min_sessions: int = 2
    incident_high_friction: int = 3

    # Rate limits (requests / minute)
    ingest_rate_limit: int = 1200
    login_rate_limit: int = 20

    def production_problems(self) -> list[str]:
        """Unsafe settings that must stop the server from booting when APP_ENV=production."""
        if self.app_env.lower() != "production":
            return []
        problems: list[str] = []
        secret = self.jwt_secret
        if len(secret) < 32 or any(marker in secret.lower() for marker in _PLACEHOLDER_SECRET_MARKERS):
            problems.append("JWT_SECRET must be a random value of at least 32 characters (not a documented placeholder)")
        if self.seed_demo:
            problems.append("SEED_DEMO must be false: the demo tenant ships a published password and ingest key")
        if self.is_sqlite:
            problems.append("DATABASE_URL must point at PostgreSQL with pgvector, not SQLite")
        elif not self.is_local_database and self.ssl_mode in ("", "disable", "allow", "prefer"):
            problems.append("DATABASE_URL points at a remote PostgreSQL without TLS: add ?sslmode=require (Neon needs it)")
        return problems

    # ── Database URL handling (SQLite for dev/tests, PostgreSQL + pgvector in production, Neon-ready) ──
    @staticmethod
    def _normalise(url: str) -> str:
        """Accept the strings providers hand out ("postgres://", "postgresql://") and pin the psycopg 3 driver."""
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        parts = urlsplit(url)
        host = parts.hostname or ""
        if url.startswith("postgresql+psycopg") and host.endswith("neon.tech") and "sslmode" not in dict(parse_qsl(parts.query)):
            query = urlencode([*parse_qsl(parts.query), ("sslmode", "require")])
            url = urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
        return url

    @property
    def sqlalchemy_url(self) -> str:
        return self._normalise(self.database_url)

    @property
    def sqlalchemy_url_direct(self) -> str:
        return self._normalise(self.database_url_direct) if self.database_url_direct else self.sqlalchemy_url

    @property
    def db_host(self) -> str:
        return urlsplit(self.sqlalchemy_url).hostname or ("file" if self.is_sqlite else "")

    @property
    def ssl_mode(self) -> str:
        return dict(parse_qsl(urlsplit(self.sqlalchemy_url).query)).get("sslmode", "")

    @property
    def is_neon(self) -> bool:
        return self.db_host.endswith("neon.tech")

    @property
    def uses_pooler(self) -> bool:
        """Neon's PgBouncer endpoint (transaction pooling): no server-side prepared statements, no session state."""
        return "-pooler" in self.db_host

    @property
    def is_local_database(self) -> bool:
        return self.db_host in ("", "file", "localhost", "127.0.0.1", "db", "::1")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def embedding_model_id(self) -> str:
        if self.embedding_provider == "nvidia":
            return f"{self.nvidia_embed_model}@{self.embedding_dim}"
        return f"local-hash-{self.embedding_dim}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
