/**
 * Content script: injected ONLY into origins the operator authorised (see background/index.ts).
 * It reads structure and outcomes, never values: no keystrokes, no input contents (except an
 * explicitly designated search box, redacted), no page text, no cookies.
 *
 * Applications can emit precise events themselves, which is preferred over guessing:
 *   window.dispatchEvent(new CustomEvent("churnce:event", { detail: JSON.stringify({ type: "interaction_failure", outcome: "timeout", ... }) }))
 * Premium finance events (amount, status, method category; never card numbers or payer identity):
 *   window.dispatchEvent(new CustomEvent("churnce:transaction", { detail: JSON.stringify({ txn_type: "payment", status: "failed", amount: 6400, currency: "KES", method: "mobile_money", bank: "M-Pesa", reason: "timeout", event_id: "order_1042" }) }))
 *   txn_type: payment | subscription | refund | chargeback | fee | payout | invoice | bill | inventory_in | inventory_out;
 *   optional bank (<= 40 chars, letters/digits/space/&/-) and due_at (ISO date) for invoices and bills. Anything else is dropped.
 * Markup hints: data-churnce-action="primary_action" on buttons, data-churnce-error="CODE" on error banners,
 * data-churnce-search on the search input, and document.documentElement.dataset.churnceWorkflow = "checkout" while a workflow is in progress.
 */
import type { EventType, OutEvent } from "../shared/config";
import { NEVER_READ, redact, safeRoute } from "../shared/privacy";
import { sanitiseTxn } from "../shared/consent";

const ALLOWED: ReadonlySet<EventType> = new Set<EventType>([
  "page_view", "page_load", "click", "repeated_click", "interaction_failure", "form_validation_failure",
  "search", "search_no_results", "abandonment", "error_message", "workflow_completed", "slow_response", "inactivity",
]);
const META_KEYS = ["error_code", "http_status", "element_label", "search_query", "form_field_category", "step", "endpoint", "attempt", "reason"] as const;
const SLOW_MS = 3000;

function sessionId(): string {
  try {
    let id = sessionStorage.getItem("churnce.sid");
    if (!id) { id = `ses_${crypto.randomUUID()}`; sessionStorage.setItem("churnce.sid", id); }
    return id;
  } catch {
    return `ses_${crypto.randomUUID()}`; // storage blocked: per-page-load pseudonym
  }
}
const SID = sessionId();

function emit(type: EventType, extra: Partial<OutEvent> = {}): void {
  const ev: OutEvent = {
    event_id: `evt_${crypto.randomUUID()}`,
    session_id: SID,
    event_type: type,
    page_route: safeRoute(location.href),
    event_timestamp: new Date().toISOString(),
    consent_state: "authorized",
    site_host: location.hostname,
    ...extra,
  };
  chrome.runtime.sendMessage({ kind: "event", event: ev }).catch(() => undefined);
  touch();
}

// ── Inactivity ────────────────────────────────────────────────────────────────
let idleTimer: ReturnType<typeof setTimeout> | undefined;
let idleFired = false;
function touch(): void {
  idleFired = false;
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => { if (!idleFired) { idleFired = true; emitQuiet("inactivity"); } }, 60_000);
}
function emitQuiet(type: EventType): void { // does not reset the idle timer
  chrome.runtime.sendMessage({ kind: "event", event: {
    event_id: `evt_${crypto.randomUUID()}`, session_id: SID, event_type: type, page_route: safeRoute(location.href),
    event_timestamp: new Date().toISOString(), consent_state: "authorized", site_host: location.hostname,
  } satisfies OutEvent }).catch(() => undefined);
}

// ── Navigation and load timing ────────────────────────────────────────────────
let lastRoute = "";
function pageView(): void {
  const route = safeRoute(location.href);
  if (route === lastRoute) return;
  lastRoute = route;
  emit("page_view");
}
function pageLoad(): void {
  const nav = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
  const ms = nav && nav.loadEventEnd > 0 ? Math.round(nav.loadEventEnd - nav.startTime) : undefined;
  if (ms === undefined) return;
  emit(ms > SLOW_MS ? "slow_response" : "page_load", { response_time_ms: ms });
}
const navApi = (window as unknown as { navigation?: EventTarget }).navigation;
if (navApi) navApi.addEventListener("navigatesuccess", () => setTimeout(pageView, 0));
else { window.addEventListener("popstate", pageView); window.addEventListener("hashchange", pageView); }
pageView();
if (document.readyState === "complete") pageLoad(); else window.addEventListener("load", () => setTimeout(pageLoad, 0), { once: true });

// ── Designated clicks and rapid repeats ───────────────────────────────────────
const recent = new Map<Element, number[]>();
document.addEventListener("click", (e) => {
  const el = (e.target as Element | null)?.closest?.("[data-churnce-action]");
  if (!el) return;
  const category = el.getAttribute("data-churnce-action") ?? "interactive";
  const label = el.getAttribute("data-churnce-label");
  emit("click", { element_category: category, meta: label ? { element_label: label.slice(0, 60) } : undefined });
  const now = Date.now();
  const hits = (recent.get(el) ?? []).filter((t) => now - t < 2500);
  hits.push(now);
  recent.set(el, hits);
  if (hits.length === 3) emit("repeated_click", { element_category: category });
}, { capture: true, passive: true });

// ── Form validation failures: category only, never the value ──────────────────
document.addEventListener("invalid", (e) => {
  const t = e.target as HTMLInputElement | null;
  const kind = t?.type && !NEVER_READ.has(t.type) ? t.type : "sensitive_or_unknown";
  emit("form_validation_failure", { element_category: "form_field", meta: { form_field_category: kind } });
}, { capture: true });

// ── Visible error messages ────────────────────────────────────────────────────
const seen = new WeakSet<Element>();
new MutationObserver((records) => {
  for (const r of records) for (const n of r.addedNodes) {
    if (!(n instanceof Element)) continue;
    const el = n.matches("[role='alert'], [data-churnce-error]") ? n : n.querySelector("[role='alert'], [data-churnce-error]");
    if (el && !seen.has(el)) {
      seen.add(el);
      emit("error_message", { outcome: "error", meta: { error_code: (el.getAttribute("data-churnce-error") ?? "ui_error").slice(0, 60) } });
    }
  }
}).observe(document.documentElement, { childList: true, subtree: true });

// ── Designated search box ─────────────────────────────────────────────────────
document.addEventListener("submit", (e) => {
  const input = (e.target as HTMLFormElement | null)?.querySelector?.<HTMLInputElement>("input[data-churnce-search]");
  if (input?.value) emit("search", { meta: { search_query: redact(input.value).slice(0, 80) } });
}, { capture: true });

// ── Explicit application events (preferred) ───────────────────────────────────
window.addEventListener("churnce:event", (e) => {
  let d: Record<string, unknown>;
  try { d = JSON.parse(String((e as CustomEvent).detail)) as Record<string, unknown>; } catch { return; }
  const type = d.type as EventType;
  if (!ALLOWED.has(type)) return;
  const meta: Record<string, string | number | boolean> = {};
  const src = (d.meta ?? {}) as Record<string, unknown>;
  for (const k of META_KEYS) {
    const v = src[k];
    if (typeof v === "number" || typeof v === "boolean") meta[k] = v;
    else if (typeof v === "string") meta[k] = redact(v).slice(0, 200);
  }
  emit(type, {
    element_category: typeof d.element_category === "string" ? d.element_category.slice(0, 60) : undefined,
    outcome: typeof d.outcome === "string" ? d.outcome.slice(0, 30) : undefined,
    response_time_ms: typeof d.response_time_ms === "number" ? Math.round(d.response_time_ms) : undefined,
    meta: Object.keys(meta).length ? meta : undefined,
  });
});

// ── Premium: financial transactions the application reports ──────────────────
window.addEventListener("churnce:transaction", (e) => {
  let d: Record<string, unknown>;
  try { d = JSON.parse(String((e as CustomEvent).detail)) as Record<string, unknown>; } catch { return; }
  const txn = sanitiseTxn(d);
  if (txn) chrome.runtime.sendMessage({ kind: "txn", host: location.hostname, txn: { ...txn, session_ref: SID } }).catch(() => undefined);
});

// ── Abandonment: leaving while a designated workflow is still open ────────────
let abandoned = false;
function maybeAbandon(): void {
  const wf = document.documentElement.dataset.churnceWorkflow;
  if (wf && !abandoned) { abandoned = true; emit("abandonment", { outcome: "abandoned", meta: { step: wf.slice(0, 40) } }); }
}
window.addEventListener("pagehide", maybeAbandon);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") maybeAbandon(); else abandoned = false; });

touch();
