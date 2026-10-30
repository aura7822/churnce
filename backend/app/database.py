from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    pass


log = logging.getLogger("churnce.db")


def _make_engine(url: str):
    """Build an engine tuned for the target: SQLite (dev/tests), self-hosted PostgreSQL, or Neon.

    Neon specifics: TLS is mandatory; idle connections are dropped when the compute suspends, so connections
    are pre-pinged and recycled early; the pooled endpoint (PgBouncer, transaction mode) cannot keep
    server-side prepared statements, so psycopg's automatic preparing is switched off; and the pooler rejects
    the "options" start-up parameter, so no per-connection settings are sent there.
    """
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        connect_args: dict[str, Any] = {
            "connect_timeout": settings.db_connect_timeout_seconds,
            "keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 5,
        }
        if settings.uses_pooler:
            connect_args["prepare_threshold"] = None
        kwargs.update(
            pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow,
            pool_recycle=settings.db_pool_recycle_seconds, pool_timeout=settings.db_pool_timeout_seconds,
            connect_args=connect_args,
        )
    eng = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(eng, "connect")
        def _pragmas(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

    return eng


engine = _make_engine(settings.sqlalchemy_url)
# DDL engine: the direct (non-pooled) endpoint when one is configured, otherwise the normal engine.
admin_engine = _make_engine(settings.sqlalchemy_url_direct) if settings.database_url_direct and not settings.is_sqlite else engine


def wait_until_ready(eng=None, attempts: int | None = None) -> None:
    """Block until the database answers. A scaled-to-zero Neon compute takes a few seconds to wake."""
    eng = eng or admin_engine
    attempts = attempts or settings.db_startup_attempts
    for n in range(1, attempts + 1):
        try:
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001
            if n == attempts:
                raise
            delay = min(2 ** (n - 1), 8)
            log.warning("database not ready (attempt %d/%d): %s; retrying in %ds", n, attempts, str(exc).splitlines()[0][:160], delay)
            time.sleep(delay)


def ping() -> dict[str, Any]:
    """Round-trip latency of SELECT 1 on a pooled connection, plus pool occupancy. Never raises."""
    started = time.perf_counter()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        ok, error = True, None
    except Exception as exc:  # noqa: BLE001
        ok, error = False, str(exc).splitlines()[0][:200]
    latency = round((time.perf_counter() - started) * 1000, 1)
    pool: dict[str, Any] = {}
    try:
        p = engine.pool
        pool = {"size": p.size(), "in_use": p.checkedout(), "overflow": p.overflow()}  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001  (SQLite's pool has no such counters)
        pass
    return {"ok": ok, "latency_ms": latency, "error": error, "pool": pool}


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── Transactional outbox for realtime messages ─────────────────────────────────
# Messages are queued on the session and only published once the transaction has
# committed, so the dashboard never refetches state that is not yet visible.
def notify(db: Session, org_id: str, payload: dict[str, Any]) -> None:
    db.info.setdefault("outbox", []).append((org_id, payload))


@event.listens_for(Session, "after_commit")
def _flush_outbox(session: Session) -> None:
    messages = session.info.pop("outbox", None)
    if not messages:
        return
    from .realtime import hub

    for org_id, payload in messages:
        hub.publish(org_id, payload)


@event.listens_for(Session, "after_rollback")
def _drop_outbox(session: Session) -> None:
    session.info.pop("outbox", None)
