import { useEffect, useRef, useState } from "react";
import { api } from "../services/api";
import { useResource } from "../hooks/useLive";
import { usePoll } from "../hooks/usePoll";
import { useAuth } from "../hooks/useAuth";
import { useToast } from "../hooks/useToast";
import type { FeedRow, Role, SiteRow } from "../types";
import { Badge, Banner, Card, Empty, ErrorNote, Led, Modal, PageHead, Segmented, Skeleton, Toggle } from "../components/ui";
import { IconBroadcast, IconCookie, IconGlobe, IconLock, IconTerminal, IconUsers, IconUser } from "../components/icons";
import { SiteActivityChart } from "../components/SiteActivity";
import { ago, dateTimeOf, num, ROLE_LABEL } from "../services/format";
import { useSiteView } from "../services/siteView";
import { serverNow } from "../services/api";
import { useTick } from "../hooks/useTick";
import { Button } from "../components/ui";
import { IconChart } from "../components/icons";

export { ROLE_LABEL };
const ROLE_NOTE: Record<Role, string> = {
  administrator: "Full control, including roles and configuration.",
  developer: "Reviews chunks, analyses incidents, reads backend and site logs.",
  website_owner: "Approves marketing actions and win-back emails, and runs finance capture.",
  data_analyst: "Reviews chunks, analyses incidents and finance, records outcomes.",
};
const SCOPE_LABEL: Record<SiteRow["consent"]["scopes"][number], string> = {
  session: "Session",
  cookies: "Cookies",
  user_data: "User data",
  finance: "Finance",
} as const;

export function SiteConsole({ site }: { site: SiteRow }) {
  const [tab, setTab] = useState<"activity" | "log">("activity");
  const [rows, setRows] = useState<FeedRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const last = useRef(0);
  const box = useRef<HTMLDivElement>(null);
  const [follow, setFollow] = useState(true);

  const pull = () => api.siteFeed(site.id, last.current).then((r) => {
    setError(null);
    if (r.rows.length) { last.current = r.rows[r.rows.length - 1].id; setRows((x) => [...x, ...r.rows].slice(-600)); }
  }).catch((e: Error) => setError(e.message));
  useEffect(() => { last.current = 0; setRows([]); void pull(); }, [site.id]); // eslint-disable-line react-hooks/exhaustive-deps
  usePoll(() => void pull(), 2000);
  useEffect(() => { if (follow && box.current) box.current.scrollTop = box.current.scrollHeight; }, [rows, tab, follow]);

  const shown = rows.filter((r) => r.kind === tab);
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
        <Segmented value={tab} onChange={setTab} options={[
          { id: "activity", label: "Extension activity", icon: <IconBroadcast />, count: rows.filter((r) => r.kind === "activity").length },
          { id: "log", label: "Site logs", icon: <IconTerminal />, count: rows.filter((r) => r.kind === "log").length },
        ]} />
        <label className="row hint" style={{ gap: 8 }}><Toggle checked={follow} onChange={setFollow} label="Follow newest" />Follow newest</label>
      </div>
      {error && <ErrorNote message={error} />}
      <div className="logview" ref={box} role="log" aria-live="off" tabIndex={0} aria-label={`${tab === "activity" ? "Extension activity" : "Logs"} for ${site.host}`}>
        {shown.length === 0 ? <div className="logline"><span className="ts" /><span className="lv">—</span><span className="lg" /><span>{tab === "activity" ? "Waiting for the extension to send events from this site…" : "No log lines yet."}</span></div>
          : shown.map((r) => (
            <div key={r.id} className={`logline ${r.level}`}>
              <span className="ts">{new Date(r.ts).toLocaleTimeString([], { hour12: false })}</span>
              <span className="lv">{r.level}</span><span className="lg">{r.kind}</span><span>{r.message}</span>
            </div>
          ))}
      </div>
      <p className="hint">Held in memory per site (last 500 lines). Events themselves are stored in the database and appear on the Live event stream.</p>
    </div>
  );
}

function clock(ms: number) {
  const t = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(t / 3600)).padStart(2, "0")}:${String(Math.floor((t % 3600) / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
}

/** Subscription status and the 72-hour free-trial countdown for one website. */
export function PlanStatus({ s }: { s: SiteRow }) {
  useTick();
  const p = s.plan;
  if (!p) return null;
  const left = p.trial_ends_at ? Date.parse(p.trial_ends_at) - serverNow() : 0;
  if (p.source === "org") return <div className="plan-line"><Badge tone="green">Organisation Pro</Badge></div>;
  if (p.subscribed) return <div className="plan-line"><Badge tone="green">Pro subscribed</Badge></div>;
  if (p.trial_ends_at && left > 0) return <div className="plan-line"><Badge tone="blue">Free trial</Badge><span className="mono plan-clock" aria-label="Free trial time left">{clock(left)}</span><span className="hint">left</span></div>;
  if (p.trial_used) return <div className="plan-line"><Badge tone="red">Trial ended</Badge><span className="hint">Free plan. Pro unlocks it again.</span></div>;
  return <div className="plan-line"><Badge>Free plan</Badge><span className="hint">Trial not started</span></div>;
}

function SiteCard({ s, canManage, onOpen, onChange, selected, onSelect }: { s: SiteRow; canManage: boolean; onOpen: () => void; onChange: (b: { role?: Role; access_enabled?: boolean }) => void; selected: boolean; onSelect: (() => void) | null }) {
  const [role, setRole] = useState<Role>(s.role);
  useEffect(() => setRole(s.role), [s.role]);
  return (
    <article className={`site-card ${s.online ? "online" : ""} ${selected ? "selected" : ""}`}>
      <button type="button" className="site-open" onClick={onOpen} aria-label={`Open logs and live activity for ${s.host}`}>
        <div className="site-head">
          <span className="site-ico"><IconGlobe /></span>
          <div style={{ minWidth: 0 }}>
            <h4>{s.name || s.host}</h4>
            {s.name && <span className="hint mono">{s.host}</span>}
            <span className="hint"><Led kind={s.online ? "on" : ""} pulse={s.online} />{s.online ? "Live now" : `Last seen ${ago(s.last_seen)}`}{s.monitoring ? " · monitoring on" : ""}</span>
          </div>
        </div>
        <dl className="site-id" aria-label="Website identity">
          <div><dt>Website ID</dt><dd className="mono">{s.website_id ?? "Not generated"}</dd></div>
          <div><dt>Owner</dt><dd>{s.owner_name || "Not set"}</dd></div>
          <div><dt>Credentials</dt><dd>{s.has_credentials ? "Generated" : "Pending"}</dd></div>
        </dl>
        <div className="site-badges">
          {s.consent.scopes.length === 0
            ? <Badge tone="red" icon={<IconLock />}>No consent recorded</Badge>
            : s.consent.scopes.map((c) => <Badge key={c} tone="green" icon={c === "cookies" ? <IconCookie /> : c === "session" ? <IconBroadcast /> : c === "finance" ? <IconChart /> : <IconUser />}>{SCOPE_LABEL[c]}</Badge>)}
        </div>
        <div className="site-stats"><span><b>{num(s.event_count)}</b> events</span><span>since {dateTimeOf(s.first_seen)}</span></div>
      </button>
      <div className="site-foot">
        <PlanStatus s={s} />
        {onSelect && <Button variant={selected ? "clay" : "neu"} icon={<IconChart />} aria-pressed={selected} onClick={onSelect}>{selected ? "Showing its metrics" : "View its metrics"}</Button>}
        <label className="field" style={{ margin: 0 }}>
          <span className="label">Dashboard role</span>
          <select className="input" value={role} disabled={!canManage} aria-describedby={`rn-${s.id}`}
            onChange={(e) => {
              const next = e.target.value as Role;
              if (next === "administrator" && !window.confirm(`Give the owner of ${s.host} full administrator access?`)) return;
              setRole(next); onChange({ role: next });
            }}>
            {(Object.keys(ROLE_LABEL) as Role[]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
          </select>
          <span id={`rn-${s.id}`} className="hint">{ROLE_NOTE[role]}</span>
        </label>
        <label className="row" style={{ justifyContent: "space-between" }}>
          <span><b>Owner dashboard access</b><br /><span className="hint">{s.access_enabled ? "Enabled" : "Off. Enable it from the extension settings."}</span></span>
          <Toggle checked={s.access_enabled} disabled={!canManage || !s.access_enabled} label={`Dashboard access for ${s.host}`} onChange={(v) => onChange({ access_enabled: v })} />
        </label>
      </div>
    </article>
  );
}

export function SitesPage() {
  const { can } = useAuth();
  const toast = useToast();
  const view = useSiteView();
  const sites = useResource(api.sites, ["sites"]);
  usePoll(sites.reload, 15000);
  const [open, setOpen] = useState<string | null>(null);
  const canManage = can("users:manage");
  const list = sites.data?.sites ?? [];
  const current = list.find((s) => s.id === open) ?? null;

  async function change(s: SiteRow, b: { role?: Role; access_enabled?: boolean }) {
    try { await api.patchSite(s.id, b); toast.ok(b.role ? `${s.host} is now ${ROLE_LABEL[b.role]}.` : `Dashboard access ${b.access_enabled ? "enabled" : "revoked"} for ${s.host}.`); sites.reload(); }
    catch (e) { toast.err((e as Error).message); sites.reload(); }
  }

  return (
    <div className="page">
      <PageHead eyebrow="Connected websites" title="Sites and roles" lede="Every website an extension reports from. Assign the dashboard role its owner or developer receives, and open a site to watch its logs and live extension activity." />
      {sites.error && <ErrorNote message={sites.error} retry={sites.reload} />}
      {view.host && <Banner tone="info">Every page is limited to <span className="chip-address">{view.host}</span>. <button type="button" className="chip" onClick={() => view.set(null)}>Show all websites</button></Banner>}
      {!canManage && <Banner tone="info">Roles can only be changed by an administrator. You can still open a site to view its activity.</Banner>}
      <Card title="Live extension activity" icon={<IconBroadcast />} sub="One line per connected website, events received every 15 seconds. Click a legend item to hide a line.">
        <SiteActivityChart minutes={15} height={250} />
      </Card>
      {!sites.data ? <Skeleton rows={2} h={150} /> : list.length === 0 ? (
        <Card><Empty icon={<IconUsers />} title="No sites connected">Authorise a website and grant the consent permissions in the extension settings. It will appear here after its first heartbeat.</Empty></Card>
      ) : (
        <div className="site-grid">
          {list.map((s) => <SiteCard key={s.id} s={s} canManage={canManage} onOpen={() => setOpen(s.id)} onChange={(b) => void change(s, b)} selected={view.host === s.host} onSelect={canManage ? () => { view.set(view.host === s.host ? null : s.host); toast.ok(view.host === s.host ? "Showing all websites again." : `Every page now shows only ${s.host}.`); } : null} />)}
        </div>
      )}
      {current && <Modal wide title={`${current.host} · logs and live activity`} onClose={() => setOpen(null)}><SiteConsole site={current} /></Modal>}
    </div>
  );
}
