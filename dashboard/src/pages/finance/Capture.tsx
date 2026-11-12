import { useEffect, useMemo, useRef, useState } from "react";
import type { CaptureSite, CaptureStatus } from "../../types";
import { Badge, Button, Card, Empty, Led } from "../../components/ui";
import { IconBroadcast, IconCheck, IconGlobe, IconPause, IconPlay, IconRefresh, IconStop, IconTerminal } from "../../components/icons";
import { useServerNow } from "../../hooks/useLive";
import { timeOf } from "../../services/format";

const STEPS = ["Handshake", "Consent check", "Pulling transactions", "Reconciled"];
const SYNC_TOTAL_MS = 8000;

type Fresh = "live" | "idle" | "offline";
const freshness = (s: CaptureSite): Fresh => (!s.online || s.seconds_since_seen === null ? "offline" : s.seconds_since_seen < 45 ? "live" : s.seconds_since_seen < 120 ? "idle" : "offline");
const pingText = (s: CaptureSite) => (s.rtt_ms !== null && s.rtt_ms !== undefined ? `ping ${Math.round(s.rtt_ms)} ms` : s.seconds_since_seen === null ? "never seen" : `last seen ${s.seconds_since_seen}s ago`);

/** Connected-website ping indicator: one pill per site. */
export function PingBar({ status }: { status: CaptureStatus | null }) {
  if (!status) return <div className="fin-ping" aria-busy="true"><span className="fin-pill skel">Checking connected websites…</span></div>;
  if (!status.sites.length) return <div className="fin-ping"><span className="fin-pill off"><Led kind="" label="no websites" />No connected websites yet. Authorise one in the extension.</span></div>;
  return (
    <div className="fin-ping" role="list" aria-label="Connected website ping">
      {status.sites.map((s) => {
        const f = freshness(s);
        return (
          <span key={s.host} role="listitem" className={`fin-pill ${f}`} title={s.last_seen ? `Last heartbeat ${s.last_seen}` : "No heartbeat yet"}>
            <Led kind={f === "live" ? "on" : f === "idle" ? "warn" : "bad"} pulse={f === "live"} label={f} />
            <b>{s.name || s.host}</b>{s.website_id && <code className="chip-id">{s.website_id}</code>}
            <span className="fin-ping-ms">{pingText(s)}</span>
          </span>
        );
      })}
    </div>
  );
}

const stateTone = { running: "green", paused: "amber", stopped: "red" } as const;

export function CaptureControls({ status, busy, canControl, onAct, error }: {
  status: CaptureStatus | null; busy: string | null; canControl: boolean; error: string | null; onAct: (a: "start" | "pause" | "restart" | "stop") => void;
}) {
  const st = status?.state ?? "stopped";
  const dis = (a: string) => !canControl || !!busy || !status || (a === "start" && st === "running") || (a === "pause" && st !== "running") || (a === "stop" && st === "stopped") || (a === "restart" && st === "stopped");
  return (
    <Card className="fin-capture" title="Real-time capture" icon={<IconBroadcast />}
      sub={canControl ? "Control whether transactions from connected websites are being captured." : "Your role can watch capture but not change it."}
      actions={status ? <Badge tone={stateTone[st]}>{st}{status.since ? ` · since ${timeOf(status.since)}` : ""}</Badge> : null}>
      <div className="fin-ctl" role="group" aria-label="Capture controls">
        <Button variant="clay" icon={<IconPlay />} busy={busy === "start"} disabled={dis("start")} onClick={() => onAct("start")}>Start</Button>
        <Button variant="neu" icon={<IconPause />} busy={busy === "pause"} disabled={dis("pause")} onClick={() => onAct("pause")}>Pause</Button>
        <Button variant="neu" icon={<IconRefresh />} busy={busy === "restart"} disabled={dis("restart")} onClick={() => onAct("restart")}>Restart</Button>
        <Button variant="clay-rose" icon={<IconStop />} busy={busy === "stop"} disabled={dis("stop")} onClick={() => onAct("stop")}>Stop</Button>
      </div>
      {error && <p className="fin-err" role="alert">{error}</p>}
      <p className="hint">Paused keeps the connection and drops new transactions until you resume. Stopped also ends syncing. The extension honours this within about 30 seconds.</p>
    </Card>
  );
}

function stepFor(s: CaptureSite, progress: number): number {
  if (s.sync === "live") return STEPS.length;
  if (s.sync === "syncing") return Math.min(STEPS.length - 1, Math.floor(progress * STEPS.length));
  return 0;
}

/** Visible while a sync runs: per-site stepper with animated progress bars, plus a live log terminal. */
export function SyncPanel({ status, active }: { status: CaptureStatus; active: boolean }) {
  const now = useServerNow(250);
  const until = status.syncing_until ? new Date(status.syncing_until).getTime() : 0;
  const progress = active && until ? Math.max(0, Math.min(1, 1 - (until - now) / SYNC_TOTAL_MS)) : 1;
  return (
    <Card className="fin-sync" title="Syncing website data" icon={<IconGlobe />} sub={active ? "Reading each website's captured transactions and reconciling them." : "All websites are in sync."}
      actions={active ? <span className="fin-sync-tag"><i /> syncing</span> : <Badge tone="green" icon={<IconCheck />}>in sync</Badge>}>
      {status.sites.length === 0 ? <Empty icon={<IconGlobe />} title="No connected websites to sync" /> : (
        <ul className="fin-sync-list">
          {status.sites.map((s) => {
            const step = stepFor(s, progress);
            const pct = s.sync === "live" ? 100 : s.sync === "syncing" ? Math.round(progress * 100) : 0;
            return (
              <li key={s.host} className={`fin-sync-row ${s.sync}`}>
                <div className="fin-sync-name"><b>{s.name || s.host}</b><span className="hint">{s.txn_count.toLocaleString()} transactions{s.last_txn_at ? ` · last ${timeOf(s.last_txn_at)}` : ""}</span></div>
                <ol className="fin-steps" aria-label={`Sync steps for ${s.host}`}>
                  {STEPS.map((t, i) => <li key={t} className={i < step ? "done" : i === step && s.sync === "syncing" ? "now" : ""}><i>{i < step ? <IconCheck /> : i + 1}</i><span>{t}</span></li>)}
                </ol>
                <div className="fin-bar" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={`Sync progress for ${s.host}`}><i style={{ width: `${pct}%` }} /></div>
              </li>
            );
          })}
        </ul>
      )}
      <LogTerminal logs={status.logs} open />
    </Card>
  );
}

export function LogTerminal({ logs, open: initial = false }: { logs: CaptureStatus["logs"]; open?: boolean }) {
  const [open, setOpen] = useState(initial);
  const ref = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  useEffect(() => { const el = ref.current; if (el && stick.current) el.scrollTop = el.scrollHeight; }, [logs, open]);
  const rows = useMemo(() => logs.slice(-120), [logs]);
  return (
    <div className="fin-logs">
      <button type="button" className="fin-logs-head" aria-expanded={open} onClick={() => setOpen(!open)}><IconTerminal /> Capture logs <span className="hint">{rows.length} lines</span><i className={open ? "up" : ""} aria-hidden="true">▾</i></button>
      {open && (
        <div ref={ref} className="fin-term" role="log" aria-live="polite" tabIndex={0}
          onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24; }}>
          {rows.length === 0 ? <div className="fin-term-empty">Waiting for the first log line…</div> : rows.map((l, i) => (
            <div key={i} className={`fin-line ${l.level}`}><time>{timeOf(l.ts)}</time><em>{l.level}</em><code>{l.host}</code><span>{l.msg}</span></div>
          ))}
        </div>
      )}
    </div>
  );
}
