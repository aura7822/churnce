"""Codebase analyser endpoints (Pro). Connect a GitHub repository or upload a zip, then ask "where does this reported bug come from, and what does changing it touch?"."""
from __future__ import annotations

import json
from collections import Counter
import re
import zlib
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import codeanalyser as ca
from . import plans, scope as scp
from .audit import audit
from .database import get_db
from .models import Chunk, CodeProject, Incident
from .plans import PLAN_NAME
from .security import Principal, require
from .utils import iso, utcnow

router = APIRouter(prefix="/analyser", tags=["analyser"])
WRITE = ("incidents:analyze", "emails:approve")  # developers, analysts, website owners; administrators hold everything
SEV = {"critical": 4, "high": 3, "medium": 2, "low": 1}
_GH = re.compile(r"^(?:https?://github\.com/)?([A-Za-z0-9_.-]{1,100})/([A-Za-z0-9_.-]{1,100}?)(?:\.git)?/?$")


def _gate(db: Session, p: Principal) -> None:
    """Website-ID sessions need Pro or a running 72-hour trial for their website. Administrators have full access."""
    if p.scoped and not p.viewing and not plans.is_premium(db, p.org_id, p.site_host):
        raise HTTPException(402, f"The codebase analyser is part of {PLAN_NAME}. Start the 72-hour free trial or subscribe to Pro.")


def _mine(db: Session, p: Principal, pid: str) -> CodeProject:
    row = db.get(CodeProject, pid)
    if not row or row.org_id != p.org_id or (p.scoped and row.site_host != p.site_host):
        raise HTTPException(404, "Project not found")
    return row


def _ser(r: CodeProject) -> dict[str, Any]:
    return {"id": r.id, "name": r.name, "source": r.source, "repo": r.repo, "branch": r.branch, "status": r.status, "error": r.error, "site_host": r.site_host,
            "files": r.file_count, "lines": r.line_count, "stats": r.stats, "created_by": r.created_by, "created_at": iso(r.created_at), "analysed_at": iso(r.analysed_at) if r.analysed_at else None}


def _store(db: Session, p: Principal, *, name: str, source: str, repo: str, branch: str, files: dict[str, str], site_host: str | None) -> CodeProject:
    index = ca.build_index(files)
    langs: dict[str, int] = {}
    for n in index.values():
        langs[n["lang"]] = langs.get(n["lang"], 0) + 1
    issues = ca.scan_issues(files)
    row = CodeProject(org_id=p.org_id, site_host=p.site_host if p.scoped else site_host, name=name[:160] or "Untitled project", source=source, repo=repo[:300], branch=branch[:120], status="ready",
                      file_count=len(files), line_count=sum(n["lines"] for n in index.values()), blob=zlib.compress(json.dumps(files).encode(), 6), created_by=p.actor,
                      stats={"languages": langs, "issues": len(issues), "high_issues": sum(1 for i in issues if i["severity"] == "high")})
    db.add(row)
    audit(db, p.org_id, p.actor, "code_project_added", "code_project", row.id, None, source)
    db.commit()
    return row


@router.get("/projects")
def projects(p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    _gate(db, p)
    q = select(CodeProject).where(CodeProject.org_id == p.org_id).order_by(CodeProject.created_at.desc()).limit(50)
    if p.scoped:
        q = q.where(CodeProject.site_host == p.site_host)
    return {"projects": [_ser(r) for r in db.scalars(q)]}


@router.post("/projects/zip", status_code=201)
async def add_zip(request: Request, name: str = Query("Uploaded source", max_length=160), site_host: str | None = Query(None, max_length=253),
                  p: Principal = Depends(require(*WRITE)), db: Session = Depends(get_db)):
    """Raw request body = the zip file (Content-Type: application/zip). Read in chunks so an oversized upload is refused early."""
    _gate(db, p)
    size, chunks = 0, []
    async for part in request.stream():
        size += len(part)
        if size > ca.MAX_ZIP_BYTES:
            raise HTTPException(413, f"The archive is larger than {ca.MAX_ZIP_BYTES // (1024 * 1024)} MB.")
        chunks.append(part)
    try:
        files = ca.read_zip(b"".join(chunks))
    except ca.UnsafeArchive as exc:
        raise HTTPException(422, str(exc)) from exc
    return _ser(_store(db, p, name=name, source="zip", repo="", branch="", files=files, site_host=site_host))


class GithubIn(BaseModel):
    repo: str = Field(min_length=3, max_length=200)  # "owner/name" or a github.com URL
    branch: str = Field("", max_length=120)
    token: str = Field("", max_length=255)  # optional, for private repositories; used for this download only and never stored
    name: str = Field("", max_length=160)
    site_host: str | None = Field(None, max_length=253)


@router.post("/projects/github", status_code=201)
def add_github(body: GithubIn, p: Principal = Depends(require(*WRITE)), db: Session = Depends(get_db)):
    _gate(db, p)
    m = _GH.match(body.repo.strip())
    if not m:
        raise HTTPException(422, "Enter the repository as owner/name or a github.com link.")
    owner, repo = m.group(1), m.group(2)
    if not re.fullmatch(r"[A-Za-z0-9._/-]{0,120}", body.branch):
        raise HTTPException(422, "That branch name is not valid.")
    url = f"https://api.github.com/repos/{owner}/{repo}/zipball" + (f"/{body.branch}" if body.branch else "")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "churnce-analyser"}
    if body.token:
        headers["Authorization"] = f"Bearer {body.token}"
    try:
        data = bytearray()
        with httpx.stream("GET", url, headers=headers, timeout=45, follow_redirects=True) as r:  # fixed api.github.com host: no user-controlled URL
            if r.status_code in (401, 403, 404):
                raise HTTPException(422, "GitHub refused the request. Check the name and branch, or provide a token with read access for a private repository.")
            r.raise_for_status()
            for part in r.iter_bytes():
                data += part
                if len(data) > ca.MAX_ZIP_BYTES:
                    raise HTTPException(413, f"The repository archive is larger than {ca.MAX_ZIP_BYTES // (1024 * 1024)} MB. Upload the relevant folders as a zip instead.")
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Could not reach GitHub. Try again, or upload a zip.") from exc
    try:
        files = ca.read_zip(bytes(data))
    except ca.UnsafeArchive as exc:
        raise HTTPException(422, str(exc)) from exc
    return _ser(_store(db, p, name=body.name or f"{owner}/{repo}", source="github", repo=f"{owner}/{repo}", branch=body.branch, files=files, site_host=body.site_host))


@router.delete("/projects/{pid}")
def delete_project(pid: str, p: Principal = Depends(require(*WRITE)), db: Session = Depends(get_db)):
    _gate(db, p)
    row = _mine(db, p, pid)
    audit(db, p.org_id, p.actor, "code_project_deleted", "code_project", row.id, None, row.name)
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/bugs")
def reported_bugs(p: Principal = Depends(require("read")), db: Session = Depends(get_db)):
    """Bugs reported on the main dashboard, most critical first. Website-ID sessions only see their own website's."""
    _gate(db, p)
    ids = scp.incident_ids(db, p) if p.scoped else None
    rows = [i for i in db.scalars(select(Incident).where(Incident.org_id == p.org_id, Incident.status != "resolved").limit(500)) if ids is None or i.id in ids]
    rows.sort(key=lambda i: (-SEV.get(i.severity, 0), -i.severity_score))
    return {"bugs": [{"id": i.id, "title": i.title, "severity": i.severity, "signal": i.signal, "journey_stage": i.journey_stage, "affected_sessions": i.affected_sessions, "status": i.status} for i in rows[:60]]}


class AnalyseIn(BaseModel):
    incident_id: str | None = None
    description: str = Field("", max_length=1500)


def _bug_from(db: Session, p: Principal, body: AnalyseIn) -> dict[str, Any]:
    if not body.incident_id:
        if len(body.description.strip()) < 8:
            raise HTTPException(422, "Pick a reported bug or describe it in a sentence.")
        return {"title": body.description.strip()[:200], "text": body.description, "signal": "", "routes": [], "facts": [], "hypotheses": []}
    inc = db.get(Incident, body.incident_id)
    if not inc or inc.org_id != p.org_id or (p.scoped and inc.id not in scp.incident_ids(db, p)):
        raise HTTPException(404, "Incident not found")
    routes, elements, evtypes = [], [], []
    for c in db.scalars(select(Chunk).where(Chunk.org_id == p.org_id, Chunk.id.in_((inc.chunk_ids or [])[:40]))):
        for ev in (c.events or [])[:40]:
            if isinstance(ev, dict):
                if ev.get("page_route"):
                    routes.append(str(ev["page_route"])[:120])
                if ev.get("element_category"):
                    elements.append(str(ev["element_category"])[:60])
                if ev.get("event_type"):
                    evtypes.append(str(ev["event_type"])[:40])
    top = lambda xs, n: [x for x, _ in Counter(xs).most_common(n)]  # noqa: E731
    return {"title": inc.title, "signal": inc.signal, "journey_stage": inc.journey_stage, "severity": inc.severity, "facts": list(inc.observed_facts or [])[:12], "hypotheses": list(inc.hypotheses or [])[:6],
            "routes": top(routes, 4), "elements": top(elements, 4), "event_types": top(evtypes, 4), "text": inc.incident_type or ""}


@router.post("/projects/{pid}/analyse")
def analyse(pid: str, body: AnalyseIn, p: Principal = Depends(require(*WRITE)), db: Session = Depends(get_db)):
    _gate(db, p)
    row = _mine(db, p, pid)
    bug = _bug_from(db, p, body)
    try:
        files = json.loads(zlib.decompress(row.blob).decode())
    except (zlib.error, ValueError) as exc:
        raise HTTPException(500, "The stored source could not be read. Delete and re-add the project.") from exc
    out = ca.analyse(files, bug)
    row.analysed_at = utcnow()
    audit(db, p.org_id, p.actor, "code_analysed", "code_project", row.id, None, body.incident_id or "description")
    db.commit()
    out["bug"] = {"title": bug["title"], "severity": bug.get("severity"), "signal": bug.get("signal"), "incident_id": body.incident_id}
    out["project"] = _ser(row)
    return out
