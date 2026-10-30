export const titleCase = (s: string) => s.replace(/[_:]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export function timeOf(iso?: string | null): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "–" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}
export function dateTimeOf(iso?: string | null): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "–" : d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
}
export function ago(iso?: string | null, now = Date.now()): string {
  if (!iso) return "–";
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}
export const pct = (v: number | null | undefined, digits = 0) => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(digits)}%`);
export const ms = (v: number | null | undefined) => (v === null || v === undefined ? "–" : v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${Math.round(v)}ms`);
export const num = (v: number | null | undefined) => (v === null || v === undefined ? "–" : v.toLocaleString());

/** Remaining review seconds from a backend deadline, using the backend-synchronised clock. */
export function remainingSeconds(deadlineIso: string | null, nowMs: number): number | null {
  if (!deadlineIso) return null;
  return Math.max(0, (Date.parse(deadlineIso) - nowMs) / 1000);
}
