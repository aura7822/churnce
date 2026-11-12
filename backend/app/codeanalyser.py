"""Codebase analyser (basic): reads a website's source, indexes it, and answers three questions about a reported bug:
   1. Where does it most likely originate?  2. If that code changes, how far does the effect reach?  3. What else looks fragile nearby?
Pure functions over {path: text}: no database, no network, so it is deterministic and unit-tested. Static analysis only: it never runs the code."""
from __future__ import annotations

import io
import posixpath
import re
import zipfile
from collections import Counter, defaultdict, deque
from typing import Any

MAX_ZIP_BYTES = 25 * 1024 * 1024
MAX_FILES = 4000
MAX_FILE_BYTES = 300 * 1024
MAX_TOTAL_BYTES = 40 * 1024 * 1024  # uncompressed: zip-bomb guard
SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".next", ".nuxt", "vendor", "venv", ".venv", "__pycache__", "coverage", ".cache", "target", "out", ".idea", ".vscode", "bower_components"}
JS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte")
PY = (".py",)
OTHER = (".html", ".htm", ".php", ".rb", ".java", ".kt", ".go", ".cs", ".css", ".scss", ".json")
TEXT_EXT = JS + PY + OTHER
STOP = set("the a an and or of to in on at for with from this that is are was were be been it its as by not no yes click clicked button page user users error issue problem when after before again repeated repeatedly times time same site website customer session event events signal incident observed fact facts unable cannot cant unknown unclassified".split())


class UnsafeArchive(ValueError):
    pass


def read_zip(data: bytes) -> dict[str, str]:
    """Reads source files straight from the archive (nothing is extracted to disk). Raises UnsafeArchive for oversize or malformed input."""
    if len(data) > MAX_ZIP_BYTES:
        raise UnsafeArchive(f"The archive is larger than {MAX_ZIP_BYTES // (1024 * 1024)} MB.")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UnsafeArchive("That file is not a valid zip archive.") from exc
    infos = [i for i in z.infolist() if not i.is_dir()]
    if len(infos) > MAX_FILES * 5 or sum(i.file_size for i in infos) > MAX_TOTAL_BYTES * 4:
        raise UnsafeArchive("The archive expands to too much data.")
    names = [i.filename.replace("\\", "/") for i in infos]
    # GitHub zipballs wrap everything in one top folder: strip it so paths read like the repository.
    top = {n.split("/", 1)[0] for n in names if "/" in n}
    strip = top.pop() + "/" if len(top) == 1 and all("/" in n for n in names) else ""
    files: dict[str, str] = {}
    total = 0
    for i, raw in zip(infos, names):
        path = raw[len(strip):] if strip and raw.startswith(strip) else raw
        parts = [x for x in path.split("/") if x]
        if not parts or ".." in parts or path.startswith("/") or any(x in SKIP_DIRS for x in parts[:-1]):
            continue
        if not path.lower().endswith(TEXT_EXT) or i.file_size > MAX_FILE_BYTES or path.endswith((".min.js", ".min.css", "package-lock.json")):
            continue
        try:
            text = z.read(i).decode("utf-8", errors="strict")
        except (UnicodeDecodeError, RuntimeError, zipfile.BadZipFile):
            continue
        total += len(text)
        if total > MAX_TOTAL_BYTES or len(files) >= MAX_FILES:
            break
        files[path] = text
    if not files:
        raise UnsafeArchive("No readable source files were found (JavaScript, TypeScript, Python, PHP, HTML and similar).")
    return files


# ───────────────────────── index ─────────────────────────
_JS_IMPORT = re.compile(r"""(?:import\s+(?:[^'"]+?\s+from\s+)?|export\s+[^'"]*?\s+from\s+|require\(\s*|import\(\s*)['"]([^'"]+)['"]""")
_PY_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import\s+([\w, *]+)|import\s+([\w., ]+))", re.M)
_SYMBOL = re.compile(r"(?:function\s+([A-Za-z_$][\w$]*)|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>|class\s+([A-Za-z_$][\w$]*)|def\s+([A-Za-z_]\w*)|class\s+([A-Za-z_]\w*)\s*[(:])")
_HANDLER = re.compile(r"""(?:\bon[A-Z]\w*\s*=\s*\{|@click|v-on:click|addEventListener\(\s*['"](?:click|submit|dblclick)['"]|\.on\(\s*['"]click['"]|\bonclick\s*=)""")
_API = re.compile(r"""(?:fetch\(\s*|axios\.\w+\(\s*|\$\.(?:ajax|get|post)\(\s*|requests\.\w+\(\s*|httpx\.\w+\(\s*)[`'"]([^`'"]+)""")


def _lang(path: str) -> str:
    return "js" if path.endswith(JS) else "py" if path.endswith(PY) else path.rsplit(".", 1)[-1] if "." in path else "txt"


def _resolve_js(src: str, spec: str, known: set[str]) -> str | None:
    if spec.startswith("@/"):
        base = "src/" + spec[2:]
    elif spec.startswith("."):
        base = posixpath.normpath(posixpath.join(posixpath.dirname(src), spec))
    else:
        return None  # a package, not part of this codebase
    for cand in [base] + [base + e for e in (".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte", ".mjs")] + [f"{base}/index{e}" for e in (".ts", ".tsx", ".js", ".jsx")]:
        if cand in known:
            return cand
    return None


def _resolve_py(src: str, mod: str, known: set[str]) -> str | None:
    if mod.startswith("."):
        dots = len(mod) - len(mod.lstrip("."))
        base = posixpath.dirname(src)
        for _ in range(dots - 1):
            base = posixpath.dirname(base)
        rel = mod.lstrip(".").replace(".", "/")
        stem = posixpath.join(base, rel) if rel else base
    else:
        stem = mod.replace(".", "/")
    for cand in (f"{stem}.py", f"{stem}/__init__.py"):
        if cand in known:
            return cand
    if not mod.startswith("."):
        tail = f"/{stem}.py"
        for k in known:
            if k.endswith(tail):
                return k
    return None


def build_index(files: dict[str, str]) -> dict[str, Any]:
    known = set(files)
    nodes: dict[str, dict[str, Any]] = {}
    rev: dict[str, set[str]] = defaultdict(set)
    for path, text in files.items():
        lang = _lang(path)
        deps: set[str] = set()
        if lang == "js":
            for spec in _JS_IMPORT.findall(text):
                r = _resolve_js(path, spec, known)
                if r and r != path:
                    deps.add(r)
        elif lang == "py":
            for frm, names, plain in _PY_IMPORT.findall(text):
                for mod in ([frm] if frm else [m.strip().split(" as ")[0] for m in plain.split(",")]):
                    r = _resolve_py(path, mod, known) if mod else None
                    if r and r != path:
                        deps.add(r)
                    if frm and names:  # `from pkg import module`
                        for n in names.split(","):
                            sub = _resolve_py(path, f"{frm}.{n.strip()}", known)
                            if sub and sub != path:
                                deps.add(sub)
        symbols = []
        for m in _SYMBOL.finditer(text):
            name = next((g for g in m.groups() if g), None)
            if name and name not in symbols:
                symbols.append(name)
        nodes[path] = {"path": path, "lang": lang, "lines": text.count("\n") + 1, "deps": sorted(deps), "symbols": symbols[:40], "handlers": len(_HANDLER.findall(text)), "apis": sorted(set(_API.findall(text)))[:12]}
        for d in deps:
            rev[d].add(path)
    for path, n in nodes.items():
        n["dependents"] = sorted(rev.get(path, ()))
    return nodes


# ───────────────────────── issues ─────────────────────────
def scan_issues(files: dict[str, str], limit: int = 120) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(path: str, line: int, rule: str, sev: str, msg: str) -> None:
        if len(out) < limit:
            out.append({"path": path, "line": line, "rule": rule, "severity": sev, "message": msg})

    for path, text in files.items():
        lang = _lang(path)
        lines = text.split("\n")
        guard = bool(re.search(r"disabled\s*=|isSubmitting|isLoading|loading\b|pending\b|debounce|throttle|\bonce\b|inFlight|busy", text))
        for n, ln in enumerate(lines, 1):
            if lang == "js":
                if _HANDLER.search(ln) and not guard:
                    add(path, n, "click-without-guard", "high", "Click or submit handler with no in-flight guard (disabled, loading, debounce): repeated clicks will repeat the action.")
                if re.search(r"fetch\(", ln) and not re.search(r"catch|try|await|\.then", " ".join(lines[n - 1:n + 4])):
                    add(path, n, "unhandled-request", "medium", "Request without error handling: a failure leaves the user with no feedback.")
                if re.search(r"catch\s*(\([^)]*\))?\s*\{\s*\}", ln):
                    add(path, n, "swallowed-error", "medium", "Empty catch block hides failures.")
                if re.search(r"\.innerHTML\s*=", ln):
                    add(path, n, "inner-html", "medium", "innerHTML assignment: injection and re-render risk.")
                if "setInterval(" in ln and "clearInterval" not in text:
                    add(path, n, "interval-leak", "low", "Interval is never cleared.")
            elif lang == "py":
                if re.match(r"\s*except\s*:", ln) or re.match(r"\s*except\s+Exception\s*:\s*(pass)?\s*$", ln):
                    add(path, n, "broad-except", "medium", "Broad except hides the real failure.")
            if re.search(r"\b(TODO|FIXME|HACK|XXX)\b", ln):
                add(path, n, "todo", "low", ln.strip()[:100])
    return out


# ───────────────────────── locating a bug ─────────────────────────
def tokens_of(text: str) -> list[str]:
    parts: list[str] = []
    for w in re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}", text):
        for sub in re.split(r"[_\-]", re.sub(r"([a-z])([A-Z])", r"\1 \2", w)):
            for s in sub.split():
                s = s.lower()
                if len(s) >= 3 and s not in STOP:
                    parts.append(s)
    return parts


def signals_from_bug(bug: dict[str, Any]) -> dict[str, Any]:
    """bug: {title, signal, journey_stage, facts[], hypotheses[], routes[], elements[], event_types[], text}"""
    blob = " ".join([bug.get("title", ""), bug.get("text", ""), *map(str, bug.get("facts", [])), *map(str, bug.get("hypotheses", [])), *map(str, bug.get("elements", [])), *map(str, bug.get("routes", []))])
    quoted = [q.strip() for q in re.findall(r"[\"'`“”‘’]([^\"'`“”‘’]{3,60})[\"'`“”‘’]", blob)]
    route_words = [w for r in bug.get("routes", []) for w in tokens_of(r.replace("/", " "))]
    toks = Counter(tokens_of(blob))
    for w in route_words:
        toks[w] += 3
    kind = "click" if re.search(r"rage|repeat|double|multiple click|dead click|click", " ".join([bug.get("signal", ""), blob]).lower()) else "error" if re.search(r"error|fail|timeout|exception|500|crash|declin", blob.lower()) else "generic"
    return {"tokens": [t for t, _ in toks.most_common(24)], "weights": dict(toks), "phrases": quoted[:8], "routes": bug.get("routes", [])[:6], "kind": kind}


def locate(files: dict[str, str], index: dict[str, Any], sig: dict[str, Any], top: int = 5) -> list[dict[str, Any]]:
    scored: list[tuple[float, str, list[dict[str, Any]], list[str]]] = []
    for path, text in files.items():
        low_path, low = path.lower(), text.lower()
        score, why, hits = 0.0, [], []
        for t in sig["tokens"]:
            w = min(3, sig["weights"].get(t, 1))
            if t in low_path:
                score += 5 * w
                why.append(f"path contains “{t}”")
            c = low.count(t)
            if c:
                score += min(c, 6) * w * 0.6
        for ph in sig["phrases"]:
            if ph.lower() in low:
                score += 9
                why.append(f"contains “{ph}”")
        for r in sig["routes"]:
            seg = r.strip("/").split("/")[0].lower()
            if seg and (seg in low_path or f"'/{seg}" in low or f'"/{seg}' in low):
                score += 6
                why.append(f"handles route /{seg}")
        node = index[path]
        if sig["kind"] == "click" and node["handlers"]:
            score += 4 + min(node["handlers"], 4)
            why.append(f"{node['handlers']} click or submit handler(s)")
        if sig["kind"] == "error" and (node["apis"] or "catch" in low):
            score += 3
            why.append("makes requests / handles errors")
        if score <= 0:
            continue
        for n, ln in enumerate(text.split("\n"), 1):
            l2 = ln.lower()
            if any(t in l2 for t in sig["tokens"][:12]) or any(p.lower() in l2 for p in sig["phrases"]):
                hits.append({"line": n, "text": ln.strip()[:160]})
                if len(hits) >= 4:
                    break
        scored.append((score, path, hits, list(dict.fromkeys(why))[:4]))
    scored.sort(key=lambda x: -x[0])
    best = scored[0][0] if scored else 1.0
    return [{"path": p, "confidence": round(100 * s / best), "score": round(s, 1), "reasons": why, "matches": hits} for s, p, hits, why in scored[:top]]


# ───────────────────────── blast radius ─────────────────────────
def blast_radius(index: dict[str, Any], path: str, max_depth: int = 4) -> dict[str, Any]:
    seen = {path: 0}
    q: deque[str] = deque([path])
    while q:
        cur = q.popleft()
        if seen[cur] >= max_depth:
            continue
        for d in index[cur]["dependents"]:
            if d not in seen:
                seen[d] = seen[cur] + 1
                q.append(d)
    layers: dict[int, list[str]] = defaultdict(list)
    for p, d in seen.items():
        if p != path:
            layers[d].append(p)
    affected = [p for p in seen if p != path]
    pct = round(100 * len(affected) / max(1, len(index)), 1)
    entries = [p for p in affected if re.search(r"(^|/)(pages?|routes?|views?|screens?|app|templates?)/", p) or not index[p]["dependents"]]
    tests = [p for p in affected if re.search(r"(^|/)(tests?|__tests__|spec)/|\.(test|spec)\.", p)]
    risk = "high" if pct >= 15 or len(affected) >= 12 else "medium" if pct >= 5 or len(affected) >= 4 else "low"
    return {"path": path, "affected": len(affected), "percent_of_codebase": pct, "risk": risk, "layers": [{"depth": d, "files": sorted(f)[:15], "count": len(f)} for d, f in sorted(layers.items())],
            "entry_points": sorted(entries)[:10], "tests": sorted(tests)[:10], "depends_on": index[path]["deps"][:12]}


def analyse(files: dict[str, str], bug: dict[str, Any], index: dict[str, Any] | None = None) -> dict[str, Any]:
    index = index or build_index(files)
    sig = signals_from_bug(bug)
    cands = locate(files, index, sig)
    for c in cands:
        c["blast"] = blast_radius(index, c["path"])
    issues = scan_issues(files)
    near = {c["path"] for c in cands[:3]}
    related = [i for i in issues if i["path"] in near and i["severity"] != "low"][:12]
    what_if: list[dict[str, Any]] = []
    if cands:
        top = cands[0]
        b = top["blast"]
        what_if.append({"scenario": f"Change {top['path']}", "effect": f"Reaches {b['affected']} file(s), {b['percent_of_codebase']}% of the codebase ({b['risk']} risk)" + (f"; entry points touched: {', '.join(b['entry_points'][:3])}" if b["entry_points"] else ""),
                        "advice": "Add or run the tests that import it before shipping." if b["tests"] else "No test imports this file: add a regression test for the reported behaviour first."})
        narrow = [c for c in cands[1:] if c["confidence"] >= 55 and c["blast"]["affected"] < b["affected"]]
        if narrow and b["affected"] >= 4:
            n = min(narrow, key=lambda c: c["blast"]["affected"])
            what_if.append({"scenario": f"Fix in {n['path']} instead", "effect": f"Narrower: reaches {n['blast']['affected']} file(s) ({n['blast']['risk']} risk) with {n['confidence']}% confidence it is involved.", "advice": "Prefer this when the top candidate is a shared module."})
        if sig["kind"] == "click":
            what_if.append({"scenario": "Guard the action against repeat clicks", "effect": "Disable the control while the request is in flight, or debounce it. Local change, no new dependents.", "advice": "Then confirm the server also ignores duplicate submissions (idempotency key)."})
        if sig["kind"] == "error":
            what_if.append({"scenario": "Handle and report the failure", "effect": "Catch the failed request, show a recoverable message and log the reason so the dashboard can group it.", "advice": "Keep the retry behind a guard so it cannot loop."})
    langs = Counter(n["lang"] for n in index.values())
    return {"signals": {"kind": sig["kind"], "tokens": sig["tokens"][:12], "phrases": sig["phrases"], "routes": sig["routes"]}, "candidates": cands, "what_if": what_if, "related_issues": related,
            "stats": {"files": len(index), "lines": sum(n["lines"] for n in index.values()), "languages": dict(langs.most_common(6)), "issues": len(issues), "high_issues": sum(1 for i in issues if i["severity"] == "high")}}
