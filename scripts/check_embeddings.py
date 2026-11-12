"""Probe the configured NVIDIA embedding model and print exactly what the API returns.

Usage (from backend/ with the venv active):  python ../scripts/check_embeddings.py
Reads NVIDIA_API_KEY, NVIDIA_BASE_URL, NVIDIA_EMBED_MODEL, EMBEDDING_DIM from backend/.env.
"""
import json
import os
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app.config import get_settings  # noqa: E402

s = get_settings()
url = s.nvidia_base_url.rstrip("/") + "/embeddings"
print(f"POST {url}\nmodel={s.nvidia_embed_model}  configured EMBEDDING_DIM={s.embedding_dim}  key set={bool(s.nvidia_api_key)}")
for body_extra in ({"input_type": "query", "truncate": "END"}, {}):
    body = {"model": s.nvidia_embed_model, "input": ["payment timeouts at checkout"], "encoding_format": "float", **body_extra}
    r = httpx.post(url, headers={"Authorization": f"Bearer {s.nvidia_api_key}"}, json=body, timeout=45)
    print(f"\nextra params {list(body_extra) or 'none'} -> HTTP {r.status_code}")
    if r.status_code == 200:
        dim = len(r.json()["data"][0]["embedding"])
        print(f"returned dimension: {dim}", "OK" if dim >= s.embedding_dim else "TOO SMALL for EMBEDDING_DIM")
        break
    print(r.text[:600])
