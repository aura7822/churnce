import { useEffect, useState, type ReactNode } from "react";
import { useAuth } from "../hooks/useAuth";
import { DbNeon } from "./DbNeon";
import { useTheme } from "../hooks/useTheme";
import {
  IconActions, IconChunks, IconEvents, IconFeedback, IconIntel, IconMoon, IconSun, IconLogout, IconMore, IconOverview, IconTerminal, IconUser,
  LogoDuotone,
} from "./icons";
import { titleCase } from "../services/format";

export interface NavDef { id: string; label: string; short: string; icon: ReactNode; pip?: number; perm?: string }

export const NAV_BASE: Omit<NavDef, "pip">[] = [
  { id: "overview", label: "Global Preview", short: "Overview", icon: <IconOverview /> },
  { id: "events", label: "Live event stream", short: "Events", icon: <IconEvents /> },
  { id: "chunks", label: "Chunk Labs & RAG", short: "Chunks", icon: <IconChunks /> },
  { id: "intelligence", label: "Diagnostics", short: "Insights", icon: <IconIntel /> },
  { id: "actions", label: "Action center", short: "Actions", icon: <IconActions /> },
  { id: "feedback", label: "Examination", short: "Outcomes", icon: <IconFeedback /> },
  { id: "logs", label: "Server logs", short: "Logs", icon: <IconTerminal />, perm: "logs:read" },
];

function ThemeButton() {
  const { mode, flip } = useTheme();
  return (
    <button className="theme-btn" onClick={flip} aria-label={`Theme: ${mode}. Click to switch.`} title={`Theme: ${mode}. Click to switch.`}>
      {mode === "dark" ? <IconMoon /> : <IconSun />}<span>{mode}</span>
    </button>
  );
}

export function Shell({ route, go: _go, nav, children }: { route: string; go: (r: string) => void; nav: NavDef[]; children: ReactNode }) {
  const { me, logout } = useAuth();
  const [more, setMore] = useState(false);
  useEffect(() => setMore(false), [route]);
  const primary = nav.slice(0, 4), rest = nav.slice(4);
  const current = nav.find((n) => n.id === route);

  return (
    <div className="app">
      <aside className="sidebar" aria-label="Primary">
        <div className="brand">
          <div className="brand-mark"><LogoDuotone /></div>
          <div><div className="brand-name">Churnce®</div><div className="brand-sub">Command Panel</div></div>
        </div>
        <nav className="nav">
          {nav.map((n) => (
            <a key={n.id} href={`#/${n.id}`} className="nav-item" aria-current={route === n.id ? "page" : undefined}>
              {n.icon}<span>{n.label}</span>{n.pip ? <span className="pip">{n.pip}</span> : null}
            </a>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="sidebar-user">
            <IconUser />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 600 }}>{me?.user.name}</div>
              <div style={{ fontSize: 12, color: "var(--sage-hi)" }}>{titleCase(me?.user.role ?? "")}</div>
            </div>
          </div>
          <button className="nav-item" onClick={logout}><IconLogout /><span>Sign out</span></button>
        </div>
      </aside>

      <div className="main">
        <div className="topbar">
          <span className="script-title">Lifecycle Marketing Agent</span>
          <span className="topbar-title">{current?.label}</span>
          <span className="spacer" />
          <ThemeButton />
          <DbNeon />
        </div>
        <main id="content">{children}</main>
      </div>

      <nav className="bottom-nav" aria-label="Primary">
        {primary.map((n) => (
          <a key={n.id} href={`#/${n.id}`} aria-current={route === n.id ? "page" : undefined}>{n.icon}<span>{n.short}</span>{n.pip ? <span className="pip">{n.pip}</span> : null}</a>
        ))}
        <button onClick={() => setMore(true)} aria-label="More sections"><IconMore /><span>More</span></button>
      </nav>
      {more && (
        <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && setMore(false)}>
          <div className="card modal" role="dialog" aria-label="More sections">
            <div className="stack">
              {rest.map((n) => <a key={n.id} href={`#/${n.id}`} className="nav-item" aria-current={route === n.id ? "page" : undefined}>{n.icon}<span>{n.label}</span>{n.pip ? <span className="pip">{n.pip}</span> : null}</a>)}
              <button className="nav-item" onClick={logout}><IconLogout /><span>Sign out</span></button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
