import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { api } from "../services/api";
import { useAuth } from "../hooks/useAuth";
import { useToast } from "../hooks/useToast";
import { useResource } from "../hooks/useLive";
import { Badge, Banner, Button, Card, Empty, ErrorNote, PageHead, Skeleton } from "../components/ui";
import { IconCode, IconGithub, IconTarget, IconUpload, IconZip, IconWarn } from "../components/icons";
import { Upsell } from "./finance/Upsell";
import { ago, num } from "../services/format";
import type { Blast, CodeAnalysis, CodeProject } from "../types";

const RISK = { low: "green", medium: "amber", high: "red" } as const;
const SEV = { high: "red", medium: "amber", low: "blue", critical: "red" } as const;
const incidentFromHash = () => new URLSearchParams(location.hash.split("?")[1] ?? "").get("incident");

/** Where the effect of changing one file travels: the file on the left, then everything that depends on it, layer by layer. */
function BlastMap({ b }: { b: Blast }) {
  const cols = [{ title: "Change here", files: [b.path], count: 1 }, ...b.layers.map((l) => ({ title: l.depth === 1 ? "Used directly by" : `${l.depth} steps away`, files: l.files.slice(0, 4), count: l.count }))];
  const W = 190, G = 46, H = 22, top = 30;
  const rows = Math.max(...cols.map((c) => Math.min(c.files.length, 4) + (c.count > 4 ? 1 : 0)));
  const height = top + rows * (H + 8) + 12;
  const width = cols.length * W + (cols.length - 1) * G;
  const short = (p: string) => (p.length > 26 ? `…${p.slice(-25)}` : p);
  return (
    <svg className="blast-map" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${b.affected} files are affected by a change to ${b.path}`}>
      {cols.map((c, ci) => {
        const x = ci * (W + G);
        return (
          <g key={ci}>
            <text x={x} y={16} className="bm-title">{c.title}</text>
            {c.files.map((f, ri) => <g key={f}><rect x={x} y={top + ri * (H + 8)} width={W} height={H} className={ci === 0 ? "bm-box origin" : "bm-box"} /><text x={x + 8} y={top + ri * (H + 8) + 15} className="bm-text">{short(f)}</text></g>)}
            {c.count > 4 && <text x={x + 4} y={top + 4 * (H + 8) + 15} className="bm-more">+{c.count - 4} more</text>}
            {ci < cols.length - 1 && <path d={`M${x + W} ${top + H / 2} H${x + W + G - 6} m-6 -5 l6 5 l-6 5`} className="bm-arrow" />}
          </g>
        );
      })}
    </svg>
  );
}

function Result({ r }: { r: CodeAnalysis }) {
  const [open, setOpen] = useState(0);
  const cand = r.candidates[open];
  return (
    <div className="stack">
      <Card className="tile">
        <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 10 }}>
          <div><span className="eyebrow"><IconTarget /> Bug under analysis</span><h3 style={{ marginTop: 4 }}>{r.bug.title}</h3></div>
          <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>{r.bug.severity && <Badge tone={SEV[r.bug.severity as keyof typeof SEV] ?? "blue"}>{r.bug.severity}</Badge>}<Badge>{r.signals.kind} signal</Badge><Badge>{num(r.stats.files)} files · {num(r.stats.lines)} lines</Badge></div>
        </div>
        {r.signals.tokens.length > 0 && <p className="hint" style={{ marginTop: 8 }}>Matched on: {r.signals.tokens.slice(0, 8).join(", ")}{r.signals.routes.length ? ` · routes ${r.signals.routes.join(", ")}` : ""}</p>}
      </Card>

      {r.candidates.length === 0 ? <Empty icon={<IconCode />} title="No likely origin found">Nothing in this codebase matches the reported signals. Add detail to the description, or connect the right project.</Empty> : (
        <div className="fin-cols">
          <Card>
            <h3>Where it likely originates</h3>
            <ul className="cand-list">
              {r.candidates.map((c, i) => (
                <li key={c.path}><button type="button" className={`cand ${i === open ? "on" : ""}`} onClick={() => setOpen(i)} aria-pressed={i === open}>
                  <span className="mono cand-path">{c.path}</span>
                  <span className="cand-meter" aria-label={`${c.confidence}% confidence`}><i style={{ width: `${c.confidence}%` }} /></span>
                  <b>{c.confidence}%</b>
                </button></li>
              ))}
            </ul>
            {cand && <div className="cand-detail">
              {cand.reasons.length > 0 && <p className="hint">{cand.reasons.join(" · ")}</p>}
              {cand.matches.length > 0 && <pre className="code-snip">{cand.matches.map((m) => `${String(m.line).padStart(4)}  ${m.text}`).join("\n")}</pre>}
            </div>}
          </Card>
          <Card>
            <div className="row" style={{ justifyContent: "space-between" }}><h3>Effect radius</h3>{cand && <Badge tone={RISK[cand.blast.risk]}>{cand.blast.risk} risk</Badge>}</div>
            {cand && <>
              <div className="fx-grid" style={{ margin: "10px 0" }}>
                <div className="fx-tile"><span className="hint">Files affected</span><b>{cand.blast.affected}</b></div>
                <div className="fx-tile"><span className="hint">Of codebase</span><b>{cand.blast.percent_of_codebase}%</b></div>
                <div className="fx-tile"><span className="hint">Entry points</span><b>{cand.blast.entry_points.length}</b></div>
                <div className="fx-tile"><span className="hint">Tests touching it</span><b>{cand.blast.tests.length}</b></div>
              </div>
              {cand.blast.affected === 0 ? <p className="hint">Nothing else imports this file, so a change stays local.</p> : <div className="blast-wrap"><BlastMap b={cand.blast} /></div>}
            </>}
          </Card>
        </div>
      )}

      {r.what_if.length > 0 && <Card><h3>What if…</h3><ul className="wc-recs">{r.what_if.map((w, i) => <li key={i}><div><b>{w.scenario}</b><div>{w.effect}</div><div className="hint">{w.advice}</div></div></li>)}</ul></Card>}
      {r.related_issues.length > 0 && <Card><h3>Fragile code nearby</h3><ul className="wc-recs">{r.related_issues.map((i, n) => <li key={n}><div><span className="mono">{i.path}:{i.line}</span><div>{i.message}</div></div><Badge tone={SEV[i.severity]} icon={<IconWarn />}>{i.severity}</Badge></li>)}</ul></Card>}
      <p className="hint">Static analysis only: the code is read, never run. Confidence reflects how well the file matches the reported signals, not proof of the root cause.</p>
    </div>
  );
}

export function AnalyserPage() {
  const { me } = useAuth();
  const toast = useToast();
  const scoped = !!me?.scope;
  const access = useResource(api.planAccess, ["finance"]);
  const projects = useResource(api.codeProjects, []);
  const bugs = useResource(api.reportedBugs, ["incidents"]);
  const [pid, setPid] = useState("");
  const [bugId, setBugId] = useState(incidentFromHash() ?? "");
  const [desc, setDesc] = useState("");
  const [res, setRes] = useState<CodeAnalysis | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [pct, setPct] = useState(0);
  const [gh, setGh] = useState({ repo: "", branch: "", token: "", name: "" });
  const file = useRef<HTMLInputElement>(null);
  const list = projects.data?.projects ?? [];
  useEffect(() => { if (!pid && list[0]) setPid(list[0].id); }, [list.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const locked = scoped && !!access.data && !access.data.active;
  const proj = useMemo(() => list.find((p) => p.id === pid) ?? null, [list, pid]);

  async function subscribe() {
    setBusy("sub");
    try { await api.subscribePro(); toast.ok("Pro activated for this website."); access.reload(); projects.reload(); } catch (e) { toast.err((e as Error).message); } finally { setBusy(null); }
  }
  async function connect(e: FormEvent) {
    e.preventDefault();
    setBusy("gh");
    try { const p = await api.addGithub({ repo: gh.repo, branch: gh.branch || undefined, token: gh.token || undefined, name: gh.name || undefined }); setGh({ repo: "", branch: "", token: "", name: "" }); setPid(p.id); projects.reload(); toast.ok(`Connected ${p.name}: ${p.files} files indexed.`); }
    catch (err) { toast.err((err as Error).message); } finally { setBusy(null); }
  }
  async function upload(f: File | undefined) {
    if (!f) return;
    if (!/\.zip$/i.test(f.name)) return toast.err("Choose a .zip file of your source code.");
    setBusy("zip"); setPct(0);
    try { const p: CodeProject = await api.uploadCodeZip(f, f.name.replace(/\.zip$/i, ""), setPct); setPid(p.id); projects.reload(); toast.ok(`Uploaded ${p.name}: ${p.files} files indexed.`); }
    catch (err) { toast.err((err as Error).message); } finally { setBusy(null); if (file.current) file.current.value = ""; }
  }
  async function run() {
    if (!pid) return toast.err("Connect or select a project first.");
    setBusy("run"); setRes(null);
    try { setRes(await api.analyseCode(pid, bugId ? { incident_id: bugId } : { description: desc })); projects.reload(); } catch (err) { toast.err((err as Error).message); } finally { setBusy(null); }
  }
  async function remove(p: CodeProject) {
    if (!confirm(`Delete ${p.name} and the stored copy of its source?`)) return;
    try { await api.deleteCodeProject(p.id); if (pid === p.id) { setPid(""); setRes(null); } projects.reload(); toast.ok("Project deleted."); } catch (err) { toast.err((err as Error).message); }
  }

  if (locked) return <Upsell isAdmin={false} scoped access={access.data} onActivate={() => undefined} onSubscribe={subscribe} busy={busy === "sub"} feature="Codebase analyser" lede="Connect your source code and see where a reported bug comes from and how far a change would reach." />;

  return (
    <div className="page">
      <PageHead eyebrow="Pro · developer tool" title="Codebase analyser" lede="Connect the website's source, pick a bug reported on the dashboard, and see where it likely originates, what a change would touch, and what looks fragile nearby." />
      <div className="fin-cols">
        <Card>
          <h3><IconGithub /> Connect a GitHub repository</h3>
          <form className="stack" onSubmit={connect}>
            <label className="field"><span className="label">Repository</span><input className="input" required placeholder="owner/name or github.com link" value={gh.repo} onChange={(e) => setGh({ ...gh, repo: e.target.value })} /></label>
            <div className="grid-2">
              <label className="field"><span className="label">Branch (optional)</span><input className="input" placeholder="default branch" value={gh.branch} onChange={(e) => setGh({ ...gh, branch: e.target.value })} /></label>
              <label className="field"><span className="label">Token for private repos (optional)</span><input className="input" type="password" autoComplete="off" value={gh.token} onChange={(e) => setGh({ ...gh, token: e.target.value })} /></label>
            </div>
            <Button type="submit" variant="clay" busy={busy === "gh"} icon={<IconGithub />}>Connect and index</Button>
            <p className="hint">The token is used for this download only and is never stored.</p>
          </form>
        </Card>
        <Card>
          <h3><IconZip /> Upload a zip of the source</h3>
          <p className="hint">Up to 25 MB. node_modules, build output, binaries and lock files are skipped.</p>
          <input ref={file} type="file" accept=".zip,application/zip" hidden onChange={(e) => void upload(e.target.files?.[0])} />
          <Button variant="neu" icon={<IconUpload />} busy={busy === "zip"} onClick={() => file.current?.click()}>Choose a .zip file</Button>
          {busy === "zip" && <div className="stack" style={{ marginTop: 8 }} role="status" aria-live="polite"><div className="fin-bar"><i style={{ width: `${pct}%` }} /></div><span className="hint">{pct < 100 ? `Uploading… ${pct}%` : "Indexing files and building the dependency map…"}</span></div>}
        </Card>
      </div>

      <Card>
        <h3>Analyse a reported bug</h3>
        {projects.error && !projects.data ? <ErrorNote message={projects.error} retry={projects.reload} /> : projects.loading && !projects.data ? <Skeleton rows={2} h={48} /> : list.length === 0 ? <Empty icon={<IconCode />} title="No project connected yet">Connect a GitHub repository or upload a zip above to begin.</Empty> : (
          <div className="stack">
            <div className="proj-list">{list.map((p) => (
              <button key={p.id} type="button" className={`proj ${p.id === pid ? "on" : ""}`} aria-pressed={p.id === pid} onClick={() => setPid(p.id)}>
                <b>{p.name}</b><span className="hint">{p.source === "github" ? p.repo : "zip"} · {num(p.files)} files · {num(p.lines)} lines{p.analysed_at ? ` · analysed ${ago(p.analysed_at)}` : ""}</span>
                <span className="proj-del" role="button" tabIndex={0} aria-label={`Delete ${p.name}`} onClick={(e) => { e.stopPropagation(); void remove(p); }} onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); void remove(p); } }}>Delete</span>
              </button>))}</div>
            {proj && (proj.stats.high_issues ?? 0) > 0 && <Banner tone="info">{proj.stats.high_issues} high-severity pattern(s) found across {proj.name}, such as click handlers with no in-flight guard.</Banner>}
            <div className="grid-2">
              <label className="field"><span className="label">Bug reported on the dashboard</span>
                <select className="input" value={bugId} onChange={(e) => setBugId(e.target.value)}>
                  <option value="">Describe it myself…</option>
                  {(bugs.data?.bugs ?? []).map((b) => <option key={b.id} value={b.id}>[{b.severity}] {b.title}</option>)}
                </select></label>
              <label className="field"><span className="label">Or describe the bug</span><textarea className="input" rows={2} disabled={!!bugId} placeholder="e.g. Repeated clicks on the Pay now button at checkout" value={desc} onChange={(e) => setDesc(e.target.value)} /></label>
            </div>
            <div><Button variant="clay" busy={busy === "run"} icon={<IconTarget />} onClick={run}>Analyse</Button></div>
          </div>
        )}
      </Card>

      {busy === "run" && <Skeleton rows={3} h={120} />}
      {res && <Result r={res} />}
    </div>
  );
}
