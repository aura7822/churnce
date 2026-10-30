import { useState } from "react";
import { api } from "../services/api";
import { useResource, type Resource } from "../hooks/useLive";
import { useAuth } from "../hooks/useAuth";
import { useToast } from "../hooks/useToast";
import type { Metrics } from "../types";
import { Banner, Card, ErrorNote, PageHead, Skeleton, SeverityBadge, StateBadge, Stat } from "../components/ui";
import {
  IconActions, IconBug, IconChunks, IconCpu, IconDb, IconEvents, IconIntel, IconMail, IconRocket, IconSearch, IconCart, IconOnboard, IconTimer, IconChart, IconDonut,
} from "../components/icons";
import { ago, ms, num } from "../services/format";
import { BarChart, ChartCard, Donut, HBar } from "../components/charts";

const STAGES: { key: string; label: string; icon: JSX.Element; pick: (m: Metrics) => number }[] = [
  { key: "collect", label: "Events", icon: <IconEvents />, pick: (m) => m.events_total },
  { key: "review", label: "In review", icon: <IconTimer />, pick: (m) => m.chunks_pending_review },
  { key: "flight", label: "Embedding", icon: <IconCpu />, pick: (m) => m.chunks_in_flight },
  { key: "indexed", label: "Indexed", icon: <IconDb />, pick: (m) => m.chunks_indexed },
  { key: "incidents", label: "Incidents", icon: <IconBug />, pick: (m) => m.incidents_active },
];

const SCENARIO_ICON: Record<string, JSX.Element> = {
  checkout_failure: <IconCart />, checkout_success: <IconRocket />, onboarding_stall: <IconOnboard />, search_dead_end: <IconSearch />,
};

function Scenarios() {
  const { can } = useAuth();
  const toast = useToast();
  const sc = useResource(api.scenarios);
  const [busy, setBusy] = useState<string | null>(null);
  if (!can("demo:simulate") || !sc.data?.enabled) return null;

  async function run(id: string) {
    setBusy(id);
    try {
      const r = await api.simulate(id, 5);
      toast.ok(`Ran ${r.sessions} journeys (${r.accepted} events). Watch the chunk lab.`);
    } catch (e) { toast.err((e as Error).message); } finally { setBusy(null); }
  }

  return (
    <Card title="Scripted journeys" icon={<IconRocket />} sub="Replays a scripted customer journey through the real ingest path.">
      <div className="grid two">
        {sc.data.scenarios.map((s) => (
          <button key={s.id} className="scenario" disabled={busy !== null} onClick={() => run(s.id)}>
            <b>{SCENARIO_ICON[s.id] ?? <IconRocket />}{s.label}{busy === s.id ? " …" : ""}</b>
            <small>{s.description}</small>
          </button>
        ))}
      </div>
    </Card>
  );
}

export function OverviewPage({ metrics }: { metrics: Resource<Metrics> }) {
  const incidents = useResource(api.incidents, ["incidents"]);
  const m = metrics.data;

  return (
    <div className="page">
      <PageHead eyebrow="" title="< globalPreview />" />
      {metrics.error && <ErrorNote message={metrics.error} retry={metrics.reload} />}
      {m && !m.monitoring_enabled && <Banner>Monitoring is switched off for this tenant. New events are being rejected.</Banner>}
      {!m ? <Skeleton rows={2} h={110} /> : (
        <>
          <div className="split-half">
            <div className="kpi-grid">
              <Stat label="Instance capture" value={num(m.events_total)} note={`${num(m.events_last_hour)} in the last hour`} icon={<IconEvents />} tone="blue" />
              <Stat label="Awaiting review" value={num(m.chunks_pending_review)} note={`${num(m.chunks_indexed)} indexed`} icon={<IconChunks />} tone="blue" />
              <Stat label="Active incidents" value={num(m.incidents_active)} note={`${num(m.recommendations_total)} recommendations`} icon={<IconIntel />} tone="blue" />
              <Stat label="Need approval" value={num(m.actions_awaiting_approval)} note={`${num(m.actions_completed)} done · ${num(m.actions_failed)} failed`} icon={<IconActions />} tone="blue" />
              <Stat label="Email drafts" value={num(m.emails_draft)} note={`${num(m.emails_approved)} approved`} icon={<IconMail />} tone="blue" />
              <Stat label="Latency p95" value={ms(m.processing_latency_ms.p95)} note={`p50 ${ms(m.processing_latency_ms.p50)} · ${m.processing_latency_ms.samples} samples`} icon={<IconTimer />} tone="blue" />
            </div>
            <Card className="tile pipeline-card" title="Pipeline" icon={<IconCpu />} sub="Events → review gate → embedding → index → incidents">
              <div className="pipeline">
                {STAGES.map((s) => {
                  const n = s.pick(m);
                  return <div key={s.key} className={`stage ${n > 0 && s.key !== "collect" ? "live" : ""}`}>{s.icon}<span className="l">{s.label}</span><span className="n">{num(n)}</span></div>;
                })}
              </div>
            </Card>
          </div>
        </>
      )}

      <Scenarios />

      {m && (
        <Card title="Summary graphs" icon={<IconChart />} sub="One view per area of the app, drawn from the same backend metrics.">
          <div className="charts">
            <ChartCard title="Events to incidents" icon={<IconChart />}>
              <BarChart label="Counts per pipeline stage" data={STAGES.map((s) => ({ label: s.label, value: s.pick(m) }))} />
            </ChartCard>
            <ChartCard title="Chunk lab" icon={<IconDonut />}>
              <Donut label="Chunks by stage" data={[
                { label: "In review", value: m.chunks_pending_review }, { label: "Embedding", value: m.chunks_in_flight }, { label: "Indexed", value: m.chunks_indexed },
                { label: "Discarded", value: (m.chunk_states.DISCARDED ?? 0) + (m.chunk_states.REJECTED ?? 0) },
              ]} />
            </ChartCard>
            <ChartCard title="Diagnostics" icon={<IconChart />}>
              <HBar label="Incident, action and email counts" data={[
                { label: "Incidents", value: m.incidents_active }, { label: "Need approval", value: m.actions_awaiting_approval }, { label: "Completed", value: m.actions_completed },
                { label: "Failed", value: m.actions_failed }, { label: "Drafts", value: m.emails_draft }, { label: "Approved", value: m.emails_approved },
              ]} />
            </ChartCard>
          </div>
        </Card>
      )}

      <div className="grid">
        <Card title="Recent incidents" icon={<IconBug />} actions={<a href="#/intelligence" className="btn btn-ghost btn-sm">Open feed</a>}>
          {!incidents.data ? <Skeleton rows={3} h={52} /> : incidents.data.incidents.length === 0 ? (
            <p className="hint">No incidents yet. Run a scripted journey or install the extension on an authorised site.</p>
          ) : (
            <div className="stack">
              {incidents.data.incidents.slice(0, 5).map((i) => (
                <a key={i.id} href="#/intelligence" className="incident-item" style={{ textDecoration: "none", color: "inherit" }}>
                  <div className="row" style={{ justifyContent: "space-between" }}><SeverityBadge s={i.severity} /><StateBadge state={i.status} /></div>
                  <h4>{i.title}</h4>
                  <span className="hint">{i.affected_sessions} journeys · last seen {ago(i.last_seen_at)}</span>
                </a>
              ))}
            </div>
          )}
        </Card>

      </div>
    </div>
  );
}
