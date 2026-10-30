import { useEffect, useState, type FormEvent } from "react";
import { api } from "../services/api";
import { useResource } from "../hooks/useLive";
import { useAuth } from "../hooks/useAuth";
import { useToast } from "../hooks/useToast";
import type { IncidentDetail, ResolutionSource } from "../types";
import { Badge, Banner, Button, Card, Empty, ErrorNote, Meter, Modal, PageHead, SeverityBadge, SimBadge, Skeleton, StateBadge } from "../components/ui";
import { IconBug, IconCheck, IconFlag, IconIntel, IconRefresh, IconTarget, IconHandshake, IconAudit } from "../components/icons";
import { ago, dateTimeOf, pct, titleCase } from "../services/format";

function ResolutionModal({ inc, onClose, onDone }: { inc: IncidentDetail; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [category, setCategory] = useState(inc.issue_signature);
  const [claims, setClaims] = useState("");
  const [segment, setSegment] = useState(false);
  const [release, setRelease] = useState("");
  const [test, setTest] = useState("");
  const [telemetry, setTelemetry] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const sources: ResolutionSource[] = [];
    if (release.trim()) sources.push({ type: "release", ref: release.trim(), status: "deployed" });
    if (test.trim()) sources.push({ type: "test_run", ref: test.trim(), status: "passed" });
    if (telemetry.trim()) sources.push({ type: "telemetry", ref: telemetry.trim(), status: "improved" });
    setBusy(true);
    try {
      const r = await api.createResolution({
        incident_id: inc.id, issue_category: category, sources, segment_available: segment,
        approved_claims: claims.split("\n").map((c) => c.trim()).filter(Boolean),
      });
      r.resolution_status === "verified" ? toast.ok("Resolution verified. Customer email drafts are being prepared.") : toast.err(`Recorded but not verified: ${r.verification_notes[0] ?? ""}`);
      onDone();
      onClose();
    } catch (err) { toast.err((err as Error).message); } finally { setBusy(false); }
  }

  return (
    <Modal title="Record a resolution" onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <p className="hint">Customer messaging stays locked until a deployed release and workflow proof are on record, and the improvement is confirmed for the customer segment.</p>
        <div className="field"><label htmlFor="cat">Issue category</label><input id="cat" className="input" required value={category} onChange={(e) => setCategory(e.target.value)} /></div>
        <div className="field"><label htmlFor="rel">Deployed release</label><input id="rel" className="input" placeholder="release_000014" value={release} onChange={(e) => setRelease(e.target.value)} /></div>
        <div className="field"><label htmlFor="tst">Passing test run</label><input id="tst" className="input" placeholder="test_run_000029" value={test} onChange={(e) => setTest(e.target.value)} /></div>
        <div className="field"><label htmlFor="tel">Improved telemetry (optional)</label><input id="tel" className="input" placeholder="dashboard link or ID" value={telemetry} onChange={(e) => setTelemetry(e.target.value)} /></div>
        <div className="field"><label htmlFor="clm">Approved customer-facing claims (one per line)</label><textarea id="clm" className="input" placeholder="The checkout flow has been improved" value={claims} onChange={(e) => setClaims(e.target.value)} /></div>
        <label className="row"><input type="checkbox" checked={segment} onChange={(e) => setSegment(e.target.checked)} /> The improvement is live for the intended customer segment</label>
        <Button variant="clay" type="submit" busy={busy} icon={<IconCheck />}>Record resolution</Button>
      </form>
    </Modal>
  );
}

function Detail({ id, reloadList }: { id: string; reloadList: () => void }) {
  const { can } = useAuth();
  const toast = useToast();
  const res = useResource<IncidentDetail>(() => api.incident(id), ["incidents", "actions", "resolutions", "outcomes"], [id]);
  const [busy, setBusy] = useState<string | null>(null);
  const [modal, setModal] = useState(false);
  const inc = res.data;

  if (res.error) return <ErrorNote message={res.error} retry={res.reload} />;
  if (!inc) return <Skeleton rows={4} h={110} />;

  async function run(name: string, fn: () => Promise<unknown>, ok: string) {
    setBusy(name);
    try { await fn(); toast.ok(ok); res.reload(); reloadList(); } catch (e) { toast.err((e as Error).message); } finally { setBusy(null); }
  }
  const analyzing = inc.status === "analyzing" || inc.status === "analysis_queued";

  return (
    <div className="stack">
      <Card title={inc.title} icon={<IconBug />} sub={`${titleCase(inc.incident_type)} · lifecycle: ${titleCase(inc.lifecycle_stage)}`}
        actions={<>
          {can("incidents:analyze") && <Button variant="neu" icon={<IconRefresh />} busy={busy === "analyze" || analyzing} onClick={() => run("analyze", () => api.analyze(inc.id), "Analysis requested.")}>Analyse</Button>}
          {can("resolutions:write") && inc.status !== "resolved" && <Button variant="clay" icon={<IconHandshake />} onClick={() => setModal(true)}>Record resolution</Button>}
          {can("outcomes:evaluate") && inc.resolution_id && <Button variant="clay-amber" icon={<IconTarget />} busy={busy === "eval"} onClick={() => run("eval", () => api.evaluate(inc.id), "Outcome evaluated.")}>Evaluate outcome</Button>}
        </>}>
        <div className="row">
          <SeverityBadge s={inc.severity} /><StateBadge state={inc.status} />
          <Badge tone="blue">{inc.affected_sessions} journeys</Badge>
          <Badge tone="violet" title={inc.analysis_notes.join(" ")}>Analysis: {inc.analysis_provider || "pending"}</Badge>
          {inc.regression_count > 0 && <Badge tone="red">Regressed {inc.regression_count}×</Badge>}
          <SimBadge simulated={inc.simulated} />
        </div>
        {inc.analysis_notes.length > 0 && <p className="hint" style={{ marginTop: 10 }}>{inc.analysis_notes.join(" · ")}</p>}
      </Card>

      {analyzing && <Banner tone="info">Analysis is running. This page updates when the backend finishes.</Banner>}

      <div className="grid two">
        <Card title="Observed facts" icon={<IconCheck />} sub="Directly recorded, not inferred">
          {inc.observed_facts.length ? <ul className="facts">{inc.observed_facts.map((f, i) => <li key={i}>{f}</li>)}</ul> : <p className="hint">Not analysed yet.</p>}
        </Card>
        <Card title="Unresolved questions" icon={<IconFlag />}>
          {inc.unresolved_questions.length ? <ul className="questions">{inc.unresolved_questions.map((f, i) => <li key={i}>{f}</li>)}</ul> : <p className="hint">None recorded.</p>}
        </Card>
      </div>

      <Card title="Hypotheses" icon={<IconIntel />} sub="Confidence is a model estimate, not a calibrated probability. Correlation is not causation.">
        {inc.hypotheses.length === 0 ? <p className="hint">No hypotheses yet.</p> : (
          <div className="stack">
            {inc.hypotheses.map((h, i) => (
              <div className="hyp" key={i}>
                <div className="row" style={{ justifyContent: "space-between" }}><span>{h.description}</span><span className="pct">{pct(h.confidence)}</span></div>
                <Meter value={h.confidence} tone={h.confidence < 0.5 ? "amber" : ""} label="confidence" />
                <div className="row">{h.evidence_ids.map((e) => <span className="chip" key={e}>{e}</span>)}</div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <div className="grid two">
        <Card title="Recommended action" icon={<IconTarget />} sub="The model proposes. The action engine decides.">
          {inc.recommended_action.type ? (
            <dl className="kv"><dt>Type</dt><dd>{titleCase(inc.recommended_action.type)}</dd><dt>Priority</dt><dd>{titleCase(inc.recommended_action.priority ?? "")}</dd><dt>Reason</dt><dd>{inc.recommended_action.reason}</dd><dt>Customer message</dt><dd>{inc.customer_message_eligible ? "Eligible" : "Not eligible yet"}</dd></dl>
          ) : <p className="hint">None yet.</p>}
          <p style={{ marginTop: 12 }}><a href="#/actions">Open the action center →</a></p>
        </Card>
        <Card title="Evidence" icon={<IconIntel />}>
          <div className="row">{inc.evidence_ids.length ? inc.evidence_ids.map((e) => <span className="chip" key={e}>{e}</span>) : <span className="hint">No cited evidence.</span>}</div>
          {inc.last_retrieval_id && <p style={{ marginTop: 12 }}><a href="#/chunks">Open the RAG window →</a></p>}
          <div className="stack" style={{ marginTop: 14 }}>{inc.chunks.slice(0, 5).map((c) => <div key={c.id} className="feed-item"><span className="chip">{c.id.slice(-6)}</span><span>{c.summary}</span><span className="hint">{ago(c.created_at)}</span></div>)}</div>
        </Card>
      </div>

      {inc.resolution && (
        <Card title="Resolution" icon={<IconHandshake />} actions={<StateBadge state={inc.resolution.resolution_status} />}>
          <ul className="facts">{inc.resolution.verification_notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
        </Card>
      )}
      {modal && <ResolutionModal inc={inc} onClose={() => setModal(false)} onDone={() => { res.reload(); reloadList(); }} />}
    </div>
  );
}

export function IntelligencePage() {
  const list = useResource(api.incidents, ["incidents"]);
  const [sel, setSel] = useState<string | null>(null);
  const incidents = list.data?.incidents ?? [];
  useEffect(() => { if (!sel && incidents[0]) setSel(incidents[0].id); }, [incidents, sel]);
  const audit = useResource(() => api.audit(80), ["actions", "chunks", "config"]);

  return (
    <div className="page">
      <PageHead eyebrow="-------" title="< Diagnostics />" />
      {list.error && <ErrorNote message={list.error} retry={list.reload} />}
      <div className="grid split">
        <Card title="Incidents" icon={<IconBug />}>
          {!list.data ? <Skeleton rows={4} h={72} /> : incidents.length === 0 ? <Empty icon={<IconBug />} title="No incidents">They appear once indexed evidence shows repeated friction.</Empty> : (
            <div className="incident-list">
              {incidents.map((i) => (
                <button key={i.id} className="incident-item" aria-current={sel === i.id} onClick={() => setSel(i.id)}>
                  <div className="row" style={{ justifyContent: "space-between" }}><SeverityBadge s={i.severity} /><StateBadge state={i.status} /></div>
                  <h4>{i.title}</h4>
                  <span className="hint">{i.affected_sessions} journeys · {ago(i.last_seen_at)}</span>
                </button>
              ))}
            </div>
          )}
        </Card>
        <div>{sel ? <Detail id={sel} reloadList={list.reload} /> : <Card><Empty icon={<IconIntel />} title="Select an incident" /></Card>}</div>
      </div>

      <Card title="Audit log" icon={<IconAudit />} sub="Who approved, edited, rejected, extended or executed what, and when.">
        {!audit.data ? <Skeleton rows={5} h={34} /> : (
          <div className="feed">
            {audit.data.audit.map((a) => (
              <div className="feed-item" key={a.id}>
                <span className="mono">{dateTimeOf(a.ts)}</span>
                <span><b>{titleCase(a.action)}</b> · {a.entity_type} <span className="mono">{a.entity_id.slice(-8)}</span>{a.from_state || a.to_state ? ` · ${a.from_state ?? "–"} → ${a.to_state ?? "–"}` : ""}</span>
                <span className="hint">{a.actor}</span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
