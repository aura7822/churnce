"""Connected websites, role assignment, per-site logs/activity, activity time-series and documentation feedback.

Site feeds are an in-memory ring per (tenant, host): diagnostic and bounded, like the backend log buffer. Everything
durable (events, sessions, sites, consent, feedback) lives in the database."""
from __future__ import annotations

import re
import secrets
import threading
from collections import defaultdict, deque
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .audit import audit
from .config import get_settings
from .database import get_db, notify
from .logbuf import redact
from .models import Chunk, ConnectedSite, DocFeedback, Event, Incident, MonitoringConfig, Organization, SessionRec, SiteIdentity, User
from .scope import session_ids
from .security import ROLES, Principal, client_ip, create_token, forbid_scoped, hash_password, ingest_config, limiter, normalise_role, require, require_unscoped
from .utils import iso, sha256, utcnow

router = APIRouter()
settings = get_settings()
CONSENT_SCOPES = ("session", "cookies", "user_data", "finance")
ONLINE_SECONDS = 90
FEED_CAPACITY = 500


# ───────────────────────── per-site feed ─────────────────────────
class SiteFeed:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=FEED_CAPACITY))
        self._seq = 0
        self._lock = threading.Lock()

    def add(self, org_id: str, host: str, kind: Literal["log", "activity"], level: str, message: str) -> None:
        with self._lock:
            self._seq += 1
            self._rows[(org_id, host)].append(
                {"id": self._seq, "ts": iso(utcnow()), "kind": kind, "level": level, "message": redact(message)[:500]}
            )

    def since(self, org_id: str, host: str, after: int, kind: str | None, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = [r for r in self._rows.get((org_id, host), ()) if r["id"] > after and (not kind or r["kind"] == kind)]
        return rows[-limit:]


feed = SiteFeed()


def _clean_host(host: str) -> str:
    return re.sub(r"[^a-z0-9.\-:]", "", (host or "").lower())[:200]


def _site(db: Session, org_id: str, host: str) -> ConnectedSite:
    host = _clean_host(host)
    site = db.scalar(select(ConnectedSite).where(ConnectedSite.org_id == org_id, ConnectedSite.host == host))
    if not site:
        site = ConnectedSite(org_id=org_id, host=host, first_seen=utcnow(), last_seen=utcnow())
        db.add(site)
        db.flush()
        feed.add(org_id, host, "log", "INFO", f"Site {host} connected for the first time")
    return site


def record_ingest(db: Session, cfg: MonitoringConfig, events: list[Any], accepted: int, rejected: list[dict[str, Any]], default_host: str | None) -> None:
    """Called from POST /events after ingestion: keeps the site registry and live feeds in step with real traffic."""
    by_host: dict[str, list[Any]] = defaultdict(list)
    for ev in events:
        host = _clean_host((getattr(ev, "site_host", None) or default_host or "").split(":")[0])
        if host:
            by_host[host].append(ev)
    now = utcnow()
    for host, evs in by_host.items():
        site = _site(db, cfg.org_id, host)
        site.last_seen = now
        site.event_count = (site.event_count or 0) + len(evs)
        for ev in evs[:25]:
            parts = [ev.event_type, ev.page_route or "/"]
            if getattr(ev, "outcome", None):
                parts.append(f"outcome={ev.outcome}")
            if getattr(ev, "response_time_ms", None) is not None:
                parts.append(f"{ev.response_time_ms}ms")
            feed.add(cfg.org_id, host, "activity", "INFO", " · ".join(parts))
        if not site.consent.get("scopes"):
            feed.add(cfg.org_id, host, "log", "WARNING", "Events received but no consent record exists for this site")
    for r in rejected[:10]:
        host = _clean_host((default_host or "").split(":")[0])
        if host:
            feed.add(cfg.org_id, host, "log", "WARNING", f"Event rejected: {r.get('reason')}")
    if by_host:
        notify(db, cfg.org_id, {"type": "site_activity", "sites": sorted(by_host), "accepted": accepted})


# ───────────────────────── serialisers ─────────────────────────
def ident_for(db: Session, site_id: str) -> SiteIdentity | None:
    return db.scalar(select(SiteIdentity).where(SiteIdentity.site_id == site_id))


def ident_map(db: Session, org_id: str) -> dict[str, SiteIdentity]:
    return {i.site_id: i for i in db.scalars(select(SiteIdentity).where(SiteIdentity.org_id == org_id)).all()}


def ser_identity(i: SiteIdentity | None) -> dict[str, Any]:
    return {"website_id": i.website_code if i else None, "name": i.name if i else "", "owner_name": i.owner_name if i else "", "has_credentials": bool(i and i.password_hash)}


def ser_site(s: ConnectedSite, ident: SiteIdentity | None = None) -> dict[str, Any]:
    age = (utcnow() - s.last_seen).total_seconds() if s.last_seen else 1e9
    scopes = list((s.consent or {}).get("scopes", []))
    return {
        "id": s.id, "host": s.host, "role": s.role, "access_enabled": s.access_enabled,
        "online": age <= ONLINE_SECONDS, "monitoring": s.monitoring, "event_count": s.event_count,
        "consent": {"scopes": scopes, "accepted_at": (s.consent or {}).get("accepted_at"), "extension_version": (s.consent or {}).get("extension_version")},
        "consented": "session" in scopes, "cookie_summary": s.cookie_summary or {},
        "first_seen": iso(s.first_seen), "last_seen": iso(s.last_seen),
        **ser_identity(ident),
    }


def _own_site(db: Session, site_id: str, p: Principal) -> ConnectedSite:
    s = db.get(ConnectedSite, site_id)
    if not s or s.org_id != p.org_id:
        raise HTTPException(404, "Site not found")
    return s


# ───────────────────────── extension → backend ─────────────────────────
class ConsentIn(BaseModel):
    scopes: list[Literal["session", "cookies", "user_data", "finance"]] = Field(default_factory=list, max_length=4)
    accepted_at: str | None = Field(default=None, max_length=40)
    extension_version: str | None = Field(default=None, max_length=20)


class CookieSummary(BaseModel):
    total: int = Field(default=0, ge=0, le=5000)
    session_cookies: int = Field(default=0, ge=0, le=5000)
    secure: int = Field(default=0, ge=0, le=5000)
    http_only: int = Field(default=0, ge=0, le=5000)
    session_present: bool = False


class HeartbeatIn(BaseModel):
    site_host: str = Field(max_length=200)
    monitoring: bool = False
    consent: ConsentIn | None = None
    cookies: CookieSummary | None = None
    rtt_ms: int | None = Field(default=None, ge=0, le=60000)  # the extension's previous round trip, shown as the ping on the liquidity page


RTT: dict[tuple[str, str], int] = {}


@router.post("/sites/heartbeat")
def heartbeat(body: HeartbeatIn, cfg: MonitoringConfig = Depends(ingest_config), db: Session = Depends(get_db)):
    limiter.check(f"hb:{cfg.id}", 120)
    host = _clean_host(body.site_host.split(":")[0])
    domains = [d.lower() for d in (cfg.authorized_domains or [])]
    if not host or not any(host == d or (d.startswith("*.") and host.endswith(d[1:])) for d in domains):
        raise HTTPException(403, "That domain is not authorised for this tenant")
    site = _site(db, cfg.org_id, host)
    site.last_seen = utcnow()
    changed_monitoring = site.monitoring != body.monitoring
    site.monitoring = body.monitoring
    if body.rtt_ms is not None:
        RTT[(cfg.org_id, host)] = body.rtt_ms
    if body.consent is not None:
        had = set((site.consent or {}).get("scopes", []))
        site.consent = body.consent.model_dump()
        if set(body.consent.scopes) != had:
            feed.add(cfg.org_id, host, "log", "INFO", f"Consent updated: {', '.join(body.consent.scopes) or 'none'}")
    if body.cookies is not None and "cookies" in (site.consent or {}).get("scopes", []):
        site.cookie_summary = body.cookies.model_dump()
    if changed_monitoring:
        feed.add(cfg.org_id, host, "log", "INFO", f"Monitoring {'on' if body.monitoring else 'off'}")
    notify(db, cfg.org_id, {"type": "site_activity", "sites": [host], "accepted": 0})
    ident = ident_for(db, site.id)
    from .plans import capture_state, premium_blob
    capture = capture_state(db, cfg.org_id)["state"]
    premium = premium_blob(db, cfg.org_id, host)
    db.commit()
    return {"ok": True, "site_id": site.id, "role": site.role, "access_enabled": site.access_enabled, "premium": premium, "finance_capture": capture, **ser_identity(ident)}


class AccessIn(BaseModel):
    site_host: str = Field(max_length=200)


@router.post("/sites/access")
def enable_access(body: AccessIn, p: Principal = Depends(require_unscoped("users:manage")), db: Session = Depends(get_db)):
    """Operator action from the extension: enable dashboard access for a site's owner and mint a one-time sign-in code."""
    site = _site(db, p.org_id, body.site_host.split(":")[0])
    return _issue_code(db, p, site)


def _issue_code(db: Session, p: Principal, site: ConnectedSite) -> dict[str, Any]:
    code = secrets.token_urlsafe(24)
    site.access_enabled = True
    site.access_code_hash = sha256(code)
    site.access_code_expires = utcnow() + timedelta(hours=24)
    if site.owner_user_id:
        u = db.get(User, site.owner_user_id)
        if u:
            u.active = True
            u.role = site.role
    audit(db, p.org_id, p.actor, "site_access_enabled", "site", site.id, None, site.role, {"host": site.host})
    feed.add(p.org_id, site.host, "log", "INFO", f"Dashboard access enabled for role {site.role} by {p.name}")
    db.commit()
    return {"site_id": site.id, "host": site.host, "role": site.role, "code": code, "expires_at": iso(site.access_code_expires)}


class CodeIn(BaseModel):
    code: str = Field(min_length=10, max_length=100)


@router.post("/auth/site-access")
def redeem(body: CodeIn, request: Request, db: Session = Depends(get_db)):
    limiter.check(f"site-access:{client_ip(request)}", settings.login_rate_limit)
    site = db.scalar(select(ConnectedSite).where(ConnectedSite.access_code_hash == sha256(body.code)))
    if not site or not site.access_enabled or not site.access_code_expires or site.access_code_expires < utcnow():
        raise HTTPException(401, "This access link is invalid or has expired")
    user = db.get(User, site.owner_user_id) if site.owner_user_id else None
    if not user:
        slug = re.sub(r"[^a-z0-9]+", "-", site.host).strip("-")
        user = User(org_id=site.org_id, email=f"owner+{slug}@sites.churnce.local", name=f"{site.host} team", role=site.role,
                    password_hash=hash_password(secrets.token_urlsafe(32)))
        db.add(user)
        db.flush()
        site.owner_user_id = user.id
    user.role, user.active = site.role, True
    site.access_code_hash = None  # one-time
    site.access_code_expires = None
    audit(db, site.org_id, f"site:{site.host}", "site_access_redeemed", "site", site.id, None, site.role)
    feed.add(site.org_id, site.host, "log", "INFO", f"Owner signed in to the dashboard as {site.role}")
    org = db.get(Organization, site.org_id)
    db.commit()
    ident = ident_for(db, site.id)
    return {"token": create_token(user, (site.host, ident.website_code if ident else "")), "scope": {"site_host": site.host, "website_id": ident.website_code if ident else "", "name": ident.name if ident else site.host, "owner_name": ident.owner_name if ident else ""},
            "user": {"id": user.id, "name": user.name, "email": user.email, "role": normalise_role(user.role)},
            "organization": {"id": org.id, "name": org.name}, "environment": "production"}


# ───────────────────────── dashboard: sites ─────────────────────────
@router.get("/sites")
def list_sites(p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    q = select(ConnectedSite).where(ConnectedSite.org_id == p.org_id)
    if p.scoped:
        q = q.where(ConnectedSite.host == p.site_host)
    rows = db.scalars(q.order_by(ConnectedSite.last_seen.desc())).all()
    idents = ident_map(db, p.org_id)
    from .plans import access_info

    out = []
    for s in rows:
        row = ser_site(s, idents.get(s.id))
        info = access_info(db, p.org_id, s.host)  # subscription status and free-trial countdown for each website
        row["plan"] = {"active": info["active"], "source": info["source"], "subscribed": info["subscribed"], "trial_used": info["trial"]["used"],
                       "trial_ends_at": info["trial"]["ends_at"], "seconds_left": info["trial"]["seconds_left"]}
        out.append(row)
    return {"sites": out, "roles": ROLES, "server_time": iso(utcnow())}


def _end_site_logins(db: Session, site: ConnectedSite) -> None:
    """Deactivate every extension sign-in that was minted from this site's website id (site+<id>+<role>@sites.churnce.local)."""
    ident = ident_for(db, site.id)
    if not ident:
        return
    for u in db.scalars(select(User).where(User.email.like(f"site+{ident.website_code.lower()}+%@sites.churnce.local"))).all():
        u.active = False


class SitePatch(BaseModel):
    role: Literal["administrator", "data_analyst", "developer", "website_owner"] | None = None
    access_enabled: bool | None = None


@router.patch("/sites/{site_id}")
def patch_site(site_id: str, body: SitePatch, p: Principal = Depends(require_unscoped("users:manage")), db: Session = Depends(get_db)):
    s = _own_site(db, site_id, p)
    if body.role and body.role != s.role:
        audit(db, p.org_id, p.actor, "site_role_changed", "site", s.id, s.role, body.role, {"host": s.host})
        feed.add(p.org_id, s.host, "log", "INFO", f"Role changed {s.role} → {body.role} by {p.name}")
        s.role = body.role
        _end_site_logins(db, s)  # a role change takes effect at the next sign-in
    if body.access_enabled is not None and body.access_enabled != s.access_enabled:
        s.access_enabled = body.access_enabled
        if not body.access_enabled:
            s.access_code_hash = None
            _end_site_logins(db, s)
            audit(db, p.org_id, p.actor, "site_access_revoked", "site", s.id, None, None, {"host": s.host})
            feed.add(p.org_id, s.host, "log", "WARNING", f"Dashboard access revoked by {p.name}")
        else:
            audit(db, p.org_id, p.actor, "site_access_enabled", "site", s.id, None, s.role, {"host": s.host})
    if s.owner_user_id:
        u = db.get(User, s.owner_user_id)
        if u:
            u.role, u.active = s.role, s.access_enabled
    db.commit()
    return ser_site(s, ident_for(db, s.id))


@router.get("/sites/{site_id}/feed")
def site_feed(
    site_id: str, after: int = Query(0, ge=0), kind: Literal["log", "activity"] | None = None, limit: int = Query(200, ge=1, le=500),
    p: Principal = Depends(require_unscoped("read")), db: Session = Depends(get_db),
):
    s = _own_site(db, site_id, p)  # server logs and the sites area are administrator-only: website-ID sessions get 403 from require_unscoped
    if not p.can("logs:read"):
        raise HTTPException(403, f"Your role ({p.role}) cannot perform this action")
    return {"site": ser_site(s, ident_for(db, s.id)), "rows": feed.since(p.org_id, s.host, after, kind, limit), "server_time": iso(utcnow())}


# ───────────────────────── time-series ─────────────────────────
def _bucket(ts, start, step: int) -> int:
    return int((ts - start).total_seconds() // step)


@router.get("/sites-series")
def sites_series(minutes: int = Query(15, ge=5, le=120), p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    """Events per bucket for each connected site: the live multi-line chart. Reads persisted events, so it survives restarts."""
    step = 15 if minutes <= 30 else 60
    now = utcnow()
    n = minutes * 60 // step
    start = now - timedelta(seconds=n * step)
    rows = db.execute(
        select(SessionRec.site_host, Event.received_at)
        .join(SessionRec, SessionRec.id == Event.session_id)
        .where(Event.org_id == p.org_id, Event.received_at >= start, *([SessionRec.site_host == p.site_host] if p.scoped else []))
        .limit(20000)
    ).all()
    counts: dict[str, list[int]] = defaultdict(lambda: [0] * n)
    for host, ts in rows:
        i = _bucket(ts, start, step)
        if host and 0 <= i < n:
            counts[host][i] += 1
    sites = db.scalars(select(ConnectedSite).where(ConnectedSite.org_id == p.org_id, *([ConnectedSite.host == p.site_host] if p.scoped else []))).all()
    for s in sites:
        counts.setdefault(s.host, [0] * n)
    online = {s.host: (utcnow() - s.last_seen).total_seconds() <= ONLINE_SECONDS for s in sites}
    series = [{"host": h, "counts": c, "total": sum(c), "online": online.get(h, False)} for h, c in sorted(counts.items(), key=lambda kv: -sum(kv[1]))][:8]
    return {"step_seconds": step, "buckets": [iso(start + timedelta(seconds=(i + 1) * step)) for i in range(n)], "series": series, "server_time": iso(now)}


@router.get("/timeseries")
def timeseries(hours: int = Query(24, ge=6, le=72), p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    """Hourly events, chunks and incidents plus event-type mix, for the overview graphs."""
    now = utcnow()
    start = (now - timedelta(hours=hours)).replace(minute=0, second=0, microsecond=0)
    n = hours + 1

    def hourly(col, *where):
        out = [0] * n
        for (ts,) in db.execute(select(col).where(*where).limit(50000)).all():
            i = int((ts - start).total_seconds() // 3600)
            if 0 <= i < n:
                out[i] += 1
        return out

    ev_scope = [Event.session_id.in_(session_ids(p))] if p.scoped else []
    ch_scope = [Chunk.session_id.in_(session_ids(p))] if p.scoped else []
    events = hourly(Event.received_at, Event.org_id == p.org_id, Event.received_at >= start, *ev_scope)
    chunks = hourly(Chunk.created_at, Chunk.org_id == p.org_id, Chunk.created_at >= start, *ch_scope)
    if p.scoped:
        from .scope import incident_ids
        mine = incident_ids(db, p)
        incidents = [0] * n
        for (iid, ts) in db.execute(select(Incident.id, Incident.last_seen_at).where(Incident.org_id == p.org_id, Incident.last_seen_at >= start).limit(5000)).all():
            i = int((ts - start).total_seconds() // 3600)
            if iid in mine and 0 <= i < n:
                incidents[i] += 1
    else:
        incidents = hourly(Incident.last_seen_at, Incident.org_id == p.org_id, Incident.last_seen_at >= start)
    mix = db.execute(select(Event.event_type, func.count()).where(Event.org_id == p.org_id, Event.received_at >= start, *ev_scope).group_by(Event.event_type)).all()
    stages = db.execute(select(Event.journey_stage, func.count()).where(Event.org_id == p.org_id, Event.received_at >= start, *ev_scope).group_by(Event.journey_stage)).all()
    return {
        "hours": [iso(start + timedelta(hours=i)) for i in range(n)],
        "events": events, "chunks": chunks, "incidents": incidents,
        "event_types": sorted(({"label": k, "value": v} for k, v in mix), key=lambda d: -d["value"])[:8],
        "journey_stages": sorted(({"label": k, "value": v} for k, v in stages), key=lambda d: -d["value"]),
        "server_time": iso(now),
    }


# ───────────────────────── documentation feedback ─────────────────────────
class FeedbackIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=1000)


@router.get("/docs/feedback")
def list_feedback(p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    rows = db.scalars(select(DocFeedback).where(DocFeedback.org_id == p.org_id).order_by(DocFeedback.created_at.desc()).limit(100)).all()
    dist = {str(i): 0 for i in range(1, 6)}
    for r in rows:
        dist[str(r.rating)] += 1
    avg = round(sum(r.rating for r in rows) / len(rows), 2) if rows else 0
    return {
        "average": avg, "count": len(rows), "distribution": dist,
        "entries": [{"id": r.id, "author": r.author, "rating": r.rating, "comment": r.comment, "created_at": iso(r.created_at), "mine": r.user_id == p.id} for r in rows],
    }


@router.post("/docs/feedback", status_code=201)
def add_feedback(body: FeedbackIn, p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    limiter.check(f"docfb:{p.id}", 10)
    db.add(DocFeedback(org_id=p.org_id, user_id=p.id, author=p.name, rating=body.rating, comment=body.comment.strip()))
    db.commit()
    return {"ok": True}
