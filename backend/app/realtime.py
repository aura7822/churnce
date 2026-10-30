from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from .utils import iso, utcnow

log = logging.getLogger("churnce.realtime")


class Hub:
    """In-process pub/sub fan-out to WebSocket subscribers, scoped per tenant."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def subscribe(self, org_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subs[org_id].add(q)
        return q

    def unsubscribe(self, org_id: str, q: asyncio.Queue) -> None:
        self._subs[org_id].discard(q)

    def _deliver(self, org_id: str, payload: dict[str, Any]) -> None:
        for q in list(self._subs.get(org_id, ())):
            if q.full():
                try:
                    q.get_nowait()  # drop the oldest message rather than block the producer
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(payload)

    def publish(self, org_id: str, payload: dict[str, Any]) -> None:
        """Thread-safe. Safe to call from request handlers and scheduler threads."""
        if self.loop is None or self.loop.is_closed():
            return
        message = {"ts": iso(utcnow()), **payload}
        try:
            self.loop.call_soon_threadsafe(self._deliver, org_id, message)
        except RuntimeError:  # loop shutting down
            log.debug("dropped realtime message during shutdown")

    @property
    def subscriber_count(self) -> int:
        return sum(len(s) for s in self._subs.values())


hub = Hub()
