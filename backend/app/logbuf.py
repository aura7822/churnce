"""In-memory ring buffer of backend log records, served to the dashboard's Backend logs page.

It is a diagnostic aid, not an audit trail: it is bounded, lost on restart, and per-process. Secrets that can
appear in log lines (bearer tokens, ingest keys, database passwords) are masked before storage.
"""
from __future__ import annotations

import itertools
import logging
import re
import threading
import time
from collections import deque
from typing import Any

from .utils import iso, utcnow

CAPACITY = 2000
_REDACT = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"), r"\1***"),
    (re.compile(r"(?i)(x-churnce-key[\"':= ]+)[A-Za-z0-9._\-]+"), r"\1***"),
    (re.compile(r"(?i)(postgres(?:ql)?(?:\+\w+)?://[^:/\s]+:)[^@\s]+(@)"), r"\1***\2"),
    (re.compile(r"(?i)((?:password|secret|api[_-]?key|token)[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"), r"\1***"),
]
STARTED = time.time()


def redact(text: str) -> str:
    for pat, rep in _REDACT:
        text = pat.sub(rep, text)
    return text


class RingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self._buf: deque[dict[str, Any]] = deque(maxlen=CAPACITY)
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = redact(record.getMessage())
            if record.exc_info:
                message += "\n" + redact(self.formatter.formatException(record.exc_info) if self.formatter else logging.Formatter().formatException(record.exc_info))
            row = {"id": 0, "ts": iso(utcnow()), "level": record.levelname, "logger": record.name, "message": message[:4000], "epoch": record.created}
            with self._lock:
                row["id"] = next(self._ids)
                self._buf.append(row)
        except Exception:  # noqa: BLE001  (logging must never break the app)
            self.handleError(record)

    def since(self, after: int = 0, level: str | None = None, limit: int = 300) -> list[dict[str, Any]]:
        floor = {"INFO": 0, "WARNING": 1, "ERROR": 2}.get((level or "INFO").upper(), 0)
        rank = {"DEBUG": 0, "INFO": 0, "WARNING": 1, "ERROR": 2, "CRITICAL": 2}
        with self._lock:
            rows = [r for r in self._buf if r["id"] > after and rank.get(r["level"], 0) >= floor]
        return rows[-limit:]

    def count_recent(self, seconds: int = 300) -> dict[str, int]:
        cutoff = time.time() - seconds
        with self._lock:
            rows = [r for r in self._buf if r["epoch"] >= cutoff]
        return {
            "errors": sum(1 for r in rows if r["level"] in ("ERROR", "CRITICAL")),
            "warnings": sum(1 for r in rows if r["level"] == "WARNING"),
        }

    def __len__(self) -> int:
        return len(self._buf)


handler = RingHandler()


def install() -> None:
    """Attach once to the root logger and to uvicorn's loggers (the access logger does not propagate)."""
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        if handler not in lg.handlers:
            lg.addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
