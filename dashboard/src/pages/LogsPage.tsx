import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../services/api";
import { useResource } from "../hooks/useLive";
import { SiteConsole } from "./SitesPage";
import type { LogLine, LogsResponse, SiteRow } from "../types";
import { Badge, Button, Card, Empty, ErrorNote, Led, Modal, PageHead, Segmented, Skeleton } from "../components/ui";
import { IconDb, IconHeart, IconPause, IconPlay, IconRefresh, IconTerminal, IconTrash, IconWarn, IconCpu, IconPlug, IconClock, IconGlobe, IconBroadcast } from "../components/icons";

type Level = "INFO" | "WARNING" | "ERROR";
const MAX_LINES = 1500;

function uptime(s: number) {
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m ${s % 60}s`;
}

function Indicator({ title, icon, tone, value, detail }: { title: string; icon: JSX.Element; tone: "ok" | "warn" | "bad"; value: string; detail: string }) {
  return (
    <div className={`ind ${tone}`} role="group" aria-label={`${title}: ${value}`}>
      <div className="t">{icon}{title}</div>
      <div className="v">{value}</div>
      <div className="d">{detail}</div>
    </div>
  );
}

/** Connected websites as clickable rows: opening one shows that site's logs and its live extension activity. */
function SiteLogs() {
  const sites = useResource(api.sites, ["sites"]);
  const [open, setOpen] = useState<SiteRow | null>(null);
  useEffect(() => { const id = setInterval(sites.reload, 10000); return () => clearInterval(id); }, [sites.reload]);
  const list = sites.data?.sites ?? [];
  return (
    <Card title="Connected website logs" icon={<IconGlobe />} sub="Select a website to read its logs and watch what the extension is doing on it in real time.">
      {sites.error && <ErrorNote message={sites.error} retry={sites.reload} />}
      {!sites.data ? <Skeleton rows={2} h={48} /> : list.length === 0 ? (
        <Empty icon={<IconGlobe />} title="No websites connected">Authorise a site and accept the consent permissions in the extension settings.</Empty>
      ) : (
        <ul className="site-rows">
          {list.map((s) => (
            <li key={s.id}>
              <button type="button" className="site-row" onClick={() => setOpen(s)} aria-label={`Open logs and live activity for ${s.host}`}>
                <Led kind={s.online ? "on" : ""} pulse={s.online} />
                <b>{s.host}</b>
                <span className="hint">{s.online ? "live now" : "offline"} · {s.event_count} events</span>
                <Badge tone={s.monitoring ? "green" : ""} icon={<IconBroadcast />}>{s.monitoring ? "monitoring" : "paused"}</Badge>
              </button>
            </li>
          ))}
        </ul>
      )}
      {open && <Modal wide title={`${open.host} · logs and live activity`} onClose={() => setOpen(null)}><SiteConsole site={open} /></Modal>}
    </Card>
  );
}

/** Streams the backend's log buffer by polling for lines newer than the last one seen. */
export function LogsPage() {
  const [lines, setLines] = useState<LogLine[]>([]);
  const [snap, setSnap] = useState<LogsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [level, setLevel] = useState<Level>("INFO");
  const [follow, setFollow] = useState(true);
  const [live, setLive] = useState(true);
  const last = useRef(0);
  const view = useRef<HTMLDivElement>(null);

  const poll = useCallback(async (reset = false) => {
    try {
      const r = await api.logs(reset ? 0 : last.current, level);
      setSnap(r); setError(null);
      if (r.logs.length || reset) {
        if (r.logs.length) last.current = r.logs[r.logs.length - 1].id;
        setLines((prev) => (reset ? r.logs : [...prev, ...r.logs]).slice(-MAX_LINES));
      }
    } catch (e) { setError((e as Error).message); }
  }, [level]);

  useEffect(() => { last.current = 0; setLines([]); poll(true); }, [poll]);
  useEffect(() => { if (!live) return; const id = setInterval(() => poll(false), 2500); return () => clearInterval(id); }, [live, poll]);
  useEffect(() => { if (follow && view.current) view.current.scrollTop = view.current.scrollHeight; }, [lines, follow]);

  const ind = snap?.indicators;
  const db = ind?.database;
  const dbTone = !db ? "warn" : !db.ok ? "bad" : db.latency_ms > 400 ? "warn" : "ok";
  const sch = ind?.scheduler;
  const llm = ind?.providers.llm, emb = ind?.providers.embeddings;
  const count = useMemo(() => ({ err: lines.filter((l) => l.level === "ERROR" || l.level === "CRITICAL").length, warn: lines.filter((l) => l.level === "WARNING").length }), [lines]);

  return (
    <div className="page">
      <PageHead eyebrow="Operations" title="Backend logs" lede="Everything the backend server prints, including warnings and errors, with live health indicators. Secrets are masked before storage." />
      {error && <ErrorNote message={error} retry={() => poll(true)} />}

      {!ind ? <Skeleton rows={2} h={100} /> : (
        <div className="indicators">
          <Indicator title="Database ping" icon={<IconDb />} tone={dbTone} value={db!.ok ? `${db!.latency_ms} ms` : "Unreachable"}
            detail={db!.ok ? `${db!.engine}${db!.neon ? " · Neon" : ""}${db!.pooled ? " · pooled" : ""}${db!.pool.in_use !== undefined ? ` · ${db!.pool.in_use}/${db!.pool.size} conns` : ""}` : db!.error ?? "no answer"} />
          <Indicator title="Scheduler" icon={<IconClock />} tone={sch!.healthy ? (sch!.last_error ? "warn" : "ok") : "bad"} value={sch!.healthy ? "Running" : "Stalled"} detail={sch!.last_error ?? `${sch!.ticks} ticks`} />
          <Indicator title="Errors · 5 min" icon={<IconWarn />} tone={ind.errors_5m ? "bad" : ind.warnings_5m ? "warn" : "ok"} value={String(ind.errors_5m)} detail={`${ind.warnings_5m} warnings`} />
          <Indicator title="Reasoning" icon={<IconCpu />} tone={llm?.ready ? "ok" : "warn"} value={llm?.label ?? "–"} detail={llm?.ready ? "provider ready" : `fallback ${llm?.fallback}`} />
          <Indicator title="Embeddings" icon={<IconCpu />} tone={emb?.ready ? "ok" : "warn"} value={emb?.provider ?? "–"} detail={emb?.model ?? ""} />
          <Indicator title="Live clients" icon={<IconPlug />} tone="ok" value={String(ind.realtime_subscribers)} detail="WebSocket subscribers" />
          <Indicator title="Uptime" icon={<IconHeart />} tone="ok" value={uptime(ind.uptime_seconds)} detail={`v${ind.version} · ${ind.environment}`} />
        </div>
      )}

      <SiteLogs />

      <Card title="Server output" icon={<IconTerminal />} sub={`${lines.length} lines shown · ${count.err} errors · ${count.warn} warnings · buffer holds ${snap?.buffered ?? 0}`}
        actions={<div className="row">
          <Button variant="ghost" className="btn-sm" icon={live ? <IconPause /> : <IconPlay />} onClick={() => setLive((v) => !v)}>{live ? "Pause" : "Resume"}</Button>
          <Button variant="ghost" className="btn-sm" icon={<IconRefresh />} onClick={() => poll(true)}>Reload</Button>
          <Button variant="ghost" className="btn-sm" icon={<IconTrash />} onClick={() => setLines([])}>Clear view</Button>
        </div>}>
        <div className="logs-toolbar" style={{ marginBottom: 12 }}>
          <Segmented<Level> value={level} onChange={setLevel} options={[{ id: "INFO", label: "All" }, { id: "WARNING", label: "Warnings+" }, { id: "ERROR", label: "Errors" }]} />
          <label className="row" style={{ gap: 8, fontSize: 13 }}><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> Follow newest</label>
        </div>
        <div className="logview" ref={view} role="log" aria-live="off" tabIndex={0} aria-label="Backend log output">
          {lines.length === 0 ? <div className="logline INFO"><span /><span /><span /><span>No log lines at this level yet.</span></div> : lines.map((l) => (
            <div key={l.id} className={`logline ${l.level}`}>
              <span className="ts">{new Date(l.ts).toLocaleTimeString([], { hour12: false })}</span>
              <span className="lv">{l.level}</span>
              <span className="lg" title={l.logger}>{l.logger}</span>
              <span>{l.message}</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
