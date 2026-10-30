import { useEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { IconCheck, IconInfo, IconSpinner, IconWarn, IconX } from "./icons";
import type { PolicyCheck } from "../types";
import { titleCase } from "../services/format";

export type Tone = "teal" | "amber" | "blue" | "red" | "green" | "violet" | "";

export function Badge({ tone = "", icon, children, title }: { tone?: Tone; icon?: ReactNode; children: ReactNode; title?: string }) {
  return <span className={`badge ${tone}`} title={title}>{icon}{children}</span>;
}

export function SimBadge({ simulated }: { simulated: boolean }) {
  return simulated ? <Badge tone="amber" title="Produced by scripted demo journeys, not real customers">Simulated</Badge> : null;
}

export function Led({ kind = "", pulse = false, label }: { kind?: "on" | "warn" | "bad" | "info" | ""; pulse?: boolean; label?: string }) {
  return <span className={`led ${kind} ${pulse ? "pulse" : ""}`} role="img" aria-label={label ?? kind ?? "status"} />;
}

export function Button({
  variant = "neu", busy, icon, children, className = "", ...rest
}: { variant?: "clay" | "clay-amber" | "clay-rose" | "neu" | "ghost" | "brutal" | "brutal-go" | "brutal-stop"; busy?: boolean; icon?: ReactNode } & ButtonHTMLAttributes<HTMLButtonElement>) {
  const cls = {
    clay: "btn btn-clay", "clay-amber": "btn btn-clay amber", "clay-rose": "btn btn-clay rose", neu: "btn btn-neu", ghost: "btn btn-ghost",
    brutal: "btn-brutal", "brutal-go": "btn-brutal go", "brutal-stop": "btn-brutal stop",
  }[variant];
  return (
    <button {...rest} disabled={rest.disabled || busy} className={`${cls} ${busy ? "spin" : ""} ${className}`}>
      {busy ? <IconSpinner className="spinner" /> : icon}
      {children}
    </button>
  );
}

export function Stat({ label, value, note, icon, tone = "" }: { label: string; value: ReactNode; note?: ReactNode; icon: ReactNode; tone?: "amber" | "blue" | "violet" | "rose" | "" }) {
  return (
    <div className={`clay ${tone}`}>
      <div className="k-label">{icon}{label}</div>
      <div className="k-value">{value}</div>
      {note && <div className="k-note">{note}</div>}
    </div>
  );
}

export function Card({ title, icon, sub, actions, children, className = "" }: { title?: ReactNode; icon?: ReactNode; sub?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <div className="card-head">
          <div>
            <h3>{icon}{title}</h3>
            {sub && <p className="card-sub">{sub}</p>}
          </div>
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function PageHead({ eyebrow, title, lede, actions }: { eyebrow: string; title: string; lede?: string; actions?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        {lede && <p>{lede}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </header>
  );
}

export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return <div className="empty">{icon}<h4>{title}</h4>{children && <p>{children}</p>}</div>;
}

export function Skeleton({ rows = 3, h = 56 }: { rows?: number; h?: number }) {
  return <div className="stack" aria-busy="true">{Array.from({ length: rows }, (_, i) => <div key={i} className="skel" style={{ height: h }} />)}</div>;
}

export function ErrorNote({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="banner" role="alert"><IconWarn /><span>{message}</span>{retry && <Button variant="ghost" className="btn-sm" onClick={retry}>Retry</Button>}</div>
  );
}

export function Banner({ children, tone = "warn", icon }: { children: ReactNode; tone?: "warn" | "info"; icon?: ReactNode }) {
  return <div className={`banner ${tone === "info" ? "info" : ""}`}>{icon ?? (tone === "info" ? <IconInfo /> : <IconWarn />)}<span>{children}</span></div>;
}

export function Meter({ value, tone = "", label }: { value: number; tone?: "amber" | "blue" | "red" | ""; label?: string }) {
  const w = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return <div className={`meter ${tone}`} role="meter" aria-valuenow={w} aria-valuemin={0} aria-valuemax={100} aria-label={label}><i style={{ width: `${w}%` }} /></div>;
}

export function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} className="toggle" disabled={disabled} onClick={() => onChange(!checked)} />;
}

export function Segmented<T extends string>({ value, options, onChange }: { value: T; options: { id: T; label: string; count?: number; icon?: ReactNode }[]; onChange: (v: T) => void }) {
  return (
    <div className="seg" role="tablist">
      {options.map((o) => (
        <button key={o.id} role="tab" aria-selected={o.id === value} onClick={() => onChange(o.id)}>
          {o.icon}{o.label}{o.count ? <span className="count">{o.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", key);
    return () => { window.removeEventListener("keydown", key); prev?.focus(); };
  }, [onClose]);
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="card modal" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref}>
        <div className="card-head"><h3>{title}</h3><Button variant="ghost" className="btn-sm" onClick={onClose} aria-label="Close"><IconX /></Button></div>
        {children}
      </div>
    </div>
  );
}

export function PolicyChecks({ checks }: { checks: PolicyCheck[] | undefined }) {
  if (!checks?.length) return null;
  return (
    <div className="stack" style={{ gap: 7 }}>
      {checks.map((c) => (
        <div key={c.name} className={`check ${c.passed ? "pass" : "fail"}`}>
          {c.passed ? <IconCheck aria-label="passed" /> : <IconX aria-label="failed" />}
          <span>{titleCase(c.name)}<small>{c.detail}</small></span>
        </div>
      ))}
    </div>
  );
}

export function SeverityBadge({ s }: { s: string }) {
  const tone: Tone = s === "critical" ? "red" : s === "high" ? "amber" : s === "medium" ? "blue" : "";
  return <Badge tone={tone}>{titleCase(s)}</Badge>;
}

const STATE_TONE: Record<string, Tone> = {
  PENDING_REVIEW: "amber", APPROVED: "blue", VALIDATING: "blue", QUEUED_FOR_INGESTION: "blue", EMBEDDING: "violet", INDEXED: "teal",
  AVAILABLE_FOR_RETRIEVAL: "green", REJECTED: "red", DISCARDED: "",
  AWAITING_APPROVAL: "amber", COMPLETED: "green", FAILED: "red", DECLINED: "", EXECUTION: "violet", OUTCOME_EVALUATION: "teal",
  open: "amber", analysis_queued: "blue", analyzing: "violet", analyzed: "teal", action_pending: "amber", resolved: "green", regression: "red",
  draft: "amber", approved: "blue", sent_simulated: "green", blocked: "red", rejected: "red",
  verified: "green", pending_verification: "amber",
};
export function StateBadge({ state }: { state: string }) {
  const tone = STATE_TONE[state] ?? "";
  const icon = tone === "green" ? <IconCheck /> : tone === "red" ? <IconX /> : undefined;
  return <Badge tone={tone} icon={icon}>{titleCase(state.toLowerCase())}</Badge>;
}

export function Dial({ seconds, total, held, idle, label }: { seconds: number | null; total: number; held?: boolean; idle?: boolean; label?: string }) {
  const s = seconds ?? 0;
  const p = idle || seconds === null ? 0 : Math.max(0, Math.min(1, s / Math.max(1, total)));
  const cls = idle || seconds === null ? "idle" : held ? "hold" : s <= 3 ? "urgent" : "";
  return (
    <div className={`dial ${cls}`} style={{ ["--p" as string]: p }} role="timer" aria-label={label ?? (seconds === null ? "Waiting for operator" : `${Math.ceil(s)} seconds until automatic ingestion`)}>
      <div className="dial-face">
        <div className="dial-read">
          <b>{seconds === null ? "∞" : Math.ceil(s)}</b>
          <small>{seconds === null ? "MANUAL" : held ? "HELD" : "SEC"}</small>
        </div>
      </div>
    </div>
  );
}

export const OK_ICON = <IconCheck />;
