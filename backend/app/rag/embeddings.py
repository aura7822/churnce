"""Embedding service adapters. Swap providers via EMBEDDING_PROVIDER without touching callers."""

from __future__ import annotations

import hashlib
import logging
import math
import time
import re
from typing import Protocol

import httpx

from ..config import get_settings

settings = get_settings()
log = logging.getLogger("churnce.embeddings")

_TOKEN = re.compile(r"[a-z0-9]+")

# Light normalization so "payments", "paying" and "payment" land on one feature.
_SYNONYMS = {
    "pay": "payment",
    "paying": "payment",
    "payments": "payment",
    "paid": "payment",
    "purchase": "checkout",
    "purchases": "checkout",
    "buy": "checkout",
    "cart": "checkout",
    "timeout": "timeout",
    "timeouts": "timeout",
    "timed": "timeout",
    "slow": "latency",
    "slower": "latency",
    "delay": "latency",
    "delays": "latency",
    "delayed": "latency",
    "errors": "error",
    "failed": "error",
    "failure": "error",
    "failures": "error",
    "failing": "error",
    "fails": "error",
    "abandoned": "abandon",
    "abandonment": "abandon",
    "abandoning": "abandon",
    "signup": "register",
    "registration": "register",
    "onboarding": "onboard",
    "search": "search",
    "searches": "search",
    "searching": "search",
}
_STOP = {"the", "a", "an", "of", "to", "and", "in", "on", "for", "with", "was", "were", "is", "are", "at", "by", "or", "it", "this", "that"}


def tokenize(text: str) -> list[str]:
    out = []
    for tok in _TOKEN.findall(text.lower()):
        if tok in _STOP:
            continue
        tok = _SYNONYMS.get(tok, tok)
        if len(tok) > 4 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        out.append(tok)
    return out


class Embedder(Protocol):
    name: str
    dim: int

    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class LocalHashEmbedder:
    """Deterministic signed feature-hashing embedder over unigrams and bigrams.

    No network, no key. Lexical rather than truly semantic, which is why NVIDIA embeddings
    are the intended production provider. It keeps the whole pipeline runnable offline.
    """

    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.name = f"local-hash-{dim}"

    def _vec(self, text: str) -> list[float]:
        toks = tokenize(text)
        feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
        v = [0.0] * self.dim
        for f in feats:
            h = hashlib.blake2b(f.encode(), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "big") % self.dim
            sign = 1.0 if h[4] & 1 else -1.0
            weight = 1.0 if "_" not in f else 0.7
            v[idx] += sign * weight
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def slice_and_normalise(vec: list[float], dim: int) -> list[float]:
    """Nemotron-3-Embed-1B returns 2048 floats; the model card allows keeping the first 1024 or 512 and
    re-normalising to unit length before similarity scoring (Matryoshka-style truncation)."""
    v = vec[:dim]
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class NvidiaEmbedder:
    """NVIDIA Nemotron-3-Embed-1B through the OpenAI-compatible /embeddings route.

    · Output is 2048-d; EMBEDDING_DIM may be 2048, 1024 or 512 (sliced and re-normalised).
    · `input_type` ("query" / "passage") and `truncate` are sent first; if the endpoint rejects them
      (HTTP 400/422) the call is repeated without them and that choice is remembered for the process.
    · 429 and 5xx responses are retried with exponential back-off.
    The stored model name includes the dimension, so vectors of different sizes are never compared.
    """

    NATIVE_DIM = 2048

    def __init__(self) -> None:
        self.model = settings.nvidia_embed_model
        self.dim = settings.embedding_dim
        self.name = f"{self.model}@{self.dim}"
        self._url = settings.nvidia_base_url.rstrip("/") + "/embeddings"
        self._extras = settings.nvidia_embed_send_input_type
        if self.dim > self.NATIVE_DIM:
            raise RuntimeError(f"EMBEDDING_DIM {self.dim} exceeds the model's native {self.NATIVE_DIM}")

    def _post(self, client: httpx.Client, batch: list[str], input_type: str) -> httpx.Response:
        body: dict = {"model": self.model, "input": batch, "encoding_format": "float"}
        if self._extras:
            body.update({"input_type": input_type, "truncate": "END"})
        for attempt in range(settings.llm_max_retries + 1):
            r = client.post(self._url, headers={"Authorization": f"Bearer {settings.nvidia_api_key}", "Accept": "application/json"}, json=body)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < settings.llm_max_retries:
                time.sleep(min(2 ** attempt, 6))
                continue
            return r
        return r  # pragma: no cover

    def _call(self, texts: list[str], input_type: str) -> list[list[float]]:
        if not settings.nvidia_api_key:
            raise RuntimeError("NVIDIA_API_KEY is not configured")
        out: list[list[float]] = []
        with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
            for i in range(0, len(texts), 32):
                batch = texts[i : i + 32]
                r = self._post(client, batch, input_type)
                if r.status_code in (400, 422) and self._extras:
                    log.warning("NVIDIA embeddings rejected input_type/truncate (%s); retrying without them", r.text[:160])
                    self._extras = False
                    r = self._post(client, batch, input_type)
                if r.status_code >= 400:
                    raise RuntimeError(f"NVIDIA embeddings HTTP {r.status_code} for model '{self.model}': {r.text[:400]}")
                data = sorted(r.json()["data"], key=lambda d: d.get("index", 0))
                out.extend(d["embedding"] for d in data)
        if out and len(out[0]) < self.dim:
            raise RuntimeError(f"Model returned {len(out[0])} dimensions, fewer than EMBEDDING_DIM {self.dim}")
        if out and len(out[0]) != self.dim:
            out = [slice_and_normalise(v, self.dim) for v in out]
        return out

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._call(texts, "passage")

    def embed_query(self, text: str) -> list[float]:
        return self._call([text], "query")[0]


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = NvidiaEmbedder() if settings.embedding_provider == "nvidia" else LocalHashEmbedder(settings.embedding_dim)
    return _embedder


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)
