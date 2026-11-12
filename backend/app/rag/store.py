"""Vector + metadata storage. pgvector on PostgreSQL, in-process cosine elsewhere."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import EvidenceRecord
from ..privacy import injection_suspected, redact
from ..utils import sha256, utcnow
from .embeddings import cosine, get_embedder

settings = get_settings()


@dataclass
class Hit:
    record: EvidenceRecord
    vector_score: float


def _vec_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def upsert_chunk_evidence(db: Session, chunk, text_: str, vector: list[float], model: str) -> EvidenceRecord:
    """Idempotent on (chunk_id, version). Older versions of the same chunk are deactivated."""
    existing = db.scalar(
        select(EvidenceRecord).where(EvidenceRecord.chunk_id == chunk.id, EvidenceRecord.chunk_version == chunk.version)
    )
    meta = {
        "journey_stage": chunk.journey_stage,
        "signal": chunk.signal,
        "issue_signature": chunk.issue_signature,
        "observations": chunk.observations,
        "simulated": chunk.simulated,
    }
    if existing:
        existing.content = text_
        existing.content_hash = sha256(text_)
        existing.embedding = vector
        existing.embedding_model = model
        existing.meta = meta
        existing.active = True
        rec = existing
    else:
        rec = EvidenceRecord(
            org_id=chunk.org_id,
            collection="customer_journey",
            source_ref=chunk.id,
            source_type="chunk",
            title=chunk.summary[:300],
            content=text_,
            content_hash=sha256(text_),
            embedding=vector,
            embedding_model=model,
            meta=meta,
            session_id=chunk.session_id,
            chunk_id=chunk.id,
            chunk_version=chunk.version,
        )
        db.add(rec)
    db.flush()
    db.execute(
        update(EvidenceRecord)
        .where(EvidenceRecord.chunk_id == chunk.id, EvidenceRecord.id != rec.id)
        .values(active=False)
    )
    return rec


def split_passages(body: str, limit: int = 900) -> list[str]:
    parts: list[str] = []
    for para in [p.strip() for p in body.replace("\r", "").split("\n\n") if p.strip()]:
        while len(para) > limit:
            cut = para.rfind(". ", 0, limit)
            cut = cut + 1 if cut > 200 else limit
            parts.append(para[:cut].strip())
            para = para[cut:].strip()
        if para:
            parts.append(para)
    return parts


def ingest_document(
    db: Session,
    org_id: str,
    collection: str,
    source_ref: str,
    title: str,
    body: str,
    meta: dict | None = None,
    source_type: str = "document",
    effective_at=None,
) -> int:
    """Chunk, redact, embed and store a knowledge document. Re-ingesting identical text is a no-op;
    changed text supersedes the previous version of the same source_ref."""
    embedder = get_embedder()
    clean_body, _ = redact(body)
    passages = split_passages(clean_body)
    if not passages:
        return 0
    hashes = [sha256(f"{i}:{p}") for i, p in enumerate(passages)]
    present = set(
        db.scalars(
            select(EvidenceRecord.content_hash).where(
                EvidenceRecord.org_id == org_id,
                EvidenceRecord.collection == collection,
                EvidenceRecord.source_ref == source_ref,
                EvidenceRecord.active.is_(True),
            )
        )
    )
    if set(hashes) == present:
        return 0
    db.execute(
        update(EvidenceRecord)
        .where(
            EvidenceRecord.org_id == org_id,
            EvidenceRecord.collection == collection,
            EvidenceRecord.source_ref == source_ref,
        )
        .values(active=False)
    )
    vectors = embedder.embed_passages([f"{title}\n{p}" for p in passages])
    now = utcnow()
    for i, (p, h, v) in enumerate(zip(passages, hashes, vectors)):
        db.add(
            EvidenceRecord(
                org_id=org_id,
                collection=collection,
                source_ref=source_ref,
                source_type=source_type,
                title=title[:300],
                content=p,
                content_hash=h,
                embedding=v,
                embedding_model=embedder.name,
                meta={**(meta or {}), "passage": i},
                quarantined=injection_suspected(p),
                effective_at=effective_at or now,
            )
        )
    db.flush()
    return len(passages)


def search(db: Session, org_id: str, query_vec: list[float], collections: list[str], k: int, model: str) -> list[Hit]:
    """Top-k per collection, always tenant-scoped and restricted to the current embedding model."""
    hits: list[Hit] = []
    for coll in collections:
        base = (
            EvidenceRecord.org_id == org_id,
            EvidenceRecord.collection == coll,
            EvidenceRecord.active.is_(True),
            EvidenceRecord.embedding_model == model,
        )
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            rows = db.scalars(
                select(EvidenceRecord)
                .where(*base)
                .order_by(text("embedding <=> CAST(:qv AS vector)"))
                .params(qv=_vec_literal(query_vec))
                .limit(k)
            ).all()
            hits += [Hit(r, cosine(query_vec, r.embedding or [])) for r in rows]
        else:
            rows = db.scalars(select(EvidenceRecord).where(*base).limit(5000)).all()
            scored = sorted(((cosine(query_vec, r.embedding or []), r) for r in rows if r.embedding), key=lambda t: -t[0])
            hits += [Hit(r, s) for s, r in scored[:k]]
    return hits


def collection_counts(db: Session, org_id: str) -> dict[str, int]:
    from sqlalchemy import func

    rows = db.execute(
        select(EvidenceRecord.collection, func.count())
        .where(EvidenceRecord.org_id == org_id, EvidenceRecord.active.is_(True))
        .group_by(EvidenceRecord.collection)
    ).all()
    return {c: n for c, n in rows}
