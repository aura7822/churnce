from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import timedelta

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import MonitoringConfig, User
from .utils import sha256, utcnow

settings = get_settings()
bearer = HTTPBearer(auto_error=False)

ROLES = ["administrator", "product_analyst", "engineer", "marketing_operator", "reviewer"]

PERMISSIONS: dict[str, set[str]] = {
    "administrator": {"*"},
    "product_analyst": {
        "read",
        "chunks:review",
        "incidents:analyze",
        "actions:approve:engineering",
        "actions:approve:support",
        "actions:approve:analytical",
        "knowledge:write",
        "outcomes:evaluate",
        "demo:simulate",
    },
    "engineer": {
        "read",
        "chunks:review",
        "incidents:analyze",
        "actions:approve:engineering",
        "actions:approve:support",
        "actions:approve:analytical",
        "resolutions:write",
        "knowledge:write",
        "logs:read",
    },
    "marketing_operator": {
        "read",
        "actions:approve:marketing",
        "actions:approve:analytical",
        "emails:approve",
        "outcomes:evaluate",
    },
    "reviewer": {"read"},
}


@dataclass(frozen=True)
class Principal:
    id: str
    org_id: str
    email: str
    name: str
    role: str

    def can(self, perm: str) -> bool:
        grants = PERMISSIONS.get(self.role, set())
        return "*" in grants or perm in grants

    @property
    def actor(self) -> str:
        return f"{self.name} <{self.email}>"


# ── Passwords and tokens ───────────────────────────────────────────────────────
_ITERATIONS = 600_000  # OWASP guidance for PBKDF2-HMAC-SHA256; stored per hash, so older hashes still verify


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS).hex()
    return f"pbkdf2${_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters)).hex()
        return hmac.compare_digest(candidate, digest)
    except Exception:
        return False


def create_token(user: User) -> str:
    now = utcnow()
    payload = {
        "sub": user.id,
        "org": user.org_id,
        "role": user.role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])


def principal_from_token(db: Session, token: str) -> Principal:
    try:
        claims = decode_token(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc
    user = db.get(User, claims.get("sub"))
    if not user or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is not active")
    return Principal(user.id, user.org_id, user.email, user.name, user.role)


def current_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> Principal:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    return principal_from_token(db, creds.credentials)


def require(*perms: str):
    """Dependency factory: caller must hold at least one of the listed permissions."""

    def dep(p: Principal = Depends(current_principal)) -> Principal:
        if not any(p.can(x) for x in perms):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Your role ({p.role}) cannot perform this action")
        return p

    return dep


# ── Ingest key auth (browser extension) ────────────────────────────────────────
def hash_ingest_key(key: str) -> str:
    return sha256(key)


def generate_ingest_key() -> str:
    return "chn_live_" + secrets.token_urlsafe(24)


def ingest_config(
    x_churnce_key: str | None = Header(default=None), db: Session = Depends(get_db)
) -> MonitoringConfig:
    if not x_churnce_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-Churnce-Key header")
    cfg = db.scalar(select(MonitoringConfig).where(MonitoringConfig.ingest_key_hash == hash_ingest_key(x_churnce_key)))
    if not cfg:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown ingest key")
    return cfg


# ── Rate limiting (sliding window, in-memory) ──────────────────────────────────
class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window: float = 60.0) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded; retry shortly")
            q.append(now)


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
