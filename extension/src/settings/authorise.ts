import { loadSettings, normalizeOrigin } from "../shared/config";
import { hostOf } from "../shared/consent";
import { $, ask } from "./ui";

/** Step 3: "Authorise site" runs a real, visible sequence: browser permission, extension registration, a backend handshake (with measured latency),
 *  saving the website name and owner, then a final sync of plan and capture state. Each step reports what actually happened. */
interface StepDef { label: string; run: () => Promise<string | void> }
type Beat = { ok: boolean; error?: string; rtt_ms?: number; premium?: { active: boolean; source: string | null; seconds_left: number }; capture?: { state: string }; website_id?: string | null };

function paint(steps: StepDef[], state: ("wait" | "now" | "done" | "fail")[], notes: string[]): void {
  $("progSteps").replaceChildren(...steps.map((s, i) => {
    const li = document.createElement("li");
    li.className = state[i] === "wait" ? "" : state[i];
    const dot = document.createElement("span");
    dot.className = "dot"; dot.textContent = state[i] === "done" ? "✓" : state[i] === "fail" ? "!" : state[i] === "now" ? "" : String(i + 1);
    const t = document.createElement("span");
    t.textContent = s.label;
    const n = document.createElement("small");
    n.textContent = notes[i] ?? "";
    li.append(dot, t, n);
    return li;
  }));
  const done = state.filter((x) => x === "done").length, now = state.includes("now") ? 0.5 : 0;
  const pct = Math.round(((done + now) / steps.length) * 100);
  $("progPct").textContent = `${pct}%`;
  const bar = $("progBar");
  bar.setAttribute("aria-valuenow", String(pct));
  (bar.firstElementChild as HTMLElement).style.width = `${pct}%`;
}

export async function authoriseSite(): Promise<boolean> {
  const origin = normalizeOrigin($<HTMLInputElement>("origin").value);
  const msg = $("msg");
  if (!origin) { msg.textContent = "Enter a valid website address."; return false; }
  const name = $<HTMLInputElement>("siteName").value.trim(), owner = $<HTMLInputElement>("ownerName").value.trim();
  const s0 = await loadSettings();
  if (!s0.ingestKey) { msg.textContent = "Save the connection (backend URL and ingest key) first."; return false; }
  let last: Beat = { ok: false };
  const steps: StepDef[] = [
    { label: "Asking the browser for permission", run: async () => { if (!(await chrome.permissions.request({ origins: [`${origin}/*`] }))) throw new Error("Permission declined. Nothing will be observed on that site."); return "granted"; } },
    { label: "Registering the site in the extension", run: async () => { const r = await ask({ kind: "authorize", origin }); if (!r?.ok) throw new Error("Could not register the site."); return hostOf(origin) ?? ""; } },
    { label: "Handshake with Churnce", run: async () => { last = await ask<Beat>({ kind: "site:handshake", origin }); if (!last.ok) throw new Error(last.error ?? "The backend did not answer."); return `${last.rtt_ms} ms`; } },
    { label: "Saving website name and owner", run: async () => {
      if (!name && !owner) return "skipped";
      const r = await ask<{ website_id?: string }>({ kind: "site:register", origin, name, owner, generate: false });
      if (!r.ok) throw new Error(r.error ?? "Could not save the name and owner.");
      return r.website_id ?? "saved";
    } },
    { label: "Syncing plan and capture state", run: async () => {
      last = await ask<Beat>({ kind: "site:handshake", origin });
      if (!last.ok) throw new Error(last.error ?? "Sync failed.");
      return `${last.premium?.active ? (last.premium.source === "trial" ? "trial" : "premium") : "free"} · capture ${last.capture?.state ?? "running"}`;
    } },
  ];
  const state: ("wait" | "now" | "done" | "fail")[] = steps.map(() => "wait"), notes: string[] = [];
  $("progress").hidden = false;
  $("progTitle").textContent = `Syncing with ${hostOf(origin)}…`;
  $<HTMLButtonElement>("authBtn").disabled = true;
  paint(steps, state, notes);
  let ok = true;
  for (let i = 0; i < steps.length; i++) {
    state[i] = "now"; paint(steps, state, notes);
    try {
      notes[i] = (await steps[i].run()) ?? "";
      state[i] = "done";
    } catch (e) {
      state[i] = "fail"; notes[i] = (e as Error).message.slice(0, 80); ok = false;
      msg.textContent = (e as Error).message;
    }
    paint(steps, state, notes);
    if (!ok) break;
    await new Promise((r) => setTimeout(r, 250)); // let the progress be seen on fast networks
  }
  $("progTitle").textContent = ok ? `${hostOf(origin)} is authorised and in sync` : "Authorisation stopped";
  $<HTMLButtonElement>("authBtn").disabled = false;
  if (ok) msg.textContent = `Authorised ${origin}. Next: generate its website ID and password.`;
  return ok;
}
