import { loadSettings } from "../shared/config";
import { hostOf } from "../shared/consent";
import { FREE_FEATURES, PREMIUM_FEATURES, SITE_ROLES } from "../shared/plans";
import { formatCountdown, trialView } from "../shared/trial";
import { $, ask, icon, siteIds, type SiteIds } from "./ui";

/** Steps 4 to 6: generated credentials (auto-filled into the sign-in card), role sign-in, and plans with the 72-hour trial. */
type State = { premium: { active: boolean; source: "org" | "trial" | null; trial_ends_at: string | null; seconds_left: number; trial_used?: boolean }; capture: { state: string }; rtt_ms: number | null; website_id: string | null };
const li = (text: string, strong?: string) => { const e = document.createElement("li"); if (strong) { const b = document.createElement("b"); b.textContent = strong; e.append(b, document.createElement("br")); } e.append(text); return e; };
let peekTimer: ReturnType<typeof setTimeout> | undefined;
let tick: ReturnType<typeof setInterval> | undefined;
let wired = false;

function setPeek(input: HTMLInputElement, btn: HTMLElement, show: boolean): void {
  input.type = show ? "text" : "password";
  btn.setAttribute("aria-pressed", String(show));
  btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
  icon(btn, show ? "eye-off" : "eye");
  clearTimeout(peekTimer);
  if (show) peekTimer = setTimeout(() => setPeek(input, btn, false), 10000); // a peek, not a standing exposure
}

function peekButton(input: HTMLInputElement): HTMLButtonElement {
  const b = document.createElement("button");
  b.type = "button"; b.className = "secondary icon"; b.setAttribute("aria-label", "Show password"); b.setAttribute("aria-pressed", "false");
  b.innerHTML = '<svg><use href="#i-eye"/></svg>';
  b.addEventListener("click", () => setPeek(input, b, input.type === "password"));
  return b;
}

function showCreds(websiteId: string, password: string): void {
  const box = $("creds");
  box.hidden = false;
  box.replaceChildren();
  const h = document.createElement("p");
  h.innerHTML = "<b>Save these now.</b> The password is shown once; only a hash is stored. They were filled into the sign-in card for you.";
  const dl = document.createElement("dl");
  const pw = document.createElement("input");
  pw.type = "password"; pw.readOnly = true; pw.value = password; pw.className = "mono"; pw.setAttribute("aria-label", "Generated password");
  const pwRow = document.createElement("span");
  pwRow.className = "field"; pwRow.append(pw, peekButton(pw));
  const idDd = document.createElement("dd"); idDd.textContent = websiteId;
  const dt1 = document.createElement("dt"), dt2 = document.createElement("dt"), dd2 = document.createElement("dd");
  dt1.textContent = "Website ID"; dt2.textContent = "Password"; dd2.append(pwRow);
  dl.append(dt1, idDd, dt2, dd2);
  const copy = document.createElement("button");
  copy.type = "button"; copy.className = "secondary"; copy.innerHTML = '<svg><use href="#i-copy"/></svg>Copy both';
  copy.addEventListener("click", async () => { await navigator.clipboard.writeText(`Website ID: ${websiteId}\nPassword: ${password}`); copy.lastChild!.textContent = "Copied"; });
  box.append(h, dl, copy);
}

function syncSignIn(): void {
  const ready = !!$<HTMLInputElement>("slId").value.trim() && !!$<HTMLInputElement>("slPass").value.trim();
  const role = $<HTMLSelectElement>("slRole");
  role.disabled = !ready;
  $("roleHint").textContent = ready ? "Choose the role you are working as." : "Enter the ID and password first, then choose your role.";
  $<HTMLButtonElement>("slBtn").disabled = !ready || !role.value;
}

export async function renderIdentity(): Promise<void> {
  const s = await loadSettings();
  const ids = await siteIds();
  const states = ((await chrome.storage.local.get("siteState")).siteState ?? {}) as Record<string, State>;
  // site pickers
  for (const sel of [$<HTMLSelectElement>("credSite"), $<HTMLSelectElement>("trialSite")]) {
    const keep = sel.value;
    sel.replaceChildren(...s.origins.map((o) => Object.assign(document.createElement("option"), { value: o, textContent: `${hostOf(o) ?? o}${(ids[o]?.website_id ?? states[o]?.website_id) ? ` · ${ids[o]?.website_id ?? states[o]?.website_id}` : ""}` })));
    if (keep && s.origins.includes(keep)) sel.value = keep;
  }
  renderTrial(states, ids);
}

function renderTrial(states: Record<string, State>, ids: Record<string, SiteIds>): void {
  const sel = $<HTMLSelectElement>("trialSite"), btn = $<HTMLButtonElement>("startTrial"), out = $("trialState"), timer = $("timer");
  clearInterval(tick);
  const o = sel.value;
  if (!o) { out.textContent = "Authorise a website and generate its ID to start the trial."; timer.hidden = true; btn.disabled = true; return; }
  const st = states[o];
  const wid = ids[o]?.website_id ?? st?.website_id ?? null;
  const view = trialView(st ? { ends_at: st.premium.trial_ends_at, used: !!st.premium.trial_used || !!st.premium.trial_ends_at } : undefined, st?.premium);
  const draw = () => {
    const left = st?.premium.trial_ends_at ? Date.parse(st.premium.trial_ends_at) - Date.now() : 0;
    if (view.phase === "active") {
      timer.hidden = false; timer.textContent = formatCountdown(left);
      out.textContent = `Premium is on for ${wid ?? hostOf(o)} until the timer ends.`;
      if (left <= 0) { clearInterval(tick); void ask({ kind: "site:heartbeat" }); }
    }
  };
  btn.disabled = true;
  timer.hidden = view.phase !== "active";
  if (view.phase === "org") out.textContent = "Premium is active for your organisation. No trial needed.";
  else if (view.phase === "active") { draw(); tick = setInterval(draw, 1000); }
  else if (view.phase === "ended") out.textContent = `The free trial for ${wid ?? "this website ID"} has ended. It can be used once per website ID.`;
  else if (!wid) out.textContent = "Generate a website ID for this site first (step 4).";
  else { out.textContent = `Try every Premium feature on ${wid} for 72 hours. No card needed.`; btn.disabled = false; }
}

export async function initIdentity(onChange: () => void): Promise<void> {
  if (wired) return;
  wired = true;
  $("freeList").replaceChildren(...FREE_FEATURES.map((f) => li(f)));
  $("premList").replaceChildren(...PREMIUM_FEATURES.map((f) => li(f.text, f.title)));
  $("slRole").replaceChildren(Object.assign(document.createElement("option"), { value: "", textContent: "Choose a role…" }), ...SITE_ROLES.map(([v, l]) => Object.assign(document.createElement("option"), { value: v, textContent: l })));
  const pass = $<HTMLInputElement>("slPass");
  $("peek").addEventListener("click", () => setPeek(pass, $("peek"), pass.type === "password"));
  for (const id of ["slId", "slPass"]) $(id).addEventListener("input", syncSignIn);
  $("slRole").addEventListener("change", syncSignIn);
  $("trialSite").addEventListener("change", () => void renderIdentity());

  $("genCreds").addEventListener("click", async () => {
    const origin = $<HTMLSelectElement>("credSite").value;
    const msg = $("msg");
    if (!origin) return void (msg.textContent = "Authorise a website first.");
    const ids = await siteIds();
    const name = ids[origin]?.name || $<HTMLInputElement>("siteName").value, owner = ids[origin]?.owner_name || $<HTMLInputElement>("ownerName").value;
    if (!name.trim() || !owner.trim()) return void (msg.textContent = "Enter the website name and owner name in the authorise card first.");
    const btn = $<HTMLButtonElement>("genCreds");
    btn.disabled = true; msg.textContent = "Generating website ID and password…";
    const r = await ask<{ website_id?: string; password?: string | null }>({ kind: "site:register", origin, name, owner, generate: true });
    btn.disabled = false;
    if (!r.ok || !r.website_id || !r.password) return void (msg.textContent = r.error ?? "Could not generate credentials.");
    showCreds(r.website_id, r.password);
    $<HTMLInputElement>("slId").value = r.website_id;
    $<HTMLInputElement>("slPass").value = r.password;
    setPeek(pass, $("peek"), false);
    syncSignIn();
    $("siteLogin").classList.add("flash");
    $("siteLogin").scrollIntoView({ behavior: "smooth", block: "center" });
    msg.textContent = `Created ${r.website_id}. The sign-in card is filled in: choose your role, then sign in.`;
    onChange();
  });

  $("slForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const status = $("slStatus");
    status.textContent = "Signing in…";
    const r = await ask<{ who?: string; role?: string }>({ kind: "site:login", websiteId: $<HTMLInputElement>("slId").value, password: pass.value, role: $<HTMLSelectElement>("slRole").value });
    if (r.ok) {
      status.textContent = `Signed in as ${r.who} (${r.role?.replace("_", " ")}). Open the dashboard and use the Website ID tab with the same details. You will see this website only.`;
      $("openDash").hidden = false;
      await chrome.storage.session.set({ signedIn: true });
    } else status.textContent = r.error ?? "Sign in failed.";
    pass.value = ""; setPeek(pass, $("peek"), false); syncSignIn();
    onChange();
  });
  $("openDash").addEventListener("click", async () => void chrome.tabs.create({ url: (await loadSettings()).dashboardUrl }));

  $("startTrial").addEventListener("click", async () => {
    const o = $<HTMLSelectElement>("trialSite").value;
    const btn = $<HTMLButtonElement>("startTrial");
    btn.disabled = true; $("trialState").textContent = "Starting the 72-hour trial…";
    const r = await ask({ kind: "trial:start", origin: o });
    if (!r.ok) $("trialState").textContent = r.error ?? "Could not start the trial.";
    await renderIdentity();
    onChange();
  });
  syncSignIn();
  await renderIdentity();
}
