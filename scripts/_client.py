"""Tiny stdlib-only HTTP client shared by the demo scripts (no pip install needed)."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Callable


class ApiError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.token: str | None = None

    def request(self, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None, timeout: float = 30) -> Any:
        hdrs = {"Accept": "application/json", **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        if self.token:
            hdrs["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(f"{self.base}/api/v1{path}", data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            try:
                detail = json.loads(detail).get("detail", detail)
            except ValueError:
                pass
            raise ApiError(exc.code, str(detail)) from None
        except urllib.error.URLError as exc:
            sys.exit(f"Cannot reach {self.base} ({exc.reason}). Is the backend running? Try: docker compose up --build")

    def login(self, email: str, password: str) -> dict:
        out = self.request("POST", "/auth/login", {"email": email, "password": password})
        self.token = out["token"]
        return out


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def wait_for(fn: Callable[[], Any], timeout: float, interval: float = 1.5, label: str = "condition") -> Any:
    """Poll until fn() returns something truthy; returns it, or None on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        got = fn()
        if got:
            return got
        time.sleep(interval)
    print(f"  ! timed out after {timeout:.0f}s waiting for {label}", file=sys.stderr)
    return None
