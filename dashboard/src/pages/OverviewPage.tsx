import { useState } from "react";
import { api } from "../services/api";
import { useResource, type Resource } from "../hooks/useLive";
import { useAuth } from "../hooks/useAuth";
import { TypedRole } from "../components/TypedRole";
import { ROLE_LABEL } from "../services/format";
import { useToast } from "../hooks/useToast";
import type { Metrics } from "../types";
import { Banner, Card, ErrorNote, Skeleton, SeverityBadge, StateBadge, Stat } from "../components/ui";
import {
  IconActions, IconBug, IconChunks, IconCpu, IconDb, IconEvents, IconIntel, IconMail, IconRocket, IconSearch, IconCart, IconOnboard, IconTimer, IconChart, IconDonut,
} from "../components/icons";
import { ago, ms, num } from "../services/format";
import { ChartCard, Donut, HBar, Spark, TimeChart } from "../components/charts";
import { SiteActivityChart } from "../components/SiteActivity";
import { IconBroadcast, IconCode, IconGlobe } from "../components/icons";
import { usePoll } from "../hooks/usePoll";

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
  const ts = useResource(() => api.timeseries(24), ["metrics"]);
  const sites = useResource(api.sites, ["sites"]);
  usePoll(ts.reload, 30000);
  const { me } = useAuth();
  const m = metrics.data;
  const t = ts.data;
  const online = sites.data?.sites.filter((x) => x.online).length ?? 0;
  const hourLabel = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const last = (a?: number[]) => (a ?? []).slice(-12);

  return (
    <div className="page">
      <section className="hero" aria-label="Welcome">
        <div className="hero-copy">
          <span className="eyebrow">{new Date().toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" })}</span>
          <h1 className="welcome"><span>Welcome</span>{me && <em><TypedRole text={ROLE_LABEL[me.user.role]} /></em>}</h1>
          <p>Signed in as <b>{me?.user.name}</b>. Every figure here is read from backend state and refreshes the moment the backend announces a change.</p>
        </div>
        <div className="hero-chips">
          <a href={me?.scope ? undefined : "#/sites"} className="hero-chip"><IconGlobe /><b>{sites.data ? sites.data.sites.length : "–"}</b><span>{me?.scope ? "your website" : "connected sites"}</span></a>
          <a href={me?.scope ? undefined : "#/sites"} className="hero-chip live"><IconBroadcast /><b>{sites.data ? online : "–"}</b><span>live now</span></a>
          <a href="#/chunks" className="hero-chip"><IconChunks /><b>{m ? num(m.chunks_pending_review) : "–"}</b><span>in review</span></a>
          <a href="#/actions" className="hero-chip"><IconActions /><b>{m ? num(m.actions_awaiting_approval) : "–"}</b><span>need approval</span></a>
        </div>
      </section>
      {metrics.error && <ErrorNote message={metrics.error} retry={metrics.reload} />}
      {m && !m.monitoring_enabled && <Banner>Monitoring is switched off for this tenant. New events are being rejected.</Banner>}
      {!m ? <Skeleton kind="kpis" rows={6} h={110} /> : (
        <>
          <div className="split-half">
            <div className="kpi-grid">
              <Stat label="Events captured" value={num(m.events_total)} note={`${num(m.events_last_hour)} in the last hour`} icon={<IconEvents />} tone="blue" spark={<Spark values={last(t?.events)} />} />
              <Stat label="Awaiting review" value={num(m.chunks_pending_review)} note={`${num(m.chunks_indexed)} indexed`} icon={<IconChunks />} tone="blue" spark={<Spark values={last(t?.chunks)} />} />
              <Stat label="Active incidents" value={num(m.incidents_active)} note={`${num(m.recommendations_total)} recommendations`} icon={<IconIntel />} tone="blue" spark={<Spark values={last(t?.incidents)} />} />
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

      <Card className="live-card" title="Live extension activity" icon={<IconBroadcast />} sub="One line per connected website: events received every 15 seconds. Hover for exact values, click a legend item to hide a line."
        actions={<a href="#/sites" className="btn btn-ghost btn-sm">Sites &amp; roles</a>}>
        <SiteActivityChart minutes={15} height={250} />
      </Card>

      <Card title="Analytics" icon={<IconChart />} sub="Last 24 hours, read from stored events, chunks and incidents.">
        {!t || !m ? <Skeleton rows={2} h={180} /> : (
          <div className="charts charts-2">
            <ChartCard title="Events per hour" icon={<IconChart />}>
              <TimeChart area label="Events received per hour over the last 24 hours" labels={t.hours} fmtX={hourLabel} series={[{ name: "Events", values: t.events }]} />
            </ChartCard>
            <ChartCard title="Chunks and incidents per hour" icon={<IconDonut />}>
              <TimeChart label="Chunks created and incidents seen per hour" labels={t.hours} fmtX={hourLabel} series={[{ name: "Chunks", values: t.chunks }, { name: "Incidents", values: t.incidents }]} />
            </ChartCard>
            <ChartCard title="What customers did" icon={<IconChart />}>
              {t.event_types.length ? <HBar label="Event types in the last 24 hours" data={t.event_types} /> : <p className="hint">No events in the last 24 hours.</p>}
            </ChartCard>
            <ChartCard title="Chunk lab status" icon={<IconDonut />}>
              <Donut label="Chunks by stage" data={[
                { label: "In review", value: m.chunks_pending_review }, { label: "Embedding", value: m.chunks_in_flight }, { label: "Indexed", value: m.chunks_indexed },
                { label: "Discarded", value: (m.chunk_states.DISCARDED ?? 0) + (m.chunk_states.REJECTED ?? 0) },
              ]} />
            </ChartCard>
          </div>
        )}
      </Card>

      <div className="grid">
        <Card title="Recent incidents" icon={<IconBug />}>
          {!incidents.data ? <Skeleton rows={3} h={52} /> : incidents.data.incidents.length === 0 ? (
            <p className="hint">No incidents yet. Run a scripted journey or install the extension on an authorised site.</p>
          ) : (
            <div className="stack">
              {incidents.data.incidents.slice(0, 5).map((i) => (
                <div key={i.id} className="incident-item">
                  <div className="row" style={{ justifyContent: "space-between" }}><SeverityBadge s={i.severity} /><StateBadge state={i.status} /></div>
                  <h4>{i.title}</h4>
                  <span className="hint">{i.affected_sessions} journeys · last seen {ago(i.last_seen_at)}</span>
                  {/* Criticality decides how loudly the codebase analyser is offered: critical and high get a solid button, medium a quiet one, low none. */}
                  {(i.severity === "critical" || i.severity === "high") && <a className="btn btn-clay amber btn-sm analyser-cta" href={`#/analyser?incident=${i.id}`}><IconCode /> Open codebase analyser</a>}
                  {i.severity === "medium" && <a className="btn btn-ghost btn-sm analyser-cta" href={`#/analyser?incident=${i.id}`}><IconCode /> Analyse the code</a>}
                </div>
              ))}
            </div>
          )}
        </Card>

      </div>
    </div>
  );
}
