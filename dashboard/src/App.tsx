import { useCallback, useMemo, useState, type FormEvent } from "react";
import { useRipple } from "./hooks/useRipple";
import { useAuth } from "./hooks/useAuth";
import { useResource } from "./hooks/useLive";
import { useRoute } from "./hooks/useRoute";
import { api } from "./services/api";
import { NAV_BASE, Shell, type NavDef } from "./components/Shell";
import { Button, Skeleton } from "./components/ui";
import { IconEye, IconLock, IconRag, IconTimer, IconIntel, IconRedact, LogoDuotone } from "./components/icons";
import { Boot } from "./components/Boot";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { LogsPage } from "./pages/LogsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { EventsPage } from "./pages/EventsPage";
import { ChunksPage } from "./pages/ChunksPage";
import { IntelligencePage } from "./pages/IntelligencePage";
import { ActionsPage } from "./pages/ActionsPage";
import { FeedbackPage } from "./pages/FeedbackPage";

const DEMO_ACCOUNTS: [string, string][] = [
  ["admin@churnce.demo", "Administrator"],
  ["engineer@churnce.demo", "Engineer"],
  ["marketing@churnce.demo", "Marketing"],
  ["analyst@churnce.demo", "Analyst"],
  ["reviewer@churnce.demo", "Read-only"],
];

export function Login({ onStart, onFail }: { onStart: () => void; onFail: () => void }) {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    onStart(); // armed before the session exists so the loading screen is the first thing shown after sign-in
    try { await login(email.trim(), password); } catch (err) { onFail(); setError((err as Error).message); } finally { setBusy(false); }
  }

  return (
    <div className="login">
      <div className="login-card">
        <section className="login-hero">
          <div className="row" style={{ gap: 12 }}>
            <div className="brand-mark"><LogoDuotone /></div>
            <div className="brand-name">Churnce®</div>
          </div>
          <div className="script-title">The Lifecycle Marketing Agent</div>
          <h1>Try another Chance <em>Bring customers back.</em></h1>
          <ul className="feature-list">
            <li><IconTimer /><span>Timed review gate: 30 seconds to inject, edit, extend or discard before evidence enters the knowledge base.</span></li>
            <li><IconRag /><span>Retrieval you can inspect: every passage, score and access decision.</span></li>
            <li><IconIntel /><span>Evidence-linked diagnoses. Actions need approval before anything leaves the building.</span></li>
          </ul>
        </section>
        <form className="login-form" onSubmit={submit} aria-label="Sign in">
          <div>
            <div className="eyebrow">Command Panel</div>
            <h2 style={{ fontSize: 28, marginTop: 6 }}>Sign in</h2>
          </div>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input id="email" className="input" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <div className="password-wrap">
              <input id="password" className="input password-input" type={showPassword ? "text" : "password"} autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
              <button
                type="button"
                className="password-toggle"
                aria-label={showPassword ? "Toggle password visibility" : "Toggle password visibility"}
                title={showPassword ? "Hide password" : "Show password"}
                onClick={() => setShowPassword((value) => !value)}
              >
                {showPassword ? <IconRedact /> : <IconEye />}
              </button>
            </div>
          </div>
          {error && <div className="banner" role="alert">{error}</div>}
          <Button variant="clay" busy={busy} icon={<IconLock />} type="submit">Enter control room</Button>
          <div>
            <div className="label" style={{ marginBottom: 8 }}>Local demo accounts</div>
            <div className="demo-accounts">
              {DEMO_ACCOUNTS.map(([addr, label]) => (
                <button type="button" key={addr} className="chip" onClick={() => { setEmail(addr); setPassword("Churnce!2026"); }}>{label}</button>
              ))}
            </div>
            <p className="hint" style={{ marginTop: 8 }}>Only present when the backend runs with SEED_DEMO=true.</p>
          </div>
        </form>
      </div>
    </div>
  );
}

function Authed() {
  const { me, can } = useAuth();
  const [route, go] = useRoute("overview");
  const metrics = useResource(api.metrics, ["metrics"]);
  const m = metrics.data;

  const nav = useMemo<NavDef[]>(() => NAV_BASE.filter((n) => !n.perm || can(n.perm)).map((n) => {
    const pip = n.id === "chunks" ? m?.chunks_pending_review : n.id === "actions" ? m?.actions_awaiting_approval : n.id === "intelligence" ? m?.incidents_active : 0;
    return { ...n, pip: pip || undefined };
  }), [m, me]); // eslint-disable-line react-hooks/exhaustive-deps

  const page = (() => {
    switch (route) {
      case "events": return <EventsPage />;
      case "chunks": return <ChunksPage />;
      case "rag": case "governance": return <ChunksPage />;
      case "intelligence": return <IntelligencePage />;
      case "actions": return <ActionsPage />;
      case "feedback": return <FeedbackPage />;
      case "logs": return can("logs:read") ? <LogsPage /> : <OverviewPage metrics={metrics} />;
      default: return <OverviewPage metrics={metrics} />;
    }
  })();

  if (!me) return null;
  return <Shell route={route} go={go} nav={nav}><ErrorBoundary resetKey={route}>{page}</ErrorBoundary></Shell>;
}

export function App() {
  useRipple();
  const { me, loading } = useAuth();
  const [boot, setBoot] = useState(false);
  const start = useCallback(() => setBoot(true), []);
  const fail = useCallback(() => setBoot(false), []);
  const done = useCallback(() => setBoot(false), []);
  if (loading) return <div className="login"><div className="card" style={{ width: 420 }}><Skeleton rows={3} /></div></div>;
  if (me && boot) return <Boot onDone={done} />;
  return me ? <Authed /> : <Login onStart={start} onFail={fail} />;
}

