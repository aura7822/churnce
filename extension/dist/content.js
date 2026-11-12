"use strict";
(() => {
  // src/shared/privacy.ts
  var PATTERNS = [
    // Government identifiers (labelled national ID / passport, KRA PIN) and IBAN-shaped strings. Over-redacting here is deliberate.
    [/\b(?:national\s*id|id\s*(?:no|number)|passport(?:\s*(?:no|number))?)\b\s*[:#.]?\s*[A-Z0-9]{6,12}\b/gi, "[id-number]"],
    [/\bID\s*[:#]?\s*\d{7,9}\b/g, "[id-number]"],
    [/\b[AP]\d{9}[A-Z]\b/g, "[id-number]"],
    [/\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b/g, "[bank-account]"],
    [/\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b/g, "[email]"],
    [/\b(?:\d[ -]?){13,19}\b/g, "[number]"],
    [/\b(?:\+?\d{1,3}[ -]?)?(?:\(?\d{2,4}\)?[ -]?){2,4}\d{2,4}\b/g, "[phone]"],
    [/\b(?:eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}|[A-Za-z0-9_-]{32,})\b/g, "[token]"]
  ];
  function redact(text) {
    return PATTERNS.reduce((t, [re, label]) => t.replace(re, label), text);
  }
  function safeRoute(href) {
    try {
      const u = new URL(href);
      return u.pathname || "/";
    } catch {
      return "/";
    }
  }
  var NEVER_READ = /* @__PURE__ */ new Set(["password", "hidden", "file", "tel", "email"]);

  // src/shared/consent.ts
  var TXN_TYPES = ["payment", "subscription", "refund", "chargeback", "fee", "payout", "invoice", "bill", "inventory_in", "inventory_out"];
  var TXN_STATUS = ["success", "failed", "pending"];
  var TXN_METHODS = ["card", "mobile_money", "bank_transfer", "wallet", "cash_on_delivery", "other"];
  var TXN_REASONS = ["insufficient_funds", "card_declined", "expired_card", "fraud_check", "timeout", "network", "issuer_unavailable", "processing_error", "cancelled_by_user", "other"];
  var pick = (list, v, fallback) => typeof v === "string" && list.includes(v) ? v : fallback;
  function sanitiseTxn(d, now = /* @__PURE__ */ new Date()) {
    const amount = typeof d.amount === "number" ? d.amount : NaN;
    if (!Number.isFinite(amount) || amount < 0 || amount > 1e9) return null;
    const currency = typeof d.currency === "string" && /^[A-Za-z]{3}$/.test(d.currency) ? d.currency.toUpperCase() : null;
    if (!currency || typeof d.txn_type !== "string" || !TXN_TYPES.includes(d.txn_type)) return null;
    if (typeof d.status !== "string" || !TXN_STATUS.includes(d.status)) return null;
    const ref = typeof d.event_id === "string" && /^[\w.:-]{3,60}$/.test(d.event_id) ? d.event_id : null;
    if (ref && /\d{13,}/.test(ref)) return null;
    const status = d.status;
    const bankRaw = typeof d.bank === "string" ? d.bank.trim() : "";
    const bank = bankRaw && bankRaw.length <= 40 && /^[A-Za-z0-9 &-]+$/.test(bankRaw) && !/\d{6,}/.test(bankRaw) ? bankRaw : void 0;
    const dueMs = typeof d.due_at === "string" ? Date.parse(d.due_at) : NaN;
    const due_at = Number.isFinite(dueMs) ? new Date(dueMs).toISOString() : void 0;
    return {
      event_id: ref ?? `txn_${Math.random().toString(36).slice(2, 12)}`,
      txn_type: d.txn_type,
      status,
      amount: Math.round(amount * 100) / 100,
      currency,
      method: pick(TXN_METHODS, d.method, "other"),
      ...status === "failed" ? { reason: pick(TXN_REASONS, d.reason, "other") } : {},
      occurred_at: now.toISOString(),
      ...bank ? { bank } : {},
      ...due_at ? { due_at } : {}
    };
  }

  // src/content/index.ts
  var ALLOWED = /* @__PURE__ */ new Set([
    "page_view",
    "page_load",
    "click",
    "repeated_click",
    "interaction_failure",
    "form_validation_failure",
    "search",
    "search_no_results",
    "abandonment",
    "error_message",
    "workflow_completed",
    "slow_response",
    "inactivity"
  ]);
  var META_KEYS = ["error_code", "http_status", "element_label", "search_query", "form_field_category", "step", "endpoint", "attempt", "reason"];
  var SLOW_MS = 3e3;
  function sessionId() {
    try {
      let id = sessionStorage.getItem("churnce.sid");
      if (!id) {
        id = `ses_${crypto.randomUUID()}`;
        sessionStorage.setItem("churnce.sid", id);
      }
      return id;
    } catch {
      return `ses_${crypto.randomUUID()}`;
    }
  }
  var SID = sessionId();
  function emit(type, extra = {}) {
    const ev = {
      event_id: `evt_${crypto.randomUUID()}`,
      session_id: SID,
      event_type: type,
      page_route: safeRoute(location.href),
      event_timestamp: (/* @__PURE__ */ new Date()).toISOString(),
      consent_state: "authorized",
      site_host: location.hostname,
      ...extra
    };
    chrome.runtime.sendMessage({ kind: "event", event: ev }).catch(() => void 0);
    touch();
  }
  var idleTimer;
  var idleFired = false;
  function touch() {
    idleFired = false;
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      if (!idleFired) {
        idleFired = true;
        emitQuiet("inactivity");
      }
    }, 6e4);
  }
  function emitQuiet(type) {
    chrome.runtime.sendMessage({ kind: "event", event: {
      event_id: `evt_${crypto.randomUUID()}`,
      session_id: SID,
      event_type: type,
      page_route: safeRoute(location.href),
      event_timestamp: (/* @__PURE__ */ new Date()).toISOString(),
      consent_state: "authorized",
      site_host: location.hostname
    } }).catch(() => void 0);
  }
  var lastRoute = "";
  function pageView() {
    const route = safeRoute(location.href);
    if (route === lastRoute) return;
    lastRoute = route;
    emit("page_view");
  }
  function pageLoad() {
    const nav = performance.getEntriesByType("navigation")[0];
    const ms = nav && nav.loadEventEnd > 0 ? Math.round(nav.loadEventEnd - nav.startTime) : void 0;
    if (ms === void 0) return;
    emit(ms > SLOW_MS ? "slow_response" : "page_load", { response_time_ms: ms });
  }
  var navApi = window.navigation;
  if (navApi) navApi.addEventListener("navigatesuccess", () => setTimeout(pageView, 0));
  else {
    window.addEventListener("popstate", pageView);
    window.addEventListener("hashchange", pageView);
  }
  pageView();
  if (document.readyState === "complete") pageLoad();
  else window.addEventListener("load", () => setTimeout(pageLoad, 0), { once: true });
  var recent = /* @__PURE__ */ new Map();
  document.addEventListener("click", (e) => {
    const el = e.target?.closest?.("[data-churnce-action]");
    if (!el) return;
    const category = el.getAttribute("data-churnce-action") ?? "interactive";
    const label = el.getAttribute("data-churnce-label");
    emit("click", { element_category: category, meta: label ? { element_label: label.slice(0, 60) } : void 0 });
    const now = Date.now();
    const hits = (recent.get(el) ?? []).filter((t) => now - t < 2500);
    hits.push(now);
    recent.set(el, hits);
    if (hits.length === 3) emit("repeated_click", { element_category: category });
  }, { capture: true, passive: true });
  document.addEventListener("invalid", (e) => {
    const t = e.target;
    const kind = t?.type && !NEVER_READ.has(t.type) ? t.type : "sensitive_or_unknown";
    emit("form_validation_failure", { element_category: "form_field", meta: { form_field_category: kind } });
  }, { capture: true });
  var seen = /* @__PURE__ */ new WeakSet();
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
  document.addEventListener("submit", (e) => {
    const input = e.target?.querySelector?.("input[data-churnce-search]");
    if (input?.value) emit("search", { meta: { search_query: redact(input.value).slice(0, 80) } });
  }, { capture: true });
  window.addEventListener("churnce:event", (e) => {
    let d;
    try {
      d = JSON.parse(String(e.detail));
    } catch {
      return;
    }
    const type = d.type;
    if (!ALLOWED.has(type)) return;
    const meta = {};
    const src = d.meta ?? {};
    for (const k of META_KEYS) {
      const v = src[k];
      if (typeof v === "number" || typeof v === "boolean") meta[k] = v;
      else if (typeof v === "string") meta[k] = redact(v).slice(0, 200);
    }
    emit(type, {
      element_category: typeof d.element_category === "string" ? d.element_category.slice(0, 60) : void 0,
      outcome: typeof d.outcome === "string" ? d.outcome.slice(0, 30) : void 0,
      response_time_ms: typeof d.response_time_ms === "number" ? Math.round(d.response_time_ms) : void 0,
      meta: Object.keys(meta).length ? meta : void 0
    });
  });
  window.addEventListener("churnce:transaction", (e) => {
    let d;
    try {
      d = JSON.parse(String(e.detail));
    } catch {
      return;
    }
    const txn = sanitiseTxn(d);
    if (txn) chrome.runtime.sendMessage({ kind: "txn", host: location.hostname, txn: { ...txn, session_ref: SID } }).catch(() => void 0);
  });
  var abandoned = false;
  function maybeAbandon() {
    const wf = document.documentElement.dataset.churnceWorkflow;
    if (wf && !abandoned) {
      abandoned = true;
      emit("abandonment", { outcome: "abandoned", meta: { step: wf.slice(0, 40) } });
    }
  }
  window.addEventListener("pagehide", maybeAbandon);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") maybeAbandon();
    else abandoned = false;
  });
  touch();
})();
//# sourceMappingURL=content.js.map
