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

ROLES = ["administrator", "data_analyst", "developer", "website_owner"]
ROLE_LABELS = {"administrator": "Admin", "data_analyst": "Data Analyst", "developer": "Developer", "website_owner": "Website Owner"}
# Accounts created before the role change keep working: their stored role is mapped on every read.
LEGACY_ROLES = {"product_analyst": "data_analyst", "engineer": "developer", "marketing_operator": "website_owner", "reviewer": "data_analyst"}
SITE_LOGIN_ROLES = ["data_analyst", "developer", "website_owner"]  # administrator needs a named account


def normalise_role(role: str | None) -> str:
    r = LEGACY_ROLES.get(role or "", role or "")
    return r if r in ROLES else "data_analyst"


PERMISSIONS: dict[str, set[str]] = {
    "administrator": {"*"},
    "data_analyst": {
        "read", "finance:read", "finance:control", "chunks:review", "incidents:analyze", "actions:approve:analytical",
        "knowledge:write", "outcomes:evaluate", "demo:simulate",
    },
    "developer": {
        "read", "finance:read", "chunks:review", "incidents:analyze", "actions:approve:engineering", "actions:approve:support",
        "actions:approve:analytical", "resolutions:write", "knowledge:write", "logs:read",
    },
    "website_owner": {
        "read", "finance:read", "finance:control", "emails:approve", "actions:approve:marketing", "actions:approve:analytical", "outcomes:evaluate",
    },
}

# Endpoints a website-ID session may never reach, whatever its role: they expose other tenants' sites, secrets or the server itself.
SITE_FORBIDDEN_MESSAGE = "This area is restricted. A website-ID session only sees its own website; sign in with an administrator account for server-wide access."


@dataclass(frozen=True)
class Principal:
    id: str
    org_id: str
    email: str
    name: str
    role: str
    site_host: str | None = None  # set for website-ID sessions: every query is limited to this website
    website_id: str | None = None
    viewing: bool = False  # an administrator who picked one website to look at: data is filtered like a website-ID session, access is not reduced

    def can(self, perm: str) -> bool:
        grants = PERMISSIONS.get(self.role, set())
        return "*" in grants or perm in grants

    @property
    def scoped(self) -> bool:
        return self.site_host is not None

    @property
    def actor(self) -> str:
        return f"{self.name} <{self.email}>"


class SiteScopeError(Exception):
    """Raised when a website-ID session reaches an area it may not use. main.py turns it into {"detail", "code": "site_scope"} (HTTP 403)."""

    def __init__(self, site: str | None = None) -> None:
        super().__init__(SITE_FORBIDDEN_MESSAGE)
        self.site = site


def forbid_scoped(p: Principal) -> None:
    if p.scoped and not p.viewing:
        raise SiteScopeError(p.site_host)


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


def create_token(user: User, site: tuple[str, str] | None = None) -> str:
    now = utcnow()
    payload = {
        "sub": user.id,
        "org": user.org_id,
        "role": normalise_role(user.role),
        **({"sh": site[0], "sc": site[1]} if site else {}),  # website-ID session: host + website id
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
    return Principal(user.id, user.org_id, user.email, user.name, normalise_role(user.role), claims.get("sh"), claims.get("sc"))


def current_principal(
    request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> Principal:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    p = principal_from_token(db, creds.credentials)
    host = (request.headers.get("x-churnce-site") or "").strip().lower()[:253]
    if host and not p.scoped and "*" in PERMISSIONS.get(p.role, set()):
        # Administrator picked a website: every metric is limited to it until the selection is cleared. Unknown hosts are ignored.
        from .models import ConnectedSite
        from .plans import code_for_host

        if db.scalar(select(ConnectedSite.id).where(ConnectedSite.org_id == p.org_id, ConnectedSite.host == host)):
            p = Principal(p.id, p.org_id, p.email, p.name, p.role, host, code_for_host(db, p.org_id, host), True)
    return p


def require(*perms: str):
    """Dependency factory: caller must hold at least one of the listed permissions."""

    def dep(p: Principal = Depends(current_principal)) -> Principal:
        if not any(p.can(x) for x in perms):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Your role ({p.role}) cannot perform this action")
        return p

    return dep


def require_unscoped(*perms: str):
    """Like `require`, but also refuses website-ID sessions (server logs, audit, config, users, demo, governance, RAG library)."""
    inner = require(*perms)

    def dep(p: Principal = Depends(inner)) -> Principal:
        forbid_scoped(p)
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
