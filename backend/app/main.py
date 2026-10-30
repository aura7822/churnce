from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from . import models  # noqa: F401  (registers tables on Base.metadata)
from .action_engine import ActionError
from .api import router
from .chunk_pipeline import PipelineError
from .communications import CommError
from .config import get_settings
from .database import Base, SessionLocal, admin_engine, wait_until_ready
from .logbuf import install as install_log_buffer
from .realtime import hub
from .resolutions import ResolutionError
from .scheduler import scheduler
from .seed import seed_demo

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
install_log_buffer()
log = logging.getLogger("churnce")


def init_database() -> None:
    wait_until_ready()
    if not settings.is_sqlite:
        # Neon: pgvector is available but must be enabled per database. DDL goes through the direct endpoint.
        with admin_engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(admin_engine)
    if not settings.is_sqlite:
        # Approximate-nearest-neighbour index for pgvector (cosine). Safe to repeat.
        try:
            with admin_engine.begin() as conn:
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_evidence_embedding ON evidence_records USING hnsw (embedding vector_cosine_ops)"))
        except Exception as exc:  # noqa: BLE001
            log.warning("HNSW index not created (%s); falling back to sequential scan", exc)
    db = SessionLocal()
    try:
        seed_demo(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    problems = settings.production_problems()
    if problems:
        raise RuntimeError("Refusing to start with unsafe production settings: " + "; ".join(problems))
    hub.bind(asyncio.get_running_loop())
    await asyncio.to_thread(init_database)
    scheduler.start()
    log.info("Database ready (%s%s%s)", "sqlite" if settings.is_sqlite else f"postgresql host={settings.db_host}", ", neon" if settings.is_neon else "", ", pooled" if settings.uses_pooler else "")
    log.info("Churnce API ready (llm=%s, embeddings=%s, rerank=%s)", settings.llm_provider, settings.embedding_provider, settings.rerank_provider)
    try:
        yield
    finally:
        await asyncio.to_thread(scheduler.stop)


app = FastAPI(title="Churnce API", version="1.0.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Churnce-Key"],
    max_age=600,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    started = time.perf_counter()
    try:
        resp = await call_next(request)
    except Exception:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        raise
    took = (time.perf_counter() - started) * 1000
    if resp.status_code >= 500:
        log.error("%s %s -> %d in %.0f ms", request.method, request.url.path, resp.status_code, took)
    elif took > settings.slow_threshold_ms:
        log.warning("slow request: %s %s took %.0f ms", request.method, request.url.path, took)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Cache-Control", "no-store")
    return resp


def _domain_error(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=getattr(exc, "status_code", 409))


for _exc in (PipelineError, ActionError, CommError, ResolutionError):
    app.add_exception_handler(_exc, _domain_error)

app.include_router(router)


@app.get("/healthz")
def healthz():
    return {"status": "ok" if scheduler.healthy else "starting", "scheduler": scheduler.status()}
