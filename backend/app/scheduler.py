"""Background scheduler.

Every time-based behaviour in Churnce (the 30-second review gate, idle-session chunking, indexing
retries, queued analyses, retention) is driven from here, from backend state. Nothing depends on a
browser tab staying open. Every transition the sweeps make is a conditional UPDATE ("claim"), so a
second worker, a restart mid-sweep or a repeated tick can never double-process a chunk.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta
from typing import Callable

from .chunk_pipeline import sweep_indexing, sweep_review_gate
from .chunking import flush_idle_sessions
from .config import get_settings
from .database import SessionLocal
from .intelligence import sweep_analysis
from .retention import purge_all
from .utils import iso, utcnow

log = logging.getLogger("churnce.scheduler")
settings = get_settings()

RETENTION_EVERY = timedelta(hours=6)


class Scheduler:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_tick = None
        self.last_error: str | None = None
        self.ticks = 0
        self._last_retention = utcnow() - RETENTION_EVERY + timedelta(minutes=2)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="churnce-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    @property
    def healthy(self) -> bool:
        if not self._thread or not self._thread.is_alive() or not self.last_tick:
            return False
        return (utcnow() - self.last_tick).total_seconds() < max(10, settings.scheduler_tick_seconds * 10)

    def status(self) -> dict:
        return {"healthy": self.healthy, "last_tick": iso(self.last_tick), "ticks": self.ticks, "last_error": self.last_error}

    def _step(self, name: str, fn: Callable) -> None:
        # One session per step: a failure in one sweep rolls back only that sweep.
        db = SessionLocal()
        try:
            fn(db)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            self.last_error = f"{name}: {exc}"[:300]
            log.exception("scheduler step %s failed", name)
        finally:
            db.close()

    def tick(self) -> None:
        """One full pass. Public so tests can drive the pipeline deterministically."""
        self._step("idle_chunking", flush_idle_sessions)
        self._step("review_gate", sweep_review_gate)
        self._step("indexing", sweep_indexing)
        self._step("analysis", sweep_analysis)
        if utcnow() - self._last_retention >= RETENTION_EVERY:
            self._last_retention = utcnow()
            self._step("retention", purge_all)
        self.last_tick = utcnow()
        self.ticks += 1

    def _run(self) -> None:
        log.info("scheduler started (tick=%ss, review window=%ss)", settings.scheduler_tick_seconds, settings.review_seconds)
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception("scheduler tick crashed")
            self._stop.wait(max(0.05, settings.scheduler_tick_seconds - (time.monotonic() - started)))


scheduler = Scheduler()
