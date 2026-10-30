# Patch notes: files you have likely customised

Drop-in files (copy over): `backend/app/rag/embeddings.py`, `backend/app/llm/schemas.py`, `backend/app/llm/service.py`, `backend/tests/test_rag_reasoning.py`, `scripts/check_embeddings.py`.
If you changed `llm/service.py` or `llm/schemas.py` yourself, diff before overwriting.

## 1. backend/app/config.py (4 small edits)
```python
nvidia_embed_model: str = "nvidia/nemotron-3-embed-1b"      # confirm exact id on build.nvidia.com
nvidia_embed_send_input_type: bool = True
gemma_model: str = "gemma-4-26b-a4b-it"                     # or gemma-4-31b-it
gemma_thinking_level: str = "minimal"                       # minimal | high
llm_max_retries: int = 2
```
and in `embedding_model_id` the nvidia branch returns `f"{self.nvidia_embed_model}@{self.embedding_dim}"`.

## 2. backend/app/api.py (3 edits)
```python
from .llm import service as llm_service            # next to the other llm import
```
In `ser_retrieval`, add to the returned dict: `"reasoning": (r.filters or {}).get("reasoning"),`
In `rag_search`, between `retrieve(...)` and `db.commit()`:
```python
reasoning = llm_service.reason_over_retrieval(body.query, rec)
rec.filters = {**(rec.filters or {}), "reasoning": reasoning}
```

## 3. dashboard/src/types/index.ts
Inside `interface Retrieval` add `reasoning?: Reasoning | null;` and add:
```ts
export interface Reasoning {
  provider: string; notes: string[]; latency_ms: number;
  answer: {
    lifecycle_stage: string; summary: string; recurring_patterns: string[];
    causes: { description: string; kind: "symptom" | "root_cause"; confidence: number; evidence_ids: string[] }[];
    feature_requests: string[]; ux_problems: string[];
    recommendations: { action: string; rationale: string; priority: string; evidence_ids: string[] }[];
    marketing_draft_notes: string[]; unresolved_questions: string[]; evidence_ids: string[]; confidence: number;
  };
}
```

## 4. dashboard/src/pages/ChunksPage.tsx
Add `IconSpark` to the icons import, paste above `const STEP`:
```tsx
function List({ title, items }: { title: string; items: string[] }) {
  return items.length ? <div><h4>{title}</h4><ul className="facts">{items.map((x, i) => <li key={i}>{x}</li>)}</ul></div> : null;
}

function Reasoned({ r }: { r: NonNullable<Retrieval["reasoning"]> }) {
  const a = r.answer;
  return (
    <div className="stack" aria-label="Model reasoning">
      <h4 className="row"><IconSpark /> Reasoning · {r.provider} · {ms(r.latency_ms)}</h4>
      <div className="row"><Badge tone="blue">Stage: {titleCase(a.lifecycle_stage)}</Badge><Badge tone="teal">Confidence {Math.round(a.confidence * 100)}%</Badge></div>
      <p>{a.summary}</p>
      <List title="Recurring patterns" items={a.recurring_patterns} />
      {a.causes.length > 0 && <div><h4>Symptoms and likely causes</h4><ul className="facts">{a.causes.map((c, i) => <li key={i}><b>{c.kind === "symptom" ? "Symptom" : "Root cause"}</b> ({Math.round(c.confidence * 100)}%): {c.description} {c.evidence_ids.map((e) => <span key={e} className="chip">{e}</span>)}</li>)}</ul></div>}
      <List title="Feature requests" items={a.feature_requests} />
      <List title="UX problems" items={a.ux_problems} />
      {a.recommendations.length > 0 && <div><h4>Recommendations</h4><ul className="facts">{a.recommendations.map((x, i) => <li key={i}><b>{titleCase(x.action)}</b> · {titleCase(x.priority)}: {x.rationale}</li>)}</ul></div>}
      <List title="Lifecycle marketing notes" items={a.marketing_draft_notes} />
      <List title="Still unknown" items={a.unresolved_questions} />
      {r.notes.length > 0 && <p className="hint">{r.notes.join(" · ")}</p>}
    </div>
  );
}
```
and in the RagWindow result block, just above `<h4 className="row"><IconBooks /> Context sent to the model</h4>` add:
```tsx
{shown.reasoning && <Reasoned r={shown.reasoning} />}
```

## 5. .env (paste-ready)
```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=<Google AI Studio key>
GEMMA_MODEL=gemma-4-26b-a4b-it
GEMMA_THINKING_LEVEL=minimal
EMBEDDING_PROVIDER=nvidia
NVIDIA_API_KEY==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
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_EMBED_MODEL=nvidia/nemotron-3-embed-1b
NVIDIA_EMBED_SEND_INPUT_TYPE=true
EMBEDDING_DIM=1024
```
Because the stored model name now includes the size (`...@1024`), passages embedded earlier are not searched: re-add knowledge documents, or delete the old evidence rows, after switching.
