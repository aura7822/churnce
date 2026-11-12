import { IconCode, IconX } from "./icons";
import { CookieNotice } from "./CookieNotice";
import { DocsNudge } from "./DocsNudge";
import { TopProgress } from "./TopProgress";
import { useSiteView } from "../services/siteView";
import { useEffect, useState, type ReactNode } from "react";
import { useAuth } from "../hooks/useAuth";
import { useTheme } from "../hooks/useTheme";
import {
  IconActions, IconChunks, IconEvents, IconMail, IconMoon, IconSun, IconLogout, IconMore, IconOverview, IconPipeline, IconTerminal, IconUser, IconGlobe, IconDocs, IconCoins, IconLock,
} from "./icons";
import { roleLabel } from "../services/format";

export interface NavDef { id: string; label: string; short: string; icon: ReactNode; pip?: number; perm?: string; premium?: boolean; lockable?: boolean; locked?: boolean }

export const NAV_BASE: Omit<NavDef, "pip">[] = [
  { id: "overview", label: "System overview", short: "Overview", icon: <IconOverview /> },
  { id: "events", label: "Live event stream", short: "Events", icon: <IconEvents /> },
  { id: "chunks", label: "Chunk lab & RAG", short: "Chunks", icon: <IconChunks /> },
  { id: "finance", label: "Finance & liquidity", short: "Finance", icon: <IconCoins />, premium: true },
  { id: "actions", label: "Action center", short: "Actions", icon: <IconActions /> },
  { id: "analyser", label: "Codebase analyser", short: "Code", icon: <IconCode />, premium: true },
  { id: "emails", label: "Customer emails", short: "Emails", icon: <IconMail />, perm: "emails:approve", lockable: true },
  { id: "sites", label: "Sites & roles", short: "Sites", icon: <IconGlobe />, perm: "users:manage", lockable: true },
  { id: "logs", label: "Backend logs", short: "Logs", icon: <IconTerminal />, perm: "logs:read", lockable: true },
];

function ThemeButton() {
  const { mode, flip } = useTheme();
  const next = mode === "dark" ? "light" : "dark";
  return (
    <button type="button" className="theme-btn" onClick={flip} aria-label={`Switch to ${next} mode`} title={`Switch to ${next} mode`}>
      {mode === "dark" ? <IconSun /> : <IconMoon />}
    </button>
  );
}

export function Shell({ route, nav, children }: { route: string; nav: NavDef[]; children: ReactNode }) {
  const { me, logout } = useAuth();
  const view = useSiteView();
  const [more, setMore] = useState(false);
  useEffect(() => setMore(false), [route]);
  const primary = nav.slice(0, 4), rest = nav.slice(4);
  const current = route === "docs" ? { label: "Documentation" } : nav.find((n) => n.id === route);

  return (
    <div className="app">
      <aside className="sidebar" aria-label="Primary">
        <div className="brand">
          <div className="brand-mark"><IconPipeline /></div>
          <div><div className="brand-name">Churnce</div><div className="brand-sub">Control room</div></div>
        </div>
        <nav className="nav">
          {nav.map((n) => (
            <a key={n.id} href={`#/${n.id}`} className="nav-item" aria-current={route === n.id ? "page" : undefined}>
              {n.icon}<span>{n.label}</span>{n.premium ? <span className="tag-premium">PRO</span> : null}{n.locked ? <IconLock className="nav-lock" aria-label="Restricted" /> : null}{n.pip ? <span className="pip">{n.pip}</span> : null}
            </a>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="sidebar-user">
            <IconUser />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 600 }}>{me?.user.name}</div>
              <div style={{ fontSize: 12, color: "var(--sage-hi)" }}>{roleLabel(me?.user.role ?? "")}</div>
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
          {view.host && !me?.scope ? <span className="chip-address view-chip" title="Every page shows only this website's captured data"><i className="dot" />Viewing<b>{view.host}</b><button type="button" className="chip-x" aria-label="Show all websites" onClick={() => view.set(null)}><IconX /></button></span> : null}
          {me?.scope ? <span className="chip-address" title={`Website-ID session: everything on screen is limited to ${me.scope.site_host}`}><i className="dot" />{me.scope.website_id}<b>{me.scope.name || me.scope.site_host}</b></span> : null}
          <ThemeButton />
          <a href="#/docs" className="docs-btn" aria-current={route === "docs" ? "page" : undefined}><IconDocs /><span>View documentation</span></a>
          <DocsNudge route={route} />
        </div>
        <TopProgress />
        <main id="content">{children}</main>
      </div>

      <CookieNotice />
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
