// src/shared/config.ts
var DEFAULTS = { backendUrl: "http://localhost:8000", ingestKey: "", origins: [], monitoring: false, consent: null, dashboardUrl: "http://localhost:5173" };
async function loadSettings() {
  const got = await chrome.storage.local.get("settings");
  return { ...DEFAULTS, ...got.settings };
}
async function saveSettings(patch) {
  const next = { ...await loadSettings(), ...patch };
  await chrome.storage.local.set({ settings: next });
  return next;
}
function normalizeOrigin(input) {
  try {
    const u = new URL(input.includes("://") ? input : `https://${input}`);
    if (u.protocol !== "http:" && u.protocol !== "https:") return null;
    return u.origin;
  } catch {
    return null;
  }
}

// src/shared/consent.ts
var REQUIRED_SCOPES = ["session", "user_data"];
function monitoringAllowed(c) {
  return !!c && REQUIRED_SCOPES.every((s) => c.scopes.includes(s));
}
function summariseCookies(cookies) {
  const n = (f) => Math.min(5e3, cookies.filter((c) => !!f(c)).length);
  return { total: Math.min(5e3, cookies.length), session_cookies: n((c) => c.session), secure: n((c) => c.secure), http_only: n((c) => c.httpOnly), session_present: cookies.some((c) => c.session) };
}
function hostOf(origin) {
  try {
    return new URL(origin).hostname.toLowerCase();
  } catch {
    return null;
  }
}

// src/background/index.ts
var QUEUE_KEY = "queue";
var STATUS_KEY = "status";
var MAX_QUEUE = 500;
var BATCH = 50;
var flushTimer;
var flushing = false;
async function queue() {
  return (await chrome.storage.local.get(QUEUE_KEY))[QUEUE_KEY] ?? [];
}
async function setStatus(s) {
  await chrome.storage.local.set({ [STATUS_KEY]: { ...s, at: (/* @__PURE__ */ new Date()).toISOString() } });
}
async function enqueue(ev) {
  const s = await loadSettings();
  if (!s.monitoring || !s.ingestKey || !monitoringAllowed(s.consent)) return;
  const host = ev.site_host.split(":")[0];
  const allowed = s.origins.some((o) => {
    try {
      return new URL(o).hostname === host;
    } catch {
      return false;
    }
  });
  if (!allowed) return;
  const q = await queue();
  q.push(ev);
  await chrome.storage.local.set({ [QUEUE_KEY]: q.slice(-MAX_QUEUE) });
  clearTimeout(flushTimer);
  flushTimer = setTimeout(() => void flush(), 1200);
}
async function flush() {
  if (flushing) return;
  flushing = true;
  try {
    const s = await loadSettings();
    let q = await queue();
    while (q.length && s.monitoring && s.ingestKey && monitoringAllowed(s.consent)) {
      const batch = q.slice(0, BATCH);
      const res = await fetch(`${s.backendUrl.replace(/\/$/, "")}/api/v1/events`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Churnce-Key": s.ingestKey },
        body: JSON.stringify({ events: batch })
      });
      if (res.status === 401 || res.status === 403) {
        await setStatus({ ok: false, message: "Ingest key rejected. Check the key in settings." });
        return;
      }
      if (res.status >= 400 && res.status < 500 && res.status !== 429) {
        q = q.slice(batch.length);
        await chrome.storage.local.set({ [QUEUE_KEY]: q });
        continue;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      q = q.slice(batch.length);
      await chrome.storage.local.set({ [QUEUE_KEY]: q });
      await setStatus({ ok: true, message: `Delivered ${batch.length} event(s)` });
    }
  } catch (err) {
    await setStatus({ ok: false, message: `Backend unreachable, will retry (${err.message})` });
  } finally {
    flushing = false;
  }
}
var syncing = Promise.resolve();
function syncContentScripts() {
  syncing = syncing.then(doSync, doSync);
  return syncing;
}
async function doSync() {
  const s = await loadSettings();
  const existing = await chrome.scripting.getRegisteredContentScripts();
  if (existing.length) await chrome.scripting.unregisterContentScripts({ ids: existing.map((x) => x.id) });
  const granted = [];
  for (const o of s.origins) if (await chrome.permissions.contains({ origins: [`${o}/*`] })) granted.push(`${o}/*`);
  if (s.monitoring && granted.length && monitoringAllowed(s.consent)) {
    await chrome.scripting.registerContentScripts([{ id: "churnce-observer", matches: granted, js: ["content.js"], runAt: "document_idle", persistAcrossSessions: true }]);
  }
}
var SITE_STATE = "siteState";
async function readState() {
  return (await chrome.storage.local.get(SITE_STATE))[SITE_STATE] ?? {};
}
async function patchState(origin, p) {
  const all = await readState();
  all[origin] = { premium: { active: false, source: null, trial_ends_at: null, seconds_left: 0 }, capture: { state: "running" }, rtt_ms: null, website_id: null, at: (/* @__PURE__ */ new Date()).toISOString(), ...all[origin], ...p };
  await chrome.storage.local.set({ [SITE_STATE]: all });
}
async function problem(res) {
  try {
    const j = await res.json();
    return typeof j.detail === "string" ? j.detail : `HTTP ${res.status}`;
  } catch {
    return `HTTP ${res.status}`;
  }
}
async function beat(origin, s, cookies) {
  const host = hostOf(origin);
  if (!host) return { ok: false, error: "Not a valid website address" };
  const prev = (await readState())[origin];
  const t0 = performance.now();
  try {
    const res = await fetch(`${s.backendUrl.replace(/\/$/, "")}/api/v1/sites/heartbeat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Churnce-Key": s.ingestKey },
      body: JSON.stringify({
        site_host: host,
        monitoring: s.monitoring && monitoringAllowed(s.consent),
        ...prev?.rtt_ms ? { rtt_ms: Math.min(6e4, Math.round(prev.rtt_ms)) } : {},
        consent: s.consent ? { scopes: s.consent.scopes, accepted_at: s.consent.acceptedAt, extension_version: s.consent.extensionVersion } : { scopes: [] },
        ...cookies ? { cookies } : {}
      })
    });
    const rtt = Math.round(performance.now() - t0);
    if (!res.ok) return { ok: false, status: res.status, rtt_ms: rtt, error: res.status === 401 ? "The ingest key was rejected" : res.status === 403 ? "The backend does not list this domain as authorised for your tenant" : `Backend answered HTTP ${res.status}` };
    const j = await res.json();
    await patchState(origin, { rtt_ms: rtt, at: (/* @__PURE__ */ new Date()).toISOString(), ...j.premium ? { premium: j.premium } : {}, ...j.finance_capture ? { capture: j.finance_capture } : {}, website_id: j.website_id ?? prev?.website_id ?? null });
    return { ok: true, rtt_ms: rtt, premium: j.premium, capture: j.finance_capture, website_id: j.website_id ?? null };
  } catch (e) {
    return { ok: false, error: `Backend unreachable (${e.message})` };
  }
}
async function heartbeat() {
  const s = await loadSettings();
  if (!s.ingestKey || !s.origins.length) return;
  const cookiesOk = !!s.consent?.scopes.includes("cookies") && await chrome.permissions.contains({ permissions: ["cookies"] });
  for (const origin of s.origins) {
    let cookies;
    if (cookiesOk) {
      try {
        cookies = summariseCookies(await chrome.cookies.getAll({ url: `${origin}/` }));
      } catch {
        cookies = void 0;
      }
    }
    const r = await beat(origin, s, cookies);
    if (!r.ok && r.status && r.status !== 403) await setStatus({ ok: false, message: `Heartbeat for ${hostOf(origin)} failed (${r.error})` });
  }
}
async function handshake(origin) {
  const s = await loadSettings();
  if (!s.ingestKey) return { ok: false, error: "Save the ingest key first" };
  if (!s.origins.includes(origin)) return { ok: false, error: "Authorise this site first" };
  return beat(origin, s);
}
async function startTrial(origin) {
  const s = await loadSettings();
  const host = hostOf(origin);
  if (!host || !s.origins.includes(origin)) return { ok: false, error: "Authorise this site first" };
  const res = await fetch(`${s.backendUrl.replace(/\/$/, "")}/api/v1/sites/trial`, { method: "POST", headers: { "Content-Type": "application/json", "X-Churnce-Key": s.ingestKey }, body: JSON.stringify({ site_host: host }) });
  if (!res.ok) {
    await beat(origin, s);
    return { ok: false, error: await problem(res) };
  }
  const j = await res.json();
  await patchState(origin, { premium: j.premium });
  await beat(origin, s);
  return { ok: true, premium: j.premium };
}
var TXN_QUEUE = "txnQueue";
var FINANCE_STATUS = "financeStatus";
var txnTimer;
var txnFlushing = false;
async function enqueueTxn(host, txn) {
  const s = await loadSettings();
  if (!s.monitoring || !s.ingestKey || !monitoringAllowed(s.consent) || !s.consent?.scopes.includes("finance")) return;
  const origin = s.origins.find((o) => hostOf(o) === host.split(":")[0]);
  if (!origin) return;
  const st = (await readState())[origin];
  if (st && (st.capture.state !== "running" || !st.premium.active)) return;
  const q = (await chrome.storage.local.get(TXN_QUEUE))[TXN_QUEUE] ?? [];
  q.push({ host: host.split(":")[0], txn });
  await chrome.storage.local.set({ [TXN_QUEUE]: q.slice(-MAX_QUEUE) });
  clearTimeout(txnTimer);
  txnTimer = setTimeout(() => void flushTxns(), 1500);
}
async function flushTxns() {
  if (txnFlushing) return;
  txnFlushing = true;
  const note = (ok, message) => chrome.storage.local.set({ [FINANCE_STATUS]: { ok, message, at: (/* @__PURE__ */ new Date()).toISOString() } });
  try {
    const s = await loadSettings();
    let q = (await chrome.storage.local.get(TXN_QUEUE))[TXN_QUEUE] ?? [];
    while (q.length && s.ingestKey) {
      const host = q[0].host;
      const batch = q.filter((x) => x.host === host).slice(0, BATCH);
      const res = await fetch(`${s.backendUrl.replace(/\/$/, "")}/api/v1/finance/events`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Churnce-Key": s.ingestKey },
        body: JSON.stringify({ site_host: host, events: batch.map((b) => b.txn) })
      });
      if (res.status === 402) {
        await note(false, "Premium is not active for this website, so transactions are not stored. Start the free trial in the plans card.");
        q = q.filter((x) => x !== batch[0] && !batch.includes(x));
        await chrome.storage.local.set({ [TXN_QUEUE]: q });
        return;
      }
      if (res.status === 403) {
        await note(false, "The backend refused finance events: check the domain is authorised and finance consent was sent.");
        q = q.filter((x) => !batch.includes(x));
        await chrome.storage.local.set({ [TXN_QUEUE]: q });
        return;
      }
      if (res.status >= 400 && res.status < 500 && res.status !== 429) {
        q = q.filter((x) => !batch.includes(x));
        await chrome.storage.local.set({ [TXN_QUEUE]: q });
        continue;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      q = q.filter((x) => !batch.includes(x));
      await chrome.storage.local.set({ [TXN_QUEUE]: q });
      await note(true, `Delivered ${batch.length} transaction event(s)`);
    }
  } catch (err) {
    await note(false, `Backend unreachable, will retry (${err.message})`);
  } finally {
    txnFlushing = false;
  }
}
async function registerSite(origin, name, owner, generate) {
  const s = await loadSettings();
  const host = hostOf(origin);
  if (!host || !s.origins.includes(origin)) return { ok: false, error: "Authorise this site first." };
  if (!s.ingestKey) return { ok: false, error: "Save the ingest key first." };
  if (generate && (!name.trim() || !owner.trim())) return { ok: false, error: "Enter the website name and owner name first." };
  const res = await fetch(`${s.backendUrl.replace(/\/$/, "")}/api/v1/sites/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Churnce-Key": s.ingestKey },
    body: JSON.stringify({ site_host: host, name, owner_name: owner, regenerate_password: generate })
  });
  if (!res.ok) return { ok: false, error: res.status === 403 ? "The backend does not list this domain as authorised for your tenant." : await problem(res) };
  const j = await res.json();
  const ids = (await chrome.storage.local.get("siteIds")).siteIds ?? {};
  if (j.website_id) ids[origin] = { website_id: j.website_id, name: j.name ?? name, owner_name: j.owner_name ?? owner };
  await chrome.storage.local.set({ siteIds: ids });
  return { ...j, ok: true };
}
async function siteLogin(websiteId, password, role) {
  if (role === "administrator") return { ok: false, error: "Administrator cannot sign in with a website ID. Use the administrator account." };
  const s = await loadSettings();
  const res = await fetch(`${s.backendUrl.replace(/\/$/, "")}/api/v1/auth/site-login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ website_id: websiteId.trim(), password: password.trim(), role }) });
  if (!res.ok) return { ok: false, error: await problem(res) };
  const j = await res.json();
  return { ok: true, who: j.user.name, role: j.user.role };
}
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  const fail = (e) => reply({ ok: false, error: e.message });
  if (msg.kind === "site:handshake" && msg.origin) {
    void handshake(msg.origin).then(reply).catch(fail);
    return true;
  }
  if (msg.kind === "trial:start" && msg.origin) {
    void startTrial(msg.origin).then(reply).catch(fail);
    return true;
  }
  if (msg.kind === "site:register") {
    const m = msg;
    void registerSite(m.origin, m.name, m.owner, m.generate).then(reply).catch(fail);
    return true;
  }
  if (msg.kind === "site:login") {
    const m = msg;
    void siteLogin(m.websiteId, m.password, m.role).then(reply).catch(fail);
    return true;
  }
  if (msg.kind === "txn") {
    const m = msg;
    void enqueueTxn(m.host, m.txn);
    return false;
  }
  if (msg.kind === "site:heartbeat") {
    void heartbeat().then(() => reply({ ok: true }));
    return true;
  }
  if (msg.kind === "event") {
    void enqueue(msg.event);
    return false;
  }
  if (msg.kind === "sync") {
    void syncContentScripts().then(() => reply({ ok: true }));
    return true;
  }
  if (msg.kind === "authorize" && msg.origin) {
    const origin = normalizeOrigin(msg.origin);
    if (!origin) {
      reply({ ok: false });
      return false;
    }
    void loadSettings().then(async (s) => {
      await saveSettings({ origins: [.../* @__PURE__ */ new Set([...s.origins, origin])] });
      await syncContentScripts();
      reply({ ok: true });
    });
    return true;
  }
  if (msg.kind === "revoke" && msg.origin) {
    void loadSettings().then(async (s) => {
      await saveSettings({ origins: s.origins.filter((o) => o !== msg.origin) });
      await chrome.permissions.remove({ origins: [`${msg.origin}/*`] }).catch(() => false);
      await syncContentScripts();
      reply({ ok: true });
    });
    return true;
  }
  return false;
});
chrome.runtime.onInstalled.addListener(() => void syncContentScripts());
chrome.runtime.onStartup.addListener(() => {
  void flush();
  void heartbeat();
});
chrome.alarms.create("flush", { periodInMinutes: 1 });
chrome.alarms.create("heartbeat", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === "flush") {
    void flush();
    void flushTxns();
  }
  if (a.name === "heartbeat") void heartbeat();
});
chrome.storage.onChanged.addListener((c) => {
  if (c.settings) void syncContentScripts();
});
//# sourceMappingURL=background.js.map
