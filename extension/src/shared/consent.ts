/**
 * Explicit, scoped consent the website owner grants before the extension monitors anything.
 *  - session:   a session identifier is created per visit and activity is tied to it (cookie VALUES are never read).
 *  - cookies:   only counts and flags (total, session, secure, httpOnly) are summarised. Optional.
 *  - finance:   Premium. Transaction type, status, amount, currency, method category, failure reason, optional bank label and due date, for the liquidity engine.
 *  - user_data: non-personal usage data: routes, element categories, timings, outcomes. Never form values, keystrokes or identity.
 */
export type Scope = "session" | "cookies" | "user_data" | "finance";
export const REQUIRED_SCOPES: Scope[] = ["session", "user_data"];
export interface Consent { scopes: Scope[]; acceptedAt: string; extensionVersion: string }

export const SCOPE_COPY: Record<Scope, { title: string; reads: string; never: string; required: boolean }> = {
  session: { title: "Session", reads: "A random per-visit session id and the order of events inside it, so friction can be seen as a journey.", never: "Login state, tokens or any cookie value.", required: true },
  user_data: { title: "Usage data", reads: "Page routes, element categories, timings and outcomes (for example 'checkout button clicked 4 times').", never: "Keystrokes, form values, names, emails, payment details or any personal or sensitive information.", required: true },
  finance: { title: "Transactions (Premium)", reads: "Transaction type, status, amount, currency, payment-method category and failure reason, plus the site's own opaque reference.", never: "Card or account numbers, payer names, emails, addresses or any payer identity.", required: false },
  cookies: { title: "Cookies", reads: "Counts and flags only: how many cookies, how many are session, secure or HttpOnly cookies.", never: "Cookie names and values.", required: false },
};

/** Monitoring needs every required scope. Cookies stay optional. */
export function monitoringAllowed(c: Consent | null | undefined): boolean {
  return !!c && REQUIRED_SCOPES.every((s) => c.scopes.includes(s));
}

export interface CookieSummary { total: number; session_cookies: number; secure: number; http_only: number; session_present: boolean }

/** Reduces cookies to counts and flags. Names and values are dropped here, before anything leaves the browser. */
export function summariseCookies(cookies: { session?: boolean; secure?: boolean; httpOnly?: boolean }[]): CookieSummary {
  const n = (f: (c: (typeof cookies)[number]) => boolean | undefined) => Math.min(5000, cookies.filter((c) => !!f(c)).length);
  return { total: Math.min(5000, cookies.length), session_cookies: n((c) => c.session), secure: n((c) => c.secure), http_only: n((c) => c.httpOnly), session_present: cookies.some((c) => c.session) };
}

/** `https://app.example.com:8443` -> `app.example.com` (what the backend registers as the site host). */
export function hostOf(origin: string): string | null {
  try { return new URL(origin).hostname.toLowerCase(); } catch { return null; }
}

// ── Finance events (Premium) ──────────────────────────────────────────────────
export const TXN_TYPES = ["payment", "subscription", "refund", "chargeback", "fee", "payout", "invoice", "bill", "inventory_in", "inventory_out"] as const;
export const TXN_STATUS = ["success", "failed", "pending"] as const;
export const TXN_METHODS = ["card", "mobile_money", "bank_transfer", "wallet", "cash_on_delivery", "other"] as const;
export const TXN_REASONS = ["insufficient_funds", "card_declined", "expired_card", "fraud_check", "timeout", "network", "issuer_unavailable", "processing_error", "cancelled_by_user", "other"] as const;
export interface OutTxn { event_id: string; txn_type: (typeof TXN_TYPES)[number]; status: (typeof TXN_STATUS)[number]; amount: number; currency: string; method: (typeof TXN_METHODS)[number]; reason?: (typeof TXN_REASONS)[number]; occurred_at: string; session_ref?: string; bank?: string; due_at?: string }

const pick = <T extends string>(list: readonly T[], v: unknown, fallback: T): T => (typeof v === "string" && (list as readonly string[]).includes(v) ? (v as T) : fallback);

/** Whitelists a page-supplied transaction. Anything else the page sends (names, card numbers, emails) is dropped, never forwarded. */
export function sanitiseTxn(d: Record<string, unknown>, now = new Date()): OutTxn | null {
  const amount = typeof d.amount === "number" ? d.amount : NaN;
  if (!Number.isFinite(amount) || amount < 0 || amount > 1_000_000_000) return null;
  const currency = typeof d.currency === "string" && /^[A-Za-z]{3}$/.test(d.currency) ? d.currency.toUpperCase() : null;
  if (!currency || typeof d.txn_type !== "string" || !(TXN_TYPES as readonly string[]).includes(d.txn_type)) return null;
  if (typeof d.status !== "string" || !(TXN_STATUS as readonly string[]).includes(d.status)) return null;
  const ref = typeof d.event_id === "string" && /^[\w.:-]{3,60}$/.test(d.event_id) ? d.event_id : null; // an id shaped like a card number is still just digits: reject long digit runs
  if (ref && /\d{13,}/.test(ref)) return null;
  const status = d.status as OutTxn["status"];
  // Optional settlement bank label (letters, digits, space, & and - only) and optional due date for invoices and bills.
  const bankRaw = typeof d.bank === "string" ? d.bank.trim() : "";
  const bank = bankRaw && bankRaw.length <= 40 && /^[A-Za-z0-9 &-]+$/.test(bankRaw) && !/\d{6,}/.test(bankRaw) ? bankRaw : undefined;
  const dueMs = typeof d.due_at === "string" ? Date.parse(d.due_at) : NaN;
  const due_at = Number.isFinite(dueMs) ? new Date(dueMs).toISOString() : undefined;
  return {
    event_id: ref ?? `txn_${Math.random().toString(36).slice(2, 12)}`, txn_type: d.txn_type as OutTxn["txn_type"], status,
    amount: Math.round(amount * 100) / 100, currency, method: pick(TXN_METHODS, d.method, "other"),
    ...(status === "failed" ? { reason: pick(TXN_REASONS, d.reason, "other") } : {}), occurred_at: now.toISOString(),
    ...(bank ? { bank } : {}), ...(due_at ? { due_at } : {}),
  };
}
