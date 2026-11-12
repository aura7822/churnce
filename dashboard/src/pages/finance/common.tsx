import type { ReactNode } from "react";
import type { Verdict } from "../../types";
import type { Tone } from "../../components/ui";

export { kes } from "../../utils/format";
export const pc = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${v}%`);
export const ratioPct = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${Math.round(v * 100)}%`);
export const x2 = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${v.toFixed(2)}×`);
export const days1 = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${v.toFixed(1)} d`);
export const delta = (v: number | null | undefined): ReactNode => (v === null || v === undefined ? null : <span className={v >= 0 ? "delta up" : "delta down"}>{v >= 0 ? "▲" : "▼"} {Math.abs(v)}%</span>);
export const day = (iso: string) => new Date(iso.length <= 10 ? iso + "T00:00:00" : iso).toLocaleDateString([], { day: "numeric", month: "short" });
export const VERDICT_TONE: Record<Verdict, Tone> = { pass: "green", warn: "amber", fail: "red" };
export const VERDICT_LABEL: Record<Verdict, string> = { pass: "Pass", warn: "Watch", fail: "Fail" };
export const hms = (secs: number) => {
  const s = Math.max(0, Math.floor(secs));
  return `${String(Math.floor(s / 3600)).padStart(2, "0")}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
};
export const BANK_COLORS = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)", "var(--c6)"];

export function Section({ id, title, lede, children, actions }: { id?: string; title: string; lede?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="fin-section" id={id} aria-label={title}>
      <header className="fin-section-head"><div><h3>{title}</h3>{lede && <p className="hint">{lede}</p>}</div>{actions}</header>
      {children}
    </section>
  );
}
