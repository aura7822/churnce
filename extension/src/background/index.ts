/**
 * Service worker: owns the settings, the delivery queue and the content-script registration.
 * It is the only place that talks to the Churnce backend. No AI keys live here, only a write-only ingest key.
 */
import { loadSettings, normalizeOrigin, saveSettings, type OutEvent } from "../shared/config";
import { autoSendEligible, OPEN_STATUSES, type Draft } from "../shared/outreach";

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
  if (!s.monitoring || !s.ingestKey) return;
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
    while (q.length && s.monitoring && s.ingestKey) {
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
  if (s.monitoring && granted.length) {
    await chrome.scripting.registerContentScripts([{ id: "churnce-observer", matches: granted, js: ["content.js"], runAt: "document_idle", persistAcrossSessions: true }]);
  }
}

// ── Customer emails ────────────────────────────────────────────────────────────
// The operator's bearer token lives in chrome.storage.session (memory only, cleared when the browser closes).
// Recipient addresses and SMTP credentials never reach the extension: the backend sends, the extension only edits and triggers.
const TOKEN_KEY = "operatorToken";
const OPERATOR_KEY = "operator";
const DRAFTS_KEY = "drafts";
const OUTREACH_STATUS = "outreachStatus";
const MAX_AUTO_PER_RUN = 10;

class AuthError extends Error {}

async function backend(path: string, init: RequestInit = {}, auth = true): Promise<Response> {
  const s = await loadSettings();
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(init.headers as Record<string, string> | undefined) };
  if (auth) {
    const token = ((await chrome.storage.session.get(TOKEN_KEY))[TOKEN_KEY] as string | undefined) ?? "";
    if (!token) throw new AuthError("Sign in as an operator first");
    headers.Authorization = `Bearer ${token}`;
  }
  const res = await fetch(`${s.backendUrl.replace(/\/$/, "")}/api/v1${path}`, { ...init, headers });
  if (res.status === 401) { await chrome.storage.session.remove([TOKEN_KEY, OPERATOR_KEY]); throw new AuthError("Session expired. Sign in again."); }
  return res;
}
async function problem(res: Response): Promise<string> {
  try { const j = await res.json(); return typeof j.detail === "string" ? j.detail : `HTTP ${res.status}`; } catch { return `HTTP ${res.status}`; }
}
async function setOutreach(message: string, ok = true): Promise<void> {
  await chrome.storage.local.set({ [OUTREACH_STATUS]: { ok, message, at: new Date().toISOString() } });
}

async function refreshDrafts(): Promise<Draft[]> {
  const res = await backend(`/emails?status=${OPEN_STATUSES.join(",")}`);
  if (!res.ok) throw new Error(await problem(res));
  const drafts = ((await res.json()) as { emails: Draft[] }).emails;
  await chrome.storage.local.set({ [DRAFTS_KEY]: drafts });
  return drafts;
}

async function sendDraft(d: Draft): Promise<void> {
  if (d.status === "draft") {
    const a = await backend(`/emails/${d.id}/approve`, { method: "POST" });
    if (!a.ok) throw new Error(await problem(a));
  }
  const r = await backend(`/emails/${d.id}/send`, { method: "POST" });
  if (!r.ok) throw new Error(await problem(r));
}

/** Runs every minute while the operator is signed in. Retrieval and auto-send are separate switches. */
async function outreachTick(): Promise<void> {
  const s = await loadSettings();
  if (!s.emailRetrieve) return;
  try {
    const drafts = await refreshDrafts();
    if (!s.emailAutoSend) { await setOutreach(`${drafts.length} draft(s) ready for review`); return; }
    let sent = 0, failed = 0;
    for (const d of drafts.filter((x) => autoSendEligible(x, s.emailAutoSendDelayMin)).slice(0, MAX_AUTO_PER_RUN)) {
      try { await sendDraft(d); sent++; } catch (e) { failed++; await setOutreach(`Auto-send stopped on ${d.id}: ${(e as Error).message}`, false); }
    }
    await refreshDrafts();
    if (!failed) await setOutreach(sent ? `Auto-sent ${sent} email(s)` : `${drafts.length} draft(s) waiting; none eligible yet`);
  } catch (e) {
    await setOutreach(e instanceof AuthError ? e.message : `Could not reach Churnce (${(e as Error).message})`, false);
  }
}

type Reply = (r: unknown) => void;
async function outreachMessage(msg: { kind: string; [k: string]: unknown }, reply: Reply): Promise<void> {
  try {
    switch (msg.kind) {
      case "auth:login": {
        const res = await backend("/auth/login", { method: "POST", body: JSON.stringify({ email: msg.email, password: msg.password }) }, false);
        if (!res.ok) return reply({ ok: false, error: await problem(res) });
        const j = (await res.json()) as { token: string; user: { name: string; role: string } };
        if (!["administrator", "marketing_operator"].includes(j.user.role)) return reply({ ok: false, error: "This account cannot approve customer emails (needs administrator or marketing operator)." });
        await chrome.storage.session.set({ [TOKEN_KEY]: j.token, [OPERATOR_KEY]: { name: j.user.name, role: j.user.role } });
        return reply({ ok: true, operator: j.user });
      }
      case "auth:logout":
        await chrome.storage.session.remove([TOKEN_KEY, OPERATOR_KEY]);
        await chrome.storage.local.remove(DRAFTS_KEY);
        return reply({ ok: true });
      case "emails:refresh": return reply({ ok: true, drafts: await refreshDrafts() });
      case "emails:save": {
        const r = await backend(`/emails/${msg.id}`, { method: "PATCH", body: JSON.stringify({ subject: msg.subject, body: msg.body }) });
        if (!r.ok) return reply({ ok: false, error: await problem(r) });
        return reply({ ok: true, drafts: await refreshDrafts() });
      }
      case "emails:send": {
        const drafts = ((await chrome.storage.local.get(DRAFTS_KEY))[DRAFTS_KEY] as Draft[] | undefined) ?? [];
        const d = drafts.find((x) => x.id === msg.id);
        if (!d) return reply({ ok: false, error: "Draft not found. Refresh the list." });
        await sendDraft(d);
        return reply({ ok: true, drafts: await refreshDrafts() });
      }
      case "emails:reject": {
        const r = await backend(`/emails/${msg.id}/reject`, { method: "POST" });
        if (!r.ok) return reply({ ok: false, error: await problem(r) });
        return reply({ ok: true, drafts: await refreshDrafts() });
      }
    }
  } catch (e) {
    reply({ ok: false, error: (e as Error).message });
  }
}

chrome.runtime.onMessage.addListener((msg: { kind: string; origin?: string }, _sender, reply) => {
  if (msg.kind.startsWith("auth:") || msg.kind.startsWith("emails:")) { void outreachMessage(msg as { kind: string }, reply); return true; }
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
chrome.runtime.onStartup.addListener(() => void flush());
chrome.alarms.create("flush", { periodInMinutes: 1 });
chrome.alarms.create("outreach", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "flush") void flush(); if (a.name === "outreach") void outreachTick(); });
chrome.storage.onChanged.addListener((c) => { if (c.settings) void syncContentScripts(); });
