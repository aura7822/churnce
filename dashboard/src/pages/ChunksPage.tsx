import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent, type RefObject } from "react";
import { api } from "../services/api";
import { useResource, useServerNow } from "../hooks/useLive";
import { useAuth } from "../hooks/useAuth";
import { useToast } from "../hooks/useToast";
import type { Chunk, Retrieval } from "../types";
import { Badge, Button, Card, Dial, Empty, ErrorNote, PageHead, Segmented, SimBadge, Skeleton, StateBadge } from "../components/ui";
import { IconBooks, IconCheck, IconMail, IconChevrons, IconChunks, IconClock, IconEye, IconFile, IconPause, IconPlus, IconRag, IconRedact, IconSave, IconSearch, IconSpark, IconTrash } from "../components/icons";
import { ago, ms, remainingSeconds, titleCase } from "../services/format";

type Filter = "pending" | "all" | "indexed" | "closed";
type Tier = 0 | 1 | 2 | 3;
const MAX_VISIBLE = 5; // injectable cards shown at once; the rest stay queued behind them
const TIER_LABEL: Record<Tier, string> = { 0: "Flagged", 1: "High", 2: "Medium", 3: "Low" };

/** Priority: flagged chunks need a human first; then chunks about to expire; then running timers; manual/held last. */
function tierOf(c: Chunk, seconds: number | null): Tier {
  if (c.sensitivity_status === "flagged") return 0;
  if (c.review_mode === "auto" && !c.held && seconds !== null && seconds <= 10) return 1;
  if (c.review_mode === "auto" && !c.held) return 2;
  return 3;
}

function MiniCard({ chunk, total, tier, rank, onChanged, reg }: { chunk: Chunk; total: number; tier: Tier; rank: number; onChanged: (opts?: { quiet?: boolean; discarded?: string }) => void; reg: (id: string, el: HTMLElement | null) => void }) {
  const { can } = useAuth();
  const toast = useToast();
  const now = useServerNow(250);
  const [draft, setDraft] = useState(chunk.summary);
  const [busy, setBusy] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const editable = can("chunks:review");
  const dirty = draft !== chunk.summary;
  const seconds = chunk.held ? chunk.seconds_remaining : remainingSeconds(chunk.review_deadline, now);
  const manual = chunk.review_mode === "manual";

  useEffect(() => { setDraft(chunk.summary); }, [chunk.version, chunk.summary]);

  async function act(name: string, fn: () => Promise<unknown>, okMsg: string, discarded?: string) {
    setBusy(name);
    try { await fn(); toast.ok(okMsg); onChanged({ discarded }); } catch (e) { toast.err((e as Error).message); onChanged({ quiet: true }); } finally { setBusy(null); }
  }
  const hold = () => { if (editable && !chunk.held) api.holdChunk(chunk.id).then(() => onChanged({ quiet: true })).catch(() => undefined); };
  const obs = Object.entries(chunk.observations).filter(([, v]) => v !== null && v !== "");

  return (
    <article ref={(el) => reg(chunk.id, el)} className={`mini p${tier} ${open ? "open" : ""}`} aria-label={`Chunk ${chunk.id}, ${TIER_LABEL[tier]} priority`}>
      <div className="mini-head">
        <Dial seconds={manual ? null : seconds} total={total} held={chunk.held} />
        <div style={{ minWidth: 0 }}>
          <div className="rank">#{rank} · {TIER_LABEL[tier].toUpperCase()} · v{chunk.version}</div>
          <h3>{titleCase(chunk.journey_stage)} · {titleCase(chunk.signal)}</h3>
        </div>
      </div>
      <div className="chunk-meta" style={{ margin: 0 }}>
        <Badge icon={<IconRedact />}>{titleCase(chunk.sensitivity_status)}</Badge>
        {chunk.edited && <Badge>Edited</Badge>}
        <SimBadge simulated={chunk.simulated} />
      </div>
      <p className="mini-body">{chunk.summary}</p>

      {open && (
        <div className="stack">
          {chunk.sensitivity_status === "flagged" && <p className="hint"><b>Flagged:</b> never auto-ingested. Edit out the sensitive content, then inject.</p>}
          {obs.length > 0 && <div className="obs">{obs.map(([k, v]) => <div key={k}><b>{String(v)}</b><span>{titleCase(k)}</span></div>)}</div>}
          <label htmlFor={`sum-${chunk.id}`} className="label">Summary (editable)</label>
          <textarea id={`sum-${chunk.id}`} className="input" value={draft} disabled={!editable} onFocus={hold} onChange={(e) => setDraft(e.target.value)} maxLength={600} />
          <ol className="timeline" aria-label="Event sequence">{chunk.events.map((ev, i) => <li key={i}>{ev}</li>)}</ol>
          <Button variant="brutal" icon={<IconSave />} busy={busy === "save"} disabled={!editable || !dirty || !draft.trim()}
            onClick={() => act("save", () => api.editChunk(chunk.id, chunk.version, draft.trim()), "Saved as a new version.")}>Save edit</Button>
        </div>
      )}

      <div className="mini-actions">
        <Button variant="brutal-go" icon={<IconCheck />} busy={busy === "inject"} disabled={!editable || dirty} title={dirty ? "Save your edit first" : "Send to the RAG window now"}
          onClick={() => act("inject", () => api.approveChunk(chunk.id, chunk.version), "Injecting into the RAG window.")}>Inject now</Button>
        <Button variant="brutal" icon={<IconClock />} busy={busy === "extend"} disabled={!editable || manual} title={manual ? "Manual chunks have no timer" : "Add 30 seconds"}
          onClick={() => act("extend", () => api.extendChunk(chunk.id), "Extended by 30 seconds.")}>+30s</Button>
        <Button variant="brutal" icon={<IconEye />} onClick={() => setOpen((v) => !v)} aria-expanded={open}>{open ? "Less" : "Edit"}</Button>
        {!chunk.held && editable && !manual && <Button variant="brutal" icon={<IconPause />} onClick={hold}>Hold</Button>}
        <Button variant="brutal-stop" icon={<IconTrash />} busy={busy === "discard"} disabled={!editable}
          onClick={() => act("discard", () => api.discardChunk(chunk.id), "Discarded. It will never be indexed.", chunk.id)}>Discard</Button>
      </div>
    </article>
  );
}

interface Flight { key: string; label: string; x: number; y: number; dx: number; dy: number; go: boolean }
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
      {r.email_draft && (
        <div className="mail" aria-label="Win-back email draft">
          <h4 className="row" style={{ fontFamily: "var(--font-body)" }}><IconMail /> Win-back email for this issue · {r.email_draft.generated_by}</h4>
          <div className="subject">{r.email_draft.subject}</div>
          <p>{r.email_draft.body}</p>
          <p className="hint" style={{ fontFamily: "var(--font-body)", marginTop: 10 }}>Preview from these findings. Per-customer versions are created once the issue has a verified fix; open the extension settings, sign in and enable email retrieval to edit and send them.</p>
        </div>
      )}
      {r.notes.length > 0 && <p className="hint">{r.notes.join(" · ")}</p>}
    </div>
  );
}

const STEP: Record<string, number> = { APPROVED: 1, VALIDATING: 1, QUEUED_FOR_INGESTION: 1, EMBEDDING: 2, INDEXED: 3, AVAILABLE_FOR_RETRIEVAL: 4 };

function RagWindow({ feed, incoming, intakeRef, catching, arrived, reloadFeed }: { feed: Chunk[]; incoming: number; intakeRef: RefObject<HTMLDivElement>; catching: boolean; arrived: Set<string>; reloadFeed: () => void }) {
  const { can } = useAuth();
  const toast = useToast();
  const list = useResource(api.retrievals, ["retrievals"]);
  const [shown, setShown] = useState<Retrieval | null>(null);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [doc, setDoc] = useState({ collection: "product_knowledge", source_ref: "", title: "", body: "" });

  async function search(e: FormEvent) {
    e.preventDefault();
    if (!q.trim()) return;
    setBusy(true);
    try { setShown(await api.ragSearch(q.trim())); } catch (err) { toast.err((err as Error).message); } finally { setBusy(false); }
  }
  async function addDoc(e: FormEvent) {
    e.preventDefault();
    try {
      const r = await api.addDocument(doc);
      toast.ok(r.unchanged ? "Already indexed, no change." : `Indexed ${r.passages} passage(s).`);
      setDoc({ ...doc, source_ref: "", title: "", body: "" });
      reloadFeed();
    } catch (err) { toast.err((err as Error).message); }
  }

  return (
    <section className="rag-window" aria-label="RAG window">
      <div className="card-head" style={{ marginBottom: 0 }}>
        <div><h3 className="row"><IconRag /> RAG window</h3><p className="card-sub">Chunks fed in real time. What enters here is what retrieval can find.</p></div>
      </div>

      <div ref={intakeRef} className={`rag-intake ${catching ? "catch" : ""}`}>
        <span className="chevrons" aria-hidden="true"><IconChevrons /><IconChevrons /><IconChevrons /></span>
        <b>Intake</b>
        <span className="hint">Expired and injected chunks drop in here, then validate, embed and index.</span>
      </div>

      <div>
        <h4 style={{ marginBottom: 8 }}>Live feed</h4>
        {feed.length === 0 && incoming === 0 ? <p className="hint">Nothing has been fed in yet.</p> : (
          <div className="rag-feed">
            {Array.from({ length: Math.min(incoming, 5) }, (_, i) => (
              <div key={`sk${i}`} className="rag-row skeleton-row" aria-label="Incoming chunk, processing" style={{ animationDelay: `${i * 90}ms` }}>
                <IconChevrons className="arrow-down" />
                <div><span className="skel-line w60" /><span className="skel-line w90" /></div>
                <div className="stage-track"><i /><i /><i /><i /></div>
              </div>
            ))}
            {feed.map((c) => (
              <div key={c.id} className={`rag-row ${arrived.has(c.id) ? "new" : ""}`}>
                <IconFile />
                <div><b>{titleCase(c.journey_stage)} · {titleCase(c.signal)}</b><small>{c.summary.slice(0, 90)}</small></div>
                <div style={{ textAlign: "right" }}>
                  <div className="stage-track" aria-label={titleCase(c.state.toLowerCase())}>{[1, 2, 3, 4].map((n) => <i key={n} className={(STEP[c.state] ?? 0) >= n ? "done" : ""} />)}</div>
                  <small>{titleCase(c.state.toLowerCase())}</small>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <form className="row" onSubmit={search} style={{ flexWrap: "nowrap" }}>
        <input className="input" placeholder="Try a query, e.g. payment timeouts at checkout" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search query" />
        <Button variant="neu" busy={busy} icon={<IconSearch />} type="submit">Retrieve</Button>
      </form>

      {(list.data?.retrievals.length ?? 0) > 0 && (
        <div className="row">
          <span className="hint">Recent:</span>
          {list.data!.retrievals.slice(0, 5).map((r) => (
            <button key={r.id} className="chip" onClick={() => api.retrieval(r.id).then(setShown).catch((e: Error) => toast.err(e.message))}>{r.query.slice(0, 32)} · {r.kept}/{r.candidates}</button>
          ))}
        </div>
      )}

      {shown && (
        <div className="stack">
          <dl className="kv">
            <dt>Query</dt><dd>{shown.query}</dd>
            <dt>When</dt><dd>{ago(shown.created_at)} · {ms(shown.latency_ms)}</dd>
            <dt>Embeddings</dt><dd>{shown.embedding_provider}</dd>
            <dt>Reranking</dt><dd>{shown.rerank_provider}</dd>
          </dl>
          {shown.reasoning && <Reasoned r={shown.reasoning} />}
          <h4 className="row"><IconBooks /> Context sent to the model</h4>
          <pre className="codeblock">{shown.context || "(empty)"}</pre>
          <p className="hint">Retrieved text is passed as untrusted data, never as instructions.</p>
        </div>
      )}

      {can("knowledge:write") && (
        <details>
          <summary className="row"><IconPlus /> Add knowledge</summary>
          <form className="stack" onSubmit={addDoc} style={{ marginTop: 10 }}>
            <select className="input" value={doc.collection} onChange={(e) => setDoc({ ...doc, collection: e.target.value })} aria-label="Collection">
              {["product_knowledge", "engineering", "support", "business_policy", "intervention_memory"].map((c) => <option key={c} value={c}>{titleCase(c)}</option>)}
            </select>
            <input className="input" placeholder="Source reference (e.g. release_000014)" required value={doc.source_ref} onChange={(e) => setDoc({ ...doc, source_ref: e.target.value })} />
            <input className="input" placeholder="Title" required value={doc.title} onChange={(e) => setDoc({ ...doc, title: e.target.value })} />
            <textarea className="input" placeholder="Body" required value={doc.body} onChange={(e) => setDoc({ ...doc, body: e.target.value })} />
            <Button variant="neu" type="submit" icon={<IconBooks />}>Index document</Button>
          </form>
        </details>
      )}
    </section>
  );
}

export function ChunksPage() {
  const now = useServerNow(500);
  const [filter, setFilter] = useState<Filter>("pending");
  const pending = useResource(api.pendingChunks, ["chunks"]);
  const all = useResource(() => api.chunks(undefined, 100), ["chunks"]);
  const cfg = useResource(api.config, ["config"]);
  const total = cfg.data?.review_seconds ?? 30;
  const pend = pending.data?.chunks ?? [];

  const ranked = useMemo(() => pend
    .map((c) => ({ c, tier: tierOf(c, c.held ? c.seconds_remaining : remainingSeconds(c.review_deadline, now)) }))
    .sort((a, b) => a.tier - b.tier || (a.c.review_deadline ?? "9").localeCompare(b.c.review_deadline ?? "9") || a.c.created_at.localeCompare(b.c.created_at)),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [pend, Math.floor(now / 1000)]);

  const rows = (all.data?.chunks ?? []).filter((c) => filter === "indexed" ? ["INDEXED", "AVAILABLE_FOR_RETRIEVAL"].includes(c.state) : filter === "closed" ? ["REJECTED", "DISCARDED"].includes(c.state) : true);
  const feed = (all.data?.chunks ?? []).filter((c) => c.state in STEP).sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, 8);
  const reload = () => { pending.reload(); all.reload(); };

  // ── "Files drop into the RAG window": a visual of a REAL transition. A chunk that leaves the pending list
  //    without the operator discarding it was ingested by the backend (timer expiry or Inject now).
  const els = useRef(new Map<string, HTMLElement>());
  const rects = useRef(new Map<string, { x: number; y: number; w: number; label: string }>());
  const prev = useRef<string[]>([]);
  const discarded = useRef(new Set<string>());
  const intake = useRef<HTMLDivElement>(null);
  const [flights, setFlights] = useState<Flight[]>([]);
  const [catching, setCatching] = useState(false);
  const [arrived, setArrived] = useState<Set<string>>(new Set());
  const reg = useCallback((id: string, el: HTMLElement | null) => { if (el) els.current.set(id, el); else els.current.delete(id); }, []);

  const measure = useCallback(() => {
    for (const { c } of ranked) {
      const el = els.current.get(c.id);
      if (el) { const r = el.getBoundingClientRect(); rects.current.set(c.id, { x: r.left, y: r.top, w: r.width, label: `${titleCase(c.journey_stage)} · ${titleCase(c.signal)}` }); }
    }
  }, [ranked]);
  useLayoutEffect(measure);
  useEffect(() => { const id = setInterval(measure, 400); window.addEventListener("scroll", measure, { passive: true }); return () => { clearInterval(id); window.removeEventListener("scroll", measure); }; }, [measure]);

  useEffect(() => {
    if (!pending.data) return;
    const ids = pend.map((c) => c.id);
    const gone = prev.current.filter((id) => !ids.includes(id) && !discarded.current.has(id));
    prev.current = ids;
    if (gone.length === 0 || filter !== "pending") return;
    const to = intake.current?.getBoundingClientRect();
    if (!to) return;
    const fl: Flight[] = gone.slice(0, 6).flatMap((id, i) => {
      const r = rects.current.get(id);
      return r ? [{ key: `${id}-${Date.now()}`, label: r.label, x: r.x + 12, y: r.y + 12, dx: to.left + to.width / 2 - (r.x + 12) - 90 + (i - 1) * 14, dy: to.top + to.height / 2 - (r.y + 12), go: false }] : [];
    });
    if (fl.length === 0) return;
    setFlights((f) => [...f, ...fl]);
    requestAnimationFrame(() => requestAnimationFrame(() => setFlights((f) => f.map((x) => (fl.some((n) => n.key === x.key) ? { ...x, go: true } : x)))));
    const t = setTimeout(() => {
      setFlights((f) => f.filter((x) => !fl.some((n) => n.key === x.key)));
      setCatching(true); setTimeout(() => setCatching(false), 600);
      setArrived((a) => new Set([...a, ...gone]));
      setTimeout(() => setArrived((a) => { const n = new Set(a); gone.forEach((g) => n.delete(g)); return n; }), 6000);
      all.reload();
    }, 950);
    return () => clearTimeout(t);
  }, [pending.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const changed = (o?: { quiet?: boolean; discarded?: string }) => { if (o?.discarded) discarded.current.add(o.discarded); reload(); };

  return (
    <div className="page">
      <PageHead eyebrow="Review gate and retrieval" title="Chunk lab & RAG" />
      <Segmented<Filter> value={filter} onChange={setFilter} options={[
        { id: "pending", label: "Pending review", count: pend.length },
        { id: "all", label: "All chunks" }, { id: "indexed", label: "Indexed" }, { id: "closed", label: "Discarded / rejected" },
      ]} />
      {(pending.error || all.error) && <ErrorNote message={(pending.error || all.error)!} retry={reload} />}

      {filter === "pending" ? (
        !pending.data ? <Skeleton rows={2} h={160} /> : ranked.length === 0 ? (
          <Card><Empty icon={<IconChunks />} title="Nothing waiting for review">New chunks appear here the moment the backend creates them.</Empty></Card>
        ) : (
          <>
            <div className="priority-legend" aria-label="Priority legend">
              {([0, 1, 2, 3] as Tier[]).map((t) => <span key={t}><i style={{ background: t === 0 ? "var(--wine)" : t === 1 ? "var(--red)" : t === 2 ? "var(--amber)" : "var(--sage-lo)" }} />{TIER_LABEL[t]}</span>)}
              <span>· sorted by priority, then by time left</span>
            </div>
            <div className="chunk-grid">{ranked.slice(0, MAX_VISIBLE).map(({ c, tier }, i) => <MiniCard key={c.id} chunk={c} total={total} tier={tier} rank={i + 1} onChanged={changed} reg={reg} />)}</div>
            {ranked.length > MAX_VISIBLE && <p className="hint">+{ranked.length - MAX_VISIBLE} more queued behind these five. They move up as cards are injected or discarded.</p>}
          </>
        )
      ) : (
        <Card title="Chunks" icon={<IconChunks />}>
          {!all.data ? <Skeleton rows={5} h={44} /> : rows.length === 0 ? <Empty icon={<IconChunks />} title="No chunks in this view" /> : (
            <div className="table-wrap">
              <table className="t">
                <thead><tr><th>Chunk</th><th>Summary</th><th>Journey</th><th>State</th><th>Privacy</th><th className="num">Ver.</th></tr></thead>
                <tbody>
                  {rows.map((c) => (
                    <tr key={c.id}>
                      <td className="mono">{c.id.slice(-8)}</td>
                      <td>{c.summary} <SimBadge simulated={c.simulated} /></td>
                      <td>{titleCase(c.journey_stage)}</td>
                      <td><StateBadge state={c.state} />{c.validation_errors.length > 0 && <div className="hint">{c.validation_errors.join("; ")}</div>}</td>
                      <td>{titleCase(c.sensitivity_status)}</td>
                      <td className="num">{c.version}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      <RagWindow feed={feed} incoming={flights.length + arrived.size + feed.filter((c) => (STEP[c.state] ?? 0) < 4 && !arrived.has(c.id)).length} intakeRef={intake} catching={catching} arrived={arrived} reloadFeed={all.reload} />

      {flights.map((f) => (
        <div key={f.key} className="flight" aria-hidden="true"
          style={{ left: f.x, top: f.y, transform: f.go ? `translate(${f.dx}px, ${f.dy}px) scale(.55)` : "none", opacity: f.go ? 0.15 : 1 }}>
          <IconFile />{f.label}
        </div>
      ))}
    </div>
  );
}
