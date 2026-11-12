/** Pure helpers for the 72-hour free trial. The backend owns the clock; these only present what it reported. */
export interface TrialEntry { ends_at: string | null; used: boolean }
export interface PremiumState { active: boolean; source: "org" | "pro" | "trial" | null; trial_ends_at: string | null; seconds_left: number }
export type TrialPhase = "none" | "active" | "ended" | "org";
export interface TrialView { phase: TrialPhase; msLeft: number }

/** `org` = premium through the organisation plan, `active` = trial running, `ended` = trial used (button stays disabled for that website ID). */
export function trialView(entry: TrialEntry | undefined, premium: PremiumState | undefined, now = Date.now()): TrialView {
  if (premium?.active && (premium.source === "org" || premium.source === "pro")) return { phase: "org", msLeft: 0 };
  const endsRaw = premium?.trial_ends_at ?? entry?.ends_at ?? null;
  const ends = endsRaw ? Date.parse(endsRaw) : NaN;
  if (Number.isFinite(ends)) return ends > now ? { phase: "active", msLeft: ends - now } : { phase: "ended", msLeft: 0 };
  return entry?.used ? { phase: "ended", msLeft: 0 } : { phase: "none", msLeft: 0 };
}

/** 259200000 ms -> "72:00:00". */
export function formatCountdown(ms: number): string {
  const t = Math.max(0, Math.floor(ms / 1000));
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(Math.floor(t / 3600))}:${p(Math.floor((t % 3600) / 60))}:${p(t % 60)}`;
}
