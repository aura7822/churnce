import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { useRipple } from "./hooks/useRipple";
import { useAuth } from "./hooks/useAuth";
import { useResource } from "./hooks/useLive";
import { useSiteView } from "./services/siteView";
import { AnalyserPage } from "./pages/AnalyserPage";
import { useRoute } from "./hooks/useRoute";
import { api } from "./services/api";
import { NAV_BASE, Shell, type NavDef } from "./components/Shell";
import { Button, Skeleton } from "./components/ui";
import { IconLock, IconPipeline, IconRag, IconTimer, IconIntel } from "./components/icons";
import { Boot } from "./components/Boot";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { LogsPage } from "./pages/LogsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { EventsPage } from "./pages/EventsPage";
import { ChunksPage } from "./pages/ChunksPage";
import { FinancePage } from "./pages/FinancePage";
import { ActionsPage } from "./pages/ActionsPage";
import { EmailsPage } from "./pages/EmailsPage";
import { Forbidden } from "./components/Forbidden";
import type { Role } from "./types";
import { ROLE_LABEL } from "./services/format";
import { SitesPage } from "./pages/SitesPage";
import { DocsPage } from "./pages/DocsPage";

const DEMO_ACCOUNTS: [string, string][] = [
  ["admin@churnce.demo", ROLE_LABEL.administrator],
  ["analyst@churnce.demo", ROLE_LABEL.data_analyst],
  ["engineer@churnce.demo", ROLE_LABEL.developer],
  ["marketing@churnce.demo", ROLE_LABEL.website_owner],
];
const SITE_ROLES: Role[] = ["data_analyst", "developer", "website_owner"];

function Login({ onStart, onFail }: { onStart: () => void; onFail: () => void }) {
  const { login, loginSite } = useAuth();
  const [tab, setTab] = useState<"account" | "website">("account");
  const [websiteId, setWebsiteId] = useState(() => (/[?&]site=([\w-]+)/.exec(location.hash)?.[1] ?? "").toUpperCase());
  const [siteRole, setSiteRole] = useState<Role>("website_owner");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    onStart(); // armed before the session exists so the loading screen is the first thing shown after sign-in
    try { if (tab === "website") await loginSite(websiteId, password, siteRole); else await login(email.trim(), password); } catch (err) { onFail(); setError((err as Error).message); } finally { setBusy(false); }
  }

  return (
    <div className="login">
      <div className="login-card">
        <section className="login-hero">
          <div className="row" style={{ gap: 12 }}>
            <div className="brand-mark"><IconPipeline /></div>
            <div className="brand-name">Churnce</div>
          </div>
          <div className="script-title">Lifecycle Marketing Agent</div>
          <h1>Understand the friction. <em>Bring customers back.</em></h1>
          <ul className="feature-list">
            <li><IconTimer /><span>Timed review gate: 30 seconds to inject, edit, extend or discard before evidence enters the knowledge base.</span></li>
            <li><IconRag /><span>Retrieval you can inspect: every passage, score and access decision.</span></li>
            <li><IconIntel /><span>Evidence-linked findings. Actions need approval before anything leaves the building.</span></li>
          </ul>
        </section>
        <form className="login-form" onSubmit={submit} aria-label="Sign in">
          <div>
            <div className="eyebrow">Control room</div>
            <h2 style={{ fontSize: 28, marginTop: 6 }}>Sign in</h2>
          </div>
          <div className="tabs" role="tablist" aria-label="Sign-in method">
            <button type="button" role="tab" aria-selected={tab === "account"} className={tab === "account" ? "on" : ""} onClick={() => { setTab("account"); setError(null); }}>Account</button>
            <button type="button" role="tab" aria-selected={tab === "website"} className={tab === "website" ? "on" : ""} onClick={() => { setTab("website"); setError(null); }}>Website ID</button>
          </div>
          {tab === "account" ? (
            <div className="field">
              <label htmlFor="email">Email</label>
              <input id="email" className="input" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
          ) : (
            <>
              <div className="field">
                <label htmlFor="wid">Website ID</label>
                <input id="wid" className="input mono" autoComplete="username" placeholder="WS-ABC123" required value={websiteId} onChange={(e) => setWebsiteId(e.target.value.toUpperCase())} />
              </div>
              <div className="field">
                <label htmlFor="srole">Role</label>
                <select id="srole" className="input" value={siteRole} onChange={(e) => setSiteRole(e.target.value as Role)}>
                  {SITE_ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                </select>
                <span className="hint">Admin needs a named account. A website-ID session only sees that website.</span>
              </div>
            </>
          )}
          <div className="field">
            <label htmlFor="password">Password</label>
            <input id="password" className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          {error && <div className="banner" role="alert">{error}</div>}
          <Button variant="clay" busy={busy} icon={<IconLock />} type="submit">Enter control room</Button>
          {tab === "account" && <div>
            <div className="label" style={{ marginBottom: 8 }}>Local demo accounts</div>
            <div className="demo-accounts">
              {DEMO_ACCOUNTS.map(([addr, label]) => (
                <button type="button" key={addr} className="chip" onClick={() => { setEmail(addr); setPassword("Churnce!2026"); }}>{label}</button>
              ))}
            </div>
            <p className="hint" style={{ marginTop: 8 }}>Only present when the backend runs with SEED_DEMO=true.</p>
          </div>}
        </form>
      </div>
    </div>
  );
}

function Authed() {
  const { me, can } = useAuth();
  const [route] = useRoute("overview");
  const view = useSiteView();
  const metrics = useResource(api.metrics, ["metrics"], [view.host]);
  const m = metrics.data;

  const scoped = !!me?.scope;
  // Sections a role cannot open stay in the menu, marked with a lock, and open the custom 403 page.
  const allowed = (id: string, perm?: string) => {
    if (scoped && (id === "logs" || id === "sites")) return false; // administrator-only
    if (scoped && id === "emails") return true; // every website role may open it; only Website Owner can act
    return !perm || can(perm);
  };
  const nav = useMemo<NavDef[]>(() => NAV_BASE.map((n) => {
    const pip = n.id === "chunks" ? m?.chunks_pending_review : n.id === "actions" ? m?.actions_awaiting_approval : 0;
    return { ...n, pip: pip || undefined, locked: !allowed(n.id, n.perm) };
  }), [m, me]); // eslint-disable-line react-hooks/exhaustive-deps
  const def = NAV_BASE.find((n) => n.id === route);

  const page = (() => {
    if (def && !allowed(def.id, def.perm)) return <Forbidden section={def.label} />;
    switch (route) {
      case "events": return <EventsPage />;
      case "chunks": return <ChunksPage />;
      case "rag": case "governance": return <ChunksPage />;
      case "finance": return <FinancePage />;
      case "actions": return <ActionsPage />;
      case "analyser": return <AnalyserPage />;
      case "emails": return <EmailsPage />;
      case "sites": return <SitesPage />;
      case "docs": return <DocsPage />;
      case "logs": return <LogsPage />;
      default: return <OverviewPage metrics={metrics} />;
    }
  })();

  if (!me) return null;
  return <Shell route={route} nav={nav}><ErrorBoundary resetKey={`${route}|${view.host ?? ""}`}><div key={view.host ?? "all"} style={{ display: "contents" }}>{page}</div></ErrorBoundary></Shell>;
}

/** `#/access?code=…` is the single-use sign-in link a site owner receives from the extension. */
function useAccessLink(onStart: () => void, onFail: () => void) {
  const { loginWithToken } = useAuth();
  const [state, setState] = useState<"idle" | "working" | "error">(() => (/^#\/access\?/.test(location.hash) ? "working" : "idle"));
  const [message, setMessage] = useState("");
  useEffect(() => {
    const m = /^#\/access\?(?:.*&)?code=([^&]+)/.exec(location.hash);
    if (!m) return;
    const code = decodeURIComponent(m[1]);
    history.replaceState(null, "", location.pathname + location.search + "#/overview"); // the code never stays in the address bar or history
    onStart();
    api.redeemSiteAccess(code).then((r) => loginWithToken(r.token)).then(() => setState("idle"))
      .catch((e: Error) => { onFail(); setMessage(e.message); setState("error"); });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return { state, message, dismiss: () => setState("idle") };
}

export function App() {
  useRipple();
  const { me, loading } = useAuth();
  const [boot, setBoot] = useState(false);
  const start = useCallback(() => setBoot(true), []);
  const fail = useCallback(() => setBoot(false), []);
  const done = useCallback(() => setBoot(false), []);
  const access = useAccessLink(start, fail);
  if (loading) return <div className="login"><div className="card" style={{ width: 320 }}><Skeleton rows={3} /></div></div>;
  if (access.state === "working" && !me) return <div className="login"><div className="card" style={{ width: 340 }}><h3>Signing you in…</h3><Skeleton rows={2} /></div></div>;
  if (access.state === "error" && !me) return <div className="login"><div className="card" style={{ width: 380 }}><h3>Access link problem</h3><div className="banner" role="alert">{access.message}</div><p className="hint">Ask the person who runs the extension to enable access again. Links work once and expire after 24 hours.</p><Button variant="clay" onClick={access.dismiss}>Go to sign in</Button></div></div>;
  if (me && boot) return <Boot onDone={done} />;
  return me ? <Authed /> : <Login onStart={start} onFail={fail} />;
}

