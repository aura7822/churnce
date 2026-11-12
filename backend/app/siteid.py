"""Website identity: id, display name and owner, a generated password, and sign-in from the extension with a non-admin role."""
from __future__ import annotations

import re
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import audit
from .config import get_settings
from .database import get_db, notify
from .models import ConnectedSite, MonitoringConfig, Organization, SiteIdentity, User
from .security import ROLE_LABELS, SITE_LOGIN_ROLES, client_ip, create_token, hash_password, ingest_config, limiter, verify_password
from .utils import iso, utcnow
from .workspace import _clean_host, _site, feed, ident_for, ser_identity

router = APIRouter()
settings = get_settings()
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L: readable when copied by hand
_dummy: str | None = None


def new_code(db: Session) -> str:
    for _ in range(20):
        code = "WS-" + "".join(secrets.choice(ALPHABET) for _ in range(6))
        if not db.scalar(select(SiteIdentity.id).where(SiteIdentity.website_code == code)):
            return code
    raise HTTPException(500, "Could not allocate a website id")


def new_password() -> str:
    return "-".join("".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(3))  # 12 symbols, ~59 bits


def clean_name(v: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f<>]", "", v or "")).strip()[:120]


class RegisterIn(BaseModel):
    site_host: str = Field(max_length=200)
    name: str = Field(default="", max_length=120)
    owner_name: str = Field(default="", max_length=120)
    regenerate_password: bool = False


@router.post("/sites/register")
def register(body: RegisterIn, cfg: MonitoringConfig = Depends(ingest_config), db: Session = Depends(get_db)):
    """Extension: set the site's name and owner, and (on request) generate its website id and password. The password is returned once."""
    limiter.check(f"reg:{cfg.id}", 30)
    host = _clean_host(body.site_host.split(":")[0])
    domains = [d.lower() for d in (cfg.authorized_domains or [])]
    if not host or not any(host == d or (d.startswith("*.") and host.endswith(d[1:])) for d in domains):
        raise HTTPException(403, "That domain is not authorised for this tenant")
    name, owner = clean_name(body.name), clean_name(body.owner_name)
    if body.regenerate_password and (not name or not owner):
        raise HTTPException(422, "Enter the website name and owner name before generating credentials")
    site = _site(db, cfg.org_id, host)
    ident = ident_for(db, site.id)
    created = ident is None
    if created:
        ident = SiteIdentity(site_id=site.id, org_id=cfg.org_id, website_code=new_code(db), name=name, owner_name=owner)
        db.add(ident)
    else:
        ident.name, ident.owner_name, ident.updated_at = name or ident.name, owner or ident.owner_name, utcnow()
    password = None
    if body.regenerate_password:
        password = new_password()
        ident.password_hash = hash_password(password)
        ident.password_rotated_at = utcnow()
        site.access_enabled = True  # generating credentials is the administrator-side act of granting access; the dashboard toggle can revoke it
    db.flush()
    feed.add(cfg.org_id, host, "log", "INFO", f"{'Website id ' + ident.website_code + ' created' if created else 'Identity updated'}"
             f"{' · new password generated' if password else ''} · owner {ident.owner_name or '(unset)'}")
    audit(db, cfg.org_id, f"extension:{host}", "site_identity_" + ("created" if created else "updated"), "site", site.id, None, None, {"password_rotated": bool(password)})
    notify(db, cfg.org_id, {"type": "site_activity", "sites": [host], "accepted": 0})
    db.commit()
    return {**ser_identity(ident), "site_id": site.id, "host": host, "role": site.role, "created": created, "password": password,
            "password_note": "Shown once. Only a hash is stored, so a lost password is replaced by generating a new one." if password else None}


class SiteLoginIn(BaseModel):
    website_id: str = Field(min_length=4, max_length=20)
    password: str = Field(min_length=6, max_length=64)
    role: str = Field(max_length=40)


@router.post("/auth/site-login")
def site_login(body: SiteLoginIn, request: Request, db: Session = Depends(get_db)):
    """Sign in with a website id and password, choosing any role except administrator that the site's assigned role allows."""
    global _dummy
    code = body.website_id.strip().upper()
    limiter.check(f"slogin-ip:{client_ip(request)}", settings.login_rate_limit)
    limiter.check(f"slogin-id:{code}", settings.login_rate_limit)
    ident = db.scalar(select(SiteIdentity).where(SiteIdentity.website_code == code))
    if not ident or not ident.password_hash:
        _dummy = _dummy or hash_password("x")
        verify_password(body.password, _dummy)  # keep timing similar whether or not the id exists
        raise HTTPException(401, "Incorrect website ID or password")
    if not verify_password(body.password.strip().upper(), ident.password_hash):
        raise HTTPException(401, "Incorrect website ID or password")
    role = body.role
    if role == "administrator":
        raise HTTPException(403, "Administrator access is not available with a website ID. Sign in with an administrator account.")
    if role not in SITE_LOGIN_ROLES:
        raise HTTPException(422, "Choose Data Analyst, Developer or Website Owner")
    site = db.get(ConnectedSite, ident.site_id)
    if not site.access_enabled:
        raise HTTPException(403, "Access for this website is switched off. Ask an administrator to enable it under Sites and roles.")
    email = f"site+{code.lower()}+{role}@sites.churnce.local"
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        import secrets as _s
        user = User(org_id=site.org_id, email=email, name=f"{ident.name or site.host} ({ident.owner_name or 'owner'})"[:120], role=role, password_hash=hash_password(_s.token_urlsafe(32)))
        db.add(user)
        db.flush()
    else:
        user.name = f"{ident.name or site.host} ({ident.owner_name or 'owner'})"[:120]
    user.role, user.active = role, True
    audit(db, site.org_id, f"site:{site.host}", "site_login", "site", site.id, None, role)
    feed.add(site.org_id, site.host, "log", "INFO", f"Extension sign-in as {role.replace('_', ' ')}")
    org = db.get(Organization, site.org_id)
    db.commit()
    return {"token": create_token(user, (site.host, code)), "scope": {"site_host": site.host, "website_id": code, "name": ident.name, "owner_name": ident.owner_name}, "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role},
            "organization": {"id": org.id, "name": org.name}, "environment": "production", "site": {"website_id": code, "host": site.host, "name": ident.name, "owner_name": ident.owner_name, "assigned_role": site.role},
            "signed_in_at": iso(utcnow())}


class TrialIn(BaseModel):
    site_host: str = Field(max_length=200)


@router.post("/sites/trial")
def start_site_trial(body: TrialIn, cfg: MonitoringConfig = Depends(ingest_config), db: Session = Depends(get_db)):
    """Extension: start the 72-hour Premium trial for one website id. Once per website id; premium features stay on until it expires."""
    from .plans import premium_blob, start_trial

    limiter.check(f"trial:{cfg.id}", 10)
    host = _clean_host(body.site_host.split(":")[0])
    domains = [d.lower() for d in (cfg.authorized_domains or [])]
    if not host or not any(host == d or (d.startswith("*.") and host.endswith(d[1:])) for d in domains):
        raise HTTPException(403, "That domain is not authorised for this tenant")
    try:
        started, trial = start_trial(db, cfg.org_id, host)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not started:
        db.commit()
        raise HTTPException(409, "The free trial was already used for this website ID" + (" and is still running" if trial["active"] else ""))
    audit(db, cfg.org_id, f"extension:{host}", "trial_started", "site", host, None, None, {"website_id": trial["website_id"], "hours": 72})
    feed.add(cfg.org_id, host, "log", "INFO", "72-hour Premium trial started")
    notify(db, cfg.org_id, {"type": "finance_update"})
    db.commit()
    return {"ok": True, "started": True, "ends_at": trial["ends_at"], "seconds_left": trial["seconds_left"], "premium": premium_blob(db, cfg.org_id, host)}
