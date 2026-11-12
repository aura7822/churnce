/**
 * Service worker: owns the settings, the delivery queue and the content-script registration.
 * It is the only place that talks to the Churnce backend. No AI keys live here, only a write-only ingest key.
 */
import { loadSettings, normalizeOrigin, saveSettings, type OutEvent } from "../shared/config";
import { hostOf, monitoringAllowed, summariseCookies, type OutTxn } from "../shared/consent";
import type { PremiumState } from "../shared/trial";

const QUEUE_KEY = "queue";
const STATUS_KEY = "status";
const MAX_QUEUE = 500;
const BATCH = 50;
let flushTimer: ReturnType<typeof setTimeout> | undefined;
let flushing = false;

async function queue(): Promise<OutEvent[]> {
  return ((await chrome.storage.local.get(QUEUE_KEY))[QUEUE_KEY] as OutEvent[] | undefined) ?? [];
}
async function setStatus(s: { ok: boolean; message: string }): Promise<void> {
  await chrome.storage.local.set({ [STATUS_KEY]: { ...s, at: new Date().toISOString() } });
}

async function enqueue(ev: OutEvent): Promise<void> {
  const s = await loadSettings();
  if (!s.monitoring || !s.ingestKey || !monitoringAllowed(s.consent)) return; // no explicit consent, no monitoring
  const host = ev.site_host.split(":")[0];
  const allowed = s.origins.some((o) => { try { return new URL(o).hostname === host; } catch { return false; } });
  if (!allowed) return; // defence in depth: drop anything from a host that is not authorised
  const q = await queue();
  q.push(ev);
  await chrome.storage.local.set({ [QUEUE_KEY]: q.slice(-MAX_QUEUE) });
  clearTimeout(flushTimer);
  flushTimer = setTimeout(() => void flush(), 1200);
}

async function flush(): Promise<void> {
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
        body: JSON.stringify({ events: batch }),
      });
      if (res.status === 401 || res.status === 403) { await setStatus({ ok: false, message: "Ingest key rejected. Check the key in settings." }); return; }
      if (res.status >= 400 && res.status < 500 && res.status !== 429) { q = q.slice(batch.length); await chrome.storage.local.set({ [QUEUE_KEY]: q }); continue; } // malformed: drop, do not loop
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      q = q.slice(batch.length);
      await chrome.storage.local.set({ [QUEUE_KEY]: q });
      await setStatus({ ok: true, message: `Delivered ${batch.length} event(s)` });
    }
  } catch (err) {
    await setStatus({ ok: false, message: `Backend unreachable, will retry (${(err as Error).message})` });
  } finally {
    flushing = false;
  }
}

/** Registers the content script for exactly the origins that were authorised, and nothing else. */
let syncing: Promise<void> = Promise.resolve();
function syncContentScripts(): Promise<void> {
  syncing = syncing.then(doSync, doSync); // serialised: concurrent unregister/register calls would collide on the script id
  return syncing;
}
async function doSync(): Promise<void> {
  const s = await loadSettings();
  const existing = await chrome.scripting.getRegisteredContentScripts();
  if (existing.length) await chrome.scripting.unregisterContentScripts({ ids: existing.map((x) => x.id) });
  const granted: string[] = [];
  for (const o of s.origins) if (await chrome.permissions.contains({ origins: [`${o}/*`] })) granted.push(`${o}/*`);
  if (s.monitoring && granted.length && monitoringAllowed(s.consent)) {
    await chrome.scripting.registerContentScripts([{ id: "churnce-observer", matches: granted, js: ["content.js"], runAt: "document_idle", persistAcrossSessions: true }]);
  }
}

// ── Connected-site heartbeat, handshake and per-site state ─────────────────────
const SITE_STATE = "siteState";
type CaptureStateName = "running" | "paused" | "stopped";
export interface SiteState { premium: PremiumState & { trial_used?: boolean }; capture: { state: CaptureStateName }; rtt_ms: number | null; website_id: string | null; at: string }

async function readState(): Promise<Record<string, SiteState>> {
  return ((await chrome.storage.local.get(SITE_STATE))[SITE_STATE] as Record<string, SiteState> | undefined) ?? {};
}
async function patchState(origin: string, p: Partial<SiteState>): Promise<void> {
  const all = await readState();
  all[origin] = { premium: { active: false, source: null, trial_ends_at: null, seconds_left: 0 }, capture: { state: "running" }, rtt_ms: null, website_id: null, at: new Date().toISOString(), ...all[origin], ...p };
  await chrome.storage.local.set({ [SITE_STATE]: all });
}
async function problem(res: Response): Promise<string> {
  try { const j = await res.json(); return typeof j.detail === "string" ? j.detail : `HTTP ${res.status}`; } catch { return `HTTP ${res.status}`; }
}

interface Beat { ok: boolean; status?: number; rtt_ms?: number; error?: string; premium?: SiteState["premium"]; capture?: SiteState["capture"]; website_id?: string | null }

/** One heartbeat for one origin: tells the backend the site is live and what consent the owner gave, and learns the plan, trial and capture state. */
async function beat(origin: string, s: Awaited<ReturnType<typeof loadSettings>>, cookies?: ReturnType<typeof summariseCookies>): Promise<Beat> {
  const host = hostOf(origin);
  if (!host) return { ok: false, error: "Not a valid website address" };
  const prev = (await readState())[origin];
  const t0 = performance.now();
  try {
    const res = await fetch(`${s.backendUrl.replace(/\/$/, "")}/api/v1/sites/heartbeat`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-Churnce-Key": s.ingestKey },
      body: JSON.stringify({
        site_host: host, monitoring: s.monitoring && monitoringAllowed(s.consent), ...(prev?.rtt_ms ? { rtt_ms: Math.min(60000, Math.round(prev.rtt_ms)) } : {}),
        consent: s.consent ? { scopes: s.consent.scopes, accepted_at: s.consent.acceptedAt, extension_version: s.consent.extensionVersion } : { scopes: [] },
        ...(cookies ? { cookies } : {}),
      }),
    });
    const rtt = Math.round(performance.now() - t0);
    if (!res.ok) return { ok: false, status: res.status, rtt_ms: rtt, error: res.status === 401 ? "The ingest key was rejected" : res.status === 403 ? "The backend does not list this domain as authorised for your tenant" : `Backend answered HTTP ${res.status}` };
    const j = (await res.json()) as { premium?: SiteState["premium"]; finance_capture?: { state: CaptureStateName }; website_id?: string | null };
    await patchState(origin, { rtt_ms: rtt, at: new Date().toISOString(), ...(j.premium ? { premium: j.premium } : {}), ...(j.finance_capture ? { capture: j.finance_capture } : {}), website_id: j.website_id ?? prev?.website_id ?? null });
    return { ok: true, rtt_ms: rtt, premium: j.premium, capture: j.finance_capture, website_id: j.website_id ?? null };
  } catch (e) {
    return { ok: false, error: `Backend unreachable (${(e as Error).message})` };
  }
}

async function heartbeat(): Promise<void> {
  const s = await loadSettings();
  if (!s.ingestKey || !s.origins.length) return;
  const cookiesOk = !!s.consent?.scopes.includes("cookies") && (await chrome.permissions.contains({ permissions: ["cookies"] }));
  for (const origin of s.origins) {
    let cookies;
    if (cookiesOk) { try { cookies = summariseCookies(await chrome.cookies.getAll({ url: `${origin}/` })); } catch { cookies = undefined; } }
    const r = await beat(origin, s, cookies);
    if (!r.ok && r.status && r.status !== 403) await setStatus({ ok: false, message: `Heartbeat for ${hostOf(origin)} failed (${r.error})` });
  }
}

/** Authorise-site step: a live round trip so the settings window can show real progress and the latency. */
async function handshake(origin: string): Promise<Beat> {
  const s = await loadSettings();
  if (!s.ingestKey) return { ok: false, error: "Save the ingest key first" };
  if (!s.origins.includes(origin)) return { ok: false, error: "Authorise this site first" };
  return beat(origin, s);
}

/** Starts the 72-hour Premium trial for the website id of this origin (once per website id). */
async function startTrial(origin: string): Promise<{ ok: boolean; error?: string; premium?: SiteState["premium"] }> {
  const s = await loadSettings();
  const host = hostOf(origin);
  if (!host || !s.origins.includes(origin)) return { ok: false, error: "Authorise this site first" };
  const res = await fetch(`${s.backendUrl.replace(/\/$/, "")}/api/v1/sites/trial`, { method: "POST", headers: { "Content-Type": "application/json", "X-Churnce-Key": s.ingestKey }, body: JSON.stringify({ site_host: host }) });
  if (!res.ok) { await beat(origin, s); return { ok: false, error: await problem(res) }; }
  const j = (await res.json()) as { premium: SiteState["premium"] };
  await patchState(origin, { premium: j.premium });
  await beat(origin, s);
  return { ok: true, premium: j.premium };
}

// ── Premium: finance events ────────────────────────────────────────────────────
const TXN_QUEUE = "txnQueue";
const FINANCE_STATUS = "financeStatus";
let txnTimer: ReturnType<typeof setTimeout> | undefined;
let txnFlushing = false;
type QTxn = { host: string; txn: OutTxn };

async function enqueueTxn(host: string, txn: OutTxn): Promise<void> {
  const s = await loadSettings();
  // Finance capture needs monitoring on, the base consent AND the separate finance consent.
  if (!s.monitoring || !s.ingestKey || !monitoringAllowed(s.consent) || !s.consent?.scopes.includes("finance")) return;
  const origin = s.origins.find((o) => hostOf(o) === host.split(":")[0]);
  if (!origin) return;
  const st = (await readState())[origin]; // paused or stopped from the dashboard, or no Premium/trial: keep nothing back
  if (st && (st.capture.state !== "running" || !st.premium.active)) return;
  const q = (((await chrome.storage.local.get(TXN_QUEUE))[TXN_QUEUE]) as QTxn[] | undefined) ?? [];
  q.push({ host: host.split(":")[0], txn });
  await chrome.storage.local.set({ [TXN_QUEUE]: q.slice(-MAX_QUEUE) });
  clearTimeout(txnTimer);
  txnTimer = setTimeout(() => void flushTxns(), 1500);
}

async function flushTxns(): Promise<void> {
  if (txnFlushing) return;
  txnFlushing = true;
  const note = (ok: boolean, message: string) => chrome.storage.local.set({ [FINANCE_STATUS]: { ok, message, at: new Date().toISOString() } });
  try {
    const s = await loadSettings();
    let q = (((await chrome.storage.local.get(TXN_QUEUE))[TXN_QUEUE]) as QTxn[] | undefined) ?? [];
    while (q.length && s.ingestKey) {
      const host = q[0].host;
      const batch = q.filter((x) => x.host === host).slice(0, BATCH);
      const res = await fetch(`${s.backendUrl.replace(/\/$/, "")}/api/v1/finance/events`, {
        method: "POST", headers: { "Content-Type": "application/json", "X-Churnce-Key": s.ingestKey },
        body: JSON.stringify({ site_host: host, events: batch.map((b) => b.txn) }),
      });
      if (res.status === 402) { await note(false, "Premium is not active for this website, so transactions are not stored. Start the free trial in the plans card."); q = q.filter((x) => x !== batch[0] && !batch.includes(x)); await chrome.storage.local.set({ [TXN_QUEUE]: q }); return; }
      if (res.status === 403) { await note(false, "The backend refused finance events: check the domain is authorised and finance consent was sent."); q = q.filter((x) => !batch.includes(x)); await chrome.storage.local.set({ [TXN_QUEUE]: q }); return; }
      if (res.status >= 400 && res.status < 500 && res.status !== 429) { q = q.filter((x) => !batch.includes(x)); await chrome.storage.local.set({ [TXN_QUEUE]: q }); continue; }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      q = q.filter((x) => !batch.includes(x));
      await chrome.storage.local.set({ [TXN_QUEUE]: q });
      await note(true, `Delivered ${batch.length} transaction event(s)`);
    }
  } catch (err) {
    await note(false, `Backend unreachable, will retry (${(err as Error).message})`);
  } finally {
    txnFlushing = false;
  }
}

// ── Website identity, role sign-in and plan ────────────────────────────────────
type Reg = { ok: boolean; error?: string; website_id?: string; name?: string; owner_name?: string; password?: string | null; has_credentials?: boolean };

/** Ingest-key call: saves the site's name and owner and, on request, generates its website id and password (shown once). */
async function registerSite(origin: string, name: string, owner: string, generate: boolean): Promise<Reg> {
  const s = await loadSettings();
  const host = hostOf(origin);
  if (!host || !s.origins.includes(origin)) return { ok: false, error: "Authorise this site first." };
  if (!s.ingestKey) return { ok: false, error: "Save the ingest key first." };
  if (generate && (!name.trim() || !owner.trim())) return { ok: false, error: "Enter the website name and owner name first." };
  const res = await fetch(`${s.backendUrl.replace(/\/$/, "")}/api/v1/sites/register`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Churnce-Key": s.ingestKey },
    body: JSON.stringify({ site_host: host, name, owner_name: owner, regenerate_password: generate }),
  });
  if (!res.ok) return { ok: false, error: res.status === 403 ? "The backend does not list this domain as authorised for your tenant." : await problem(res) };
  const j = (await res.json()) as Reg;
  const ids = ((await chrome.storage.local.get("siteIds")).siteIds as Record<string, { website_id: string; name: string; owner_name: string }> | undefined) ?? {};
  if (j.website_id) ids[origin] = { website_id: j.website_id, name: j.name ?? name, owner_name: j.owner_name ?? owner }; // the id and names are not secret; the password is never stored here
  await chrome.storage.local.set({ siteIds: ids });
  return { ...j, ok: true };
}

/** Website id + password + a role other than administrator, verified against the backend. The dashboard sign-in uses the same details. */
async function siteLogin(websiteId: string, password: string, role: string): Promise<{ ok: boolean; error?: string; who?: string; role?: string }> {
  if (role === "administrator") return { ok: false, error: "Administrator cannot sign in with a website ID. Use the administrator account." };
  const s = await loadSettings();
  const res = await fetch(`${s.backendUrl.replace(/\/$/, "")}/api/v1/auth/site-login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ website_id: websiteId.trim(), password: password.trim(), role }) });
  if (!res.ok) return { ok: false, error: await problem(res) };
  const j = (await res.json()) as { user: { name: string; role: string } };
  return { ok: true, who: j.user.name, role: j.user.role }; // the token is not kept here: the extension only verifies the credentials
}

chrome.runtime.onMessage.addListener((msg: { kind: string; origin?: string }, _sender, reply) => {
  const fail = (e: Error) => reply({ ok: false, error: e.message });
  if (msg.kind === "site:handshake" && msg.origin) { void handshake(msg.origin).then(reply).catch(fail); return true; }
  if (msg.kind === "trial:start" && msg.origin) { void startTrial(msg.origin).then(reply).catch(fail); return true; }
  if (msg.kind === "site:register") { const m = msg as unknown as { origin: string; name: string; owner: string; generate: boolean }; void registerSite(m.origin, m.name, m.owner, m.generate).then(reply).catch(fail); return true; }
  if (msg.kind === "site:login") { const m = msg as unknown as { websiteId: string; password: string; role: string }; void siteLogin(m.websiteId, m.password, m.role).then(reply).catch(fail); return true; }
  if (msg.kind === "txn") { const m = msg as unknown as { host: string; txn: OutTxn }; void enqueueTxn(m.host, m.txn); return false; }
  if (msg.kind === "site:heartbeat") { void heartbeat().then(() => reply({ ok: true })); return true; }
  if (msg.kind === "event") { void enqueue((msg as unknown as { event: OutEvent }).event); return false; }
  if (msg.kind === "sync") { void syncContentScripts().then(() => reply({ ok: true })); return true; }
  if (msg.kind === "authorize" && msg.origin) {
    const origin = normalizeOrigin(msg.origin);
    if (!origin) { reply({ ok: false }); return false; }
    void loadSettings().then(async (s) => { await saveSettings({ origins: [...new Set([...s.origins, origin])] }); await syncContentScripts(); reply({ ok: true }); });
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
chrome.runtime.onStartup.addListener(() => { void flush(); void heartbeat(); });
chrome.alarms.create("flush", { periodInMinutes: 1 });
chrome.alarms.create("heartbeat", { periodInMinutes: 0.5 }); // backend treats a site as live for 90 s
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "flush") { void flush(); void flushTxns(); } if (a.name === "heartbeat") void heartbeat(); });
chrome.storage.onChanged.addListener((c) => { if (c.settings) void syncContentScripts(); });
