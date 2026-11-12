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
var SCOPE_COPY = {
  session: { title: "Session", reads: "A random per-visit session id and the order of events inside it, so friction can be seen as a journey.", never: "Login state, tokens or any cookie value.", required: true },
  user_data: { title: "Usage data", reads: "Page routes, element categories, timings and outcomes (for example 'checkout button clicked 4 times').", never: "Keystrokes, form values, names, emails, payment details or any personal or sensitive information.", required: true },
  finance: { title: "Transactions (Premium)", reads: "Transaction type, status, amount, currency, payment-method category and failure reason, plus the site's own opaque reference.", never: "Card or account numbers, payer names, emails, addresses or any payer identity.", required: false },
  cookies: { title: "Cookies", reads: "Counts and flags only: how many cookies, how many are session, secure or HttpOnly cookies.", never: "Cookie names and values.", required: false }
};
function monitoringAllowed(c) {
  return !!c && REQUIRED_SCOPES.every((s) => c.scopes.includes(s));
}
function hostOf(origin) {
  try {
    return new URL(origin).hostname.toLowerCase();
  } catch {
    return null;
  }
}

// src/settings/ui.ts
var $ = (id) => document.getElementById(id);
var ask = (m) => chrome.runtime.sendMessage(m);
function icon(el, name) {
  el.querySelector("use")?.setAttribute("href", `#i-${name}`);
}
function locked(card, on) {
  card.classList.toggle("is-locked", on);
  card.querySelectorAll(":scope > *:not(.lock-veil)").forEach((e) => {
    e.inert = on;
  });
}
async function siteIds() {
  return (await chrome.storage.local.get("siteIds")).siteIds ?? {};
}

// src/settings/authorise.ts
function paint(steps, state, notes) {
  $("progSteps").replaceChildren(...steps.map((s, i) => {
    const li2 = document.createElement("li");
    li2.className = state[i] === "wait" ? "" : state[i];
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.textContent = state[i] === "done" ? "\u2713" : state[i] === "fail" ? "!" : state[i] === "now" ? "" : String(i + 1);
    const t = document.createElement("span");
    t.textContent = s.label;
    const n = document.createElement("small");
    n.textContent = notes[i] ?? "";
    li2.append(dot, t, n);
    return li2;
  }));
  const done = state.filter((x) => x === "done").length, now = state.includes("now") ? 0.5 : 0;
  const pct = Math.round((done + now) / steps.length * 100);
  $("progPct").textContent = `${pct}%`;
  const bar = $("progBar");
  bar.setAttribute("aria-valuenow", String(pct));
  bar.firstElementChild.style.width = `${pct}%`;
}
async function authoriseSite() {
  const origin = normalizeOrigin($("origin").value);
  const msg = $("msg");
  if (!origin) {
    msg.textContent = "Enter a valid website address.";
    return false;
  }
  const name = $("siteName").value.trim(), owner = $("ownerName").value.trim();
  const s0 = await loadSettings();
  if (!s0.ingestKey) {
    msg.textContent = "Save the connection (backend URL and ingest key) first.";
    return false;
  }
  let last = { ok: false };
  const steps = [
    { label: "Asking the browser for permission", run: async () => {
      if (!await chrome.permissions.request({ origins: [`${origin}/*`] })) throw new Error("Permission declined. Nothing will be observed on that site.");
      return "granted";
    } },
    { label: "Registering the site in the extension", run: async () => {
      const r = await ask({ kind: "authorize", origin });
      if (!r?.ok) throw new Error("Could not register the site.");
      return hostOf(origin) ?? "";
    } },
    { label: "Handshake with Churnce", run: async () => {
      last = await ask({ kind: "site:handshake", origin });
      if (!last.ok) throw new Error(last.error ?? "The backend did not answer.");
      return `${last.rtt_ms} ms`;
    } },
    { label: "Saving website name and owner", run: async () => {
      if (!name && !owner) return "skipped";
      const r = await ask({ kind: "site:register", origin, name, owner, generate: false });
      if (!r.ok) throw new Error(r.error ?? "Could not save the name and owner.");
      return r.website_id ?? "saved";
    } },
    { label: "Syncing plan and capture state", run: async () => {
      last = await ask({ kind: "site:handshake", origin });
      if (!last.ok) throw new Error(last.error ?? "Sync failed.");
      return `${last.premium?.active ? last.premium.source === "trial" ? "trial" : "premium" : "free"} \xB7 capture ${last.capture?.state ?? "running"}`;
    } }
  ];
  const state = steps.map(() => "wait"), notes = [];
  $("progress").hidden = false;
  $("progTitle").textContent = `Syncing with ${hostOf(origin)}\u2026`;
  $("authBtn").disabled = true;
  paint(steps, state, notes);
  let ok = true;
  for (let i = 0; i < steps.length; i++) {
    state[i] = "now";
    paint(steps, state, notes);
    try {
      notes[i] = await steps[i].run() ?? "";
      state[i] = "done";
    } catch (e) {
      state[i] = "fail";
      notes[i] = e.message.slice(0, 80);
      ok = false;
      msg.textContent = e.message;
    }
    paint(steps, state, notes);
    if (!ok) break;
    await new Promise((r) => setTimeout(r, 250));
  }
  $("progTitle").textContent = ok ? `${hostOf(origin)} is authorised and in sync` : "Authorisation stopped";
  $("authBtn").disabled = false;
  if (ok) msg.textContent = `Authorised ${origin}. Next: generate its website ID and password.`;
  return ok;
}

// src/shared/plans.ts
var FREE_FEATURES = [
  "Consent-based friction capture on authorised sites",
  "Review gate, RAG window and Digest classification",
  "Evidence-linked recommendations and approved win-back emails",
  "Connected sites, roles and live activity"
];
var PREMIUM_FEATURES = [
  { title: "Liquidity engine", text: "Live cash position across banks and currencies, converted to KES, with runway and coverage." },
  { title: "Multi-horizon forecasts and stress tests", text: "7 to 90 day income and cashflow forecasts with confidence bands, plus scenario stress tests." },
  { title: "Working capital and pooling", text: "Receivables, payables and inventory cycles, with cash pooling and sweeping rules." },
  { title: "Compliance ratios", text: "Current ratio, quick ratio and liquidity coverage ratio, checked against thresholds." },
  { title: "Cents AI analyst", text: "A virtual financial analyst that summarises your metrics, offers advice and answers questions." },
  { title: "Transaction capture", text: "Amounts, currency, status, bank label and failure reason. Never card numbers, account numbers or payer identity." }
];
var SITE_ROLES = [["data_analyst", "Data Analyst"], ["developer", "Developer"], ["website_owner", "Website Owner"]];

// src/shared/trial.ts
function trialView(entry, premium, now = Date.now()) {
  if (premium?.active && (premium.source === "org" || premium.source === "pro")) return { phase: "org", msLeft: 0 };
  const endsRaw = premium?.trial_ends_at ?? entry?.ends_at ?? null;
  const ends = endsRaw ? Date.parse(endsRaw) : NaN;
  if (Number.isFinite(ends)) return ends > now ? { phase: "active", msLeft: ends - now } : { phase: "ended", msLeft: 0 };
  return entry?.used ? { phase: "ended", msLeft: 0 } : { phase: "none", msLeft: 0 };
}
function formatCountdown(ms) {
  const t = Math.max(0, Math.floor(ms / 1e3));
  const p = (n) => String(n).padStart(2, "0");
  return `${p(Math.floor(t / 3600))}:${p(Math.floor(t % 3600 / 60))}:${p(t % 60)}`;
}

// src/settings/identity.ts
var li = (text, strong) => {
  const e = document.createElement("li");
  if (strong) {
    const b = document.createElement("b");
    b.textContent = strong;
    e.append(b, document.createElement("br"));
  }
  e.append(text);
  return e;
};
var peekTimer;
var tick;
var wired = false;
function setPeek(input, btn, show) {
  input.type = show ? "text" : "password";
  btn.setAttribute("aria-pressed", String(show));
  btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
  icon(btn, show ? "eye-off" : "eye");
  clearTimeout(peekTimer);
  if (show) peekTimer = setTimeout(() => setPeek(input, btn, false), 1e4);
}
function peekButton(input) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "secondary icon";
  b.setAttribute("aria-label", "Show password");
  b.setAttribute("aria-pressed", "false");
  b.innerHTML = '<svg><use href="#i-eye"/></svg>';
  b.addEventListener("click", () => setPeek(input, b, input.type === "password"));
  return b;
}
function showCreds(websiteId, password) {
  const box = $("creds");
  box.hidden = false;
  box.replaceChildren();
  const h = document.createElement("p");
  h.innerHTML = "<b>Save these now.</b> The password is shown once; only a hash is stored. They were filled into the sign-in card for you.";
  const dl = document.createElement("dl");
  const pw = document.createElement("input");
  pw.type = "password";
  pw.readOnly = true;
  pw.value = password;
  pw.className = "mono";
  pw.setAttribute("aria-label", "Generated password");
  const pwRow = document.createElement("span");
  pwRow.className = "field";
  pwRow.append(pw, peekButton(pw));
  const idDd = document.createElement("dd");
  idDd.textContent = websiteId;
  const dt1 = document.createElement("dt"), dt2 = document.createElement("dt"), dd2 = document.createElement("dd");
  dt1.textContent = "Website ID";
  dt2.textContent = "Password";
  dd2.append(pwRow);
  dl.append(dt1, idDd, dt2, dd2);
  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "secondary";
  copy.innerHTML = '<svg><use href="#i-copy"/></svg>Copy both';
  copy.addEventListener("click", async () => {
    await navigator.clipboard.writeText(`Website ID: ${websiteId}
Password: ${password}`);
    copy.lastChild.textContent = "Copied";
  });
  box.append(h, dl, copy);
}
function syncSignIn() {
  const ready = !!$("slId").value.trim() && !!$("slPass").value.trim();
  const role = $("slRole");
  role.disabled = !ready;
  $("roleHint").textContent = ready ? "Choose the role you are working as." : "Enter the ID and password first, then choose your role.";
  $("slBtn").disabled = !ready || !role.value;
}
async function renderIdentity() {
  const s = await loadSettings();
  const ids = await siteIds();
  const states = (await chrome.storage.local.get("siteState")).siteState ?? {};
  for (const sel of [$("credSite"), $("trialSite")]) {
    const keep = sel.value;
    sel.replaceChildren(...s.origins.map((o) => Object.assign(document.createElement("option"), { value: o, textContent: `${hostOf(o) ?? o}${ids[o]?.website_id ?? states[o]?.website_id ? ` \xB7 ${ids[o]?.website_id ?? states[o]?.website_id}` : ""}` })));
    if (keep && s.origins.includes(keep)) sel.value = keep;
  }
  renderTrial(states, ids);
}
function renderTrial(states, ids) {
  const sel = $("trialSite"), btn = $("startTrial"), out = $("trialState"), timer = $("timer");
  clearInterval(tick);
  const o = sel.value;
  if (!o) {
    out.textContent = "Authorise a website and generate its ID to start the trial.";
    timer.hidden = true;
    btn.disabled = true;
    return;
  }
  const st = states[o];
  const wid = ids[o]?.website_id ?? st?.website_id ?? null;
  const view = trialView(st ? { ends_at: st.premium.trial_ends_at, used: !!st.premium.trial_used || !!st.premium.trial_ends_at } : void 0, st?.premium);
  const draw = () => {
    const left = st?.premium.trial_ends_at ? Date.parse(st.premium.trial_ends_at) - Date.now() : 0;
    if (view.phase === "active") {
      timer.hidden = false;
      timer.textContent = formatCountdown(left);
      out.textContent = `Premium is on for ${wid ?? hostOf(o)} until the timer ends.`;
      if (left <= 0) {
        clearInterval(tick);
        void ask({ kind: "site:heartbeat" });
      }
    }
  };
  btn.disabled = true;
  timer.hidden = view.phase !== "active";
  if (view.phase === "org") out.textContent = "Premium is active for your organisation. No trial needed.";
  else if (view.phase === "active") {
    draw();
    tick = setInterval(draw, 1e3);
  } else if (view.phase === "ended") out.textContent = `The free trial for ${wid ?? "this website ID"} has ended. It can be used once per website ID.`;
  else if (!wid) out.textContent = "Generate a website ID for this site first (step 4).";
  else {
    out.textContent = `Try every Premium feature on ${wid} for 72 hours. No card needed.`;
    btn.disabled = false;
  }
}
async function initIdentity(onChange) {
  if (wired) return;
  wired = true;
  $("freeList").replaceChildren(...FREE_FEATURES.map((f) => li(f)));
  $("premList").replaceChildren(...PREMIUM_FEATURES.map((f) => li(f.text, f.title)));
  $("slRole").replaceChildren(Object.assign(document.createElement("option"), { value: "", textContent: "Choose a role\u2026" }), ...SITE_ROLES.map(([v, l]) => Object.assign(document.createElement("option"), { value: v, textContent: l })));
  const pass = $("slPass");
  $("peek").addEventListener("click", () => setPeek(pass, $("peek"), pass.type === "password"));
  for (const id of ["slId", "slPass"]) $(id).addEventListener("input", syncSignIn);
  $("slRole").addEventListener("change", syncSignIn);
  $("trialSite").addEventListener("change", () => void renderIdentity());
  $("genCreds").addEventListener("click", async () => {
    const origin = $("credSite").value;
    const msg = $("msg");
    if (!origin) return void (msg.textContent = "Authorise a website first.");
    const ids = await siteIds();
    const name = ids[origin]?.name || $("siteName").value, owner = ids[origin]?.owner_name || $("ownerName").value;
    if (!name.trim() || !owner.trim()) return void (msg.textContent = "Enter the website name and owner name in the authorise card first.");
    const btn = $("genCreds");
    btn.disabled = true;
    msg.textContent = "Generating website ID and password\u2026";
    const r = await ask({ kind: "site:register", origin, name, owner, generate: true });
    btn.disabled = false;
    if (!r.ok || !r.website_id || !r.password) return void (msg.textContent = r.error ?? "Could not generate credentials.");
    showCreds(r.website_id, r.password);
    $("slId").value = r.website_id;
    $("slPass").value = r.password;
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
    status.textContent = "Signing in\u2026";
    const r = await ask({ kind: "site:login", websiteId: $("slId").value, password: pass.value, role: $("slRole").value });
    if (r.ok) {
      status.textContent = `Signed in as ${r.who} (${r.role?.replace("_", " ")}). Open the dashboard and use the Website ID tab with the same details. You will see this website only.`;
      $("openDash").hidden = false;
      await chrome.storage.session.set({ signedIn: true });
    } else status.textContent = r.error ?? "Sign in failed.";
    pass.value = "";
    setPeek(pass, $("peek"), false);
    syncSignIn();
    onChange();
  });
  $("openDash").addEventListener("click", async () => void chrome.tabs.create({ url: (await loadSettings()).dashboardUrl }));
  $("startTrial").addEventListener("click", async () => {
    const o = $("trialSite").value;
    const btn = $("startTrial");
    btn.disabled = true;
    $("trialState").textContent = "Starting the 72-hour trial\u2026";
    const r = await ask({ kind: "trial:start", origin: o });
    if (!r.ok) $("trialState").textContent = r.error ?? "Could not start the trial.";
    await renderIdentity();
    onChange();
  });
  syncSignIn();
  await renderIdentity();
}

// src/settings/sites.ts
var SCOPES = ["session", "user_data", "finance", "cookies"];
var wired2 = false;
function scopeRow(s, on) {
  const c = SCOPE_COPY[s];
  const l = document.createElement("label");
  l.className = "check scope";
  const i = document.createElement("input");
  i.type = "checkbox";
  i.dataset.scope = s;
  i.checked = on || c.required;
  i.disabled = c.required;
  const t = document.createElement("span");
  const b = document.createElement("b");
  b.textContent = `${c.title}${c.required ? " \xB7 required" : " \xB7 optional"}`;
  const r = document.createElement("span");
  r.className = "note";
  r.textContent = ` Reads: ${c.reads} Never reads: ${c.never}`;
  t.append(b, document.createElement("br"), r);
  l.append(i, t);
  return l;
}
async function renderConsent() {
  const s = await loadSettings();
  const have = new Set(s.consent?.scopes ?? []);
  $("scopes").replaceChildren(...SCOPES.map((x) => scopeRow(x, have.has(x))));
  $("owner").checked = !!s.consent;
  $("consentStatus").textContent = monitoringAllowed(s.consent) ? `Granted ${new Date(s.consent.acceptedAt).toLocaleString()}: ${s.consent.scopes.join(", ")}.` : "Not granted yet. Site authorisation stays locked and monitoring stays off until the required permissions are granted.";
  if (wired2) return;
  wired2 = true;
  $("grant").addEventListener("click", async () => {
    const msg = $("consentStatus");
    const picked = [...document.querySelectorAll("#scopes input")].filter((i) => i.checked || i.disabled).map((i) => i.dataset.scope);
    if (!REQUIRED_SCOPES.every((r) => picked.includes(r))) return void (msg.textContent = "Session and usage data are both required for real-time monitoring.");
    if (!$("owner").checked) return void (msg.textContent = "Confirm that you own or are authorised to monitor this website.");
    if (picked.includes("cookies") && !await chrome.permissions.request({ permissions: ["cookies"] })) {
      picked.splice(picked.indexOf("cookies"), 1);
      msg.textContent = "Cookie summary declined by the browser; the other permissions were saved.";
    }
    await saveSettings({ consent: { scopes: picked, acceptedAt: (/* @__PURE__ */ new Date()).toISOString(), extensionVersion: chrome.runtime.getManifest().version } });
    await ask({ kind: "site:heartbeat" });
    await renderConsent();
  });
  $("withdraw").addEventListener("click", async () => {
    await saveSettings({ consent: null, monitoring: false });
    await chrome.permissions.remove({ permissions: ["cookies"] }).catch(() => false);
    await ask({ kind: "site:heartbeat" });
    await renderConsent();
    $("consentStatus").textContent = "Consent withdrawn. Monitoring is off, no further data is sent and site authorisation is locked again.";
  });
}

// src/settings/settings.ts
var say = (t) => {
  $("msg").textContent = t;
};
function flow(done) {
  const order = ["connect", "consent", "authorise", "creds", "signin", "plan"];
  const first = order.find((k) => !done[k]);
  document.querySelectorAll("#flow li").forEach((li2) => {
    const k = li2.dataset.step;
    li2.className = done[k] ? "done" : k === first ? "now" : "";
  });
}
async function render() {
  const s = await loadSettings();
  const consented = monitoringAllowed(s.consent);
  const { status, siteState } = await chrome.storage.local.get(["status", "siteState"]);
  const states = siteState ?? {};
  const ids = await siteIds();
  const signed = !!(await chrome.storage.session.get("signedIn")).signedIn;
  $("backend").value = s.backendUrl;
  $("dashUrl").value = s.dashboardUrl;
  $("key").placeholder = s.ingestKey ? "Saved (hidden). Enter a new key to replace it." : "chn_live_\u2026";
  await renderConsent();
  locked($("auth"), !consented);
  locked($("credsCard"), !s.origins.length || !consented);
  const ready = !!s.ingestKey && s.origins.length > 0 && consented;
  const first = s.origins.map((o) => states[o]).find(Boolean);
  $("led").className = `led ${s.monitoring && ready ? status?.ok === false ? "bad" : "on" : ""}`;
  $("stateText").textContent = s.monitoring && ready ? "Monitoring live" : s.ingestKey ? "Connected, monitoring off" : "Not connected";
  $("rttChip").textContent = first?.rtt_ms ? `ping ${first.rtt_ms} ms` : "ping \u2013 ms";
  $("statusLine").textContent = status ? `${status.message} (${new Date(status.at).toLocaleTimeString()})` : "Nothing sent yet.";
  const tog = $("monitorToggle");
  tog.checked = s.monitoring;
  tog.disabled = !ready && !s.monitoring;
  const ul = $("origins");
  ul.replaceChildren(...(s.origins.length ? s.origins : []).map((o) => {
    const li2 = document.createElement("li");
    const t = document.createElement("span");
    t.className = "grow";
    t.textContent = `${o}${ids[o] ? `  \xB7  ${ids[o].name || ""}` : ""}`;
    const st = states[o];
    const pills = [
      ids[o]?.website_id && Object.assign(document.createElement("span"), { className: "chip", textContent: ids[o].website_id }),
      st && Object.assign(document.createElement("span"), { className: `pill ${st.premium.active ? "ok" : ""}`, textContent: st.premium.active ? "premium" : "free" }),
      st && Object.assign(document.createElement("span"), { className: `pill ${st.capture.state === "running" ? "ok" : "warn"}`, textContent: `capture ${st.capture.state}` })
    ].filter(Boolean);
    const b = document.createElement("button");
    b.type = "button";
    b.className = "secondary";
    b.textContent = "Revoke";
    b.addEventListener("click", async () => {
      await ask({ kind: "revoke", origin: o });
      say(`Revoked ${o}.`);
      await render();
    });
    li2.append(t, ...pills, b);
    return li2;
  }));
  if (!s.origins.length) ul.replaceChildren(Object.assign(document.createElement("li"), { textContent: "No authorised websites yet." }));
  await renderIdentity();
  flow({ connect: !!s.ingestKey, consent: consented, authorise: s.origins.length > 0, creds: Object.values(ids).some((i) => i.website_id), signin: signed, plan: Object.values(states).some((x) => x.premium.active) });
}
$("conn").addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = normalizeOrigin($("backend").value);
  if (!url) return say("Enter a valid http(s) backend URL.");
  const granted = await chrome.permissions.request({ origins: [`${url}/*`] });
  if (!granted) return say("Permission to reach the backend was declined.");
  const key = $("key").value.trim();
  const dash = normalizeOrigin($("dashUrl").value);
  await saveSettings({ backendUrl: url, ...key ? { ingestKey: key } : {}, ...dash ? { dashboardUrl: dash } : {} });
  $("key").value = "";
  say("Connection saved.");
  await ask({ kind: "site:heartbeat" });
  await render();
});
$("monitorToggle").addEventListener("change", async () => {
  await saveSettings({ monitoring: $("monitorToggle").checked });
  await ask({ kind: "sync" });
  await ask({ kind: "site:heartbeat" });
  await render();
});
$("auth").addEventListener("submit", async (e) => {
  e.preventDefault();
  const ok = await authoriseSite();
  if (ok) $("credsCard").scrollIntoView({ behavior: "smooth", block: "center" });
  await render();
});
chrome.storage.onChanged.addListener((c) => {
  if (c.siteState || c.status || c.siteIds) void render();
});
void initIdentity(() => void render()).then(render);
//# sourceMappingURL=settings.js.map
