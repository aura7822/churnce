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

// src/shared/consent.ts
var REQUIRED_SCOPES = ["session", "user_data"];
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

// src/shared/trial.ts
function formatCountdown(ms) {
  const t = Math.max(0, Math.floor(ms / 1e3));
  const p = (n) => String(n).padStart(2, "0");
  return `${p(Math.floor(t / 3600))}:${p(Math.floor(t % 3600 / 60))}:${p(t % 60)}`;
}

// src/popup/popup.ts
var $ = (id) => document.getElementById(id);
var tick;
async function render() {
  const s = await loadSettings();
  const { status, queue, siteState } = await chrome.storage.local.get(["status", "queue", "siteState"]);
  const states = siteState ?? {};
  const consented = monitoringAllowed(s.consent);
  const ready = !!s.ingestKey && s.origins.length > 0 && consented;
  $("led").className = `led ${s.monitoring && ready ? status?.ok === false ? "bad" : "on" : ""}`;
  $("stateText").textContent = s.monitoring ? "Monitoring" : "Off";
  const rtt = s.origins.map((o) => states[o]?.rtt_ms).find(Boolean);
  $("rtt").textContent = rtt ? `ping ${rtt} ms` : "ping \u2013 ms";
  $("toggle").textContent = s.monitoring ? "Turn off" : "Turn on";
  $("toggle").disabled = !ready && !s.monitoring;
  $("sites").textContent = !s.origins.length ? "No authorised sites yet. Add one in settings." : consented ? "" : "Owner consent not granted yet. Open settings to grant permissions.";
  $("siteList").replaceChildren(...s.origins.map((o) => {
    const st = states[o];
    const row = document.createElement("div");
    row.className = "site-row";
    const name = document.createElement("span");
    name.className = "mono";
    name.textContent = hostOf(o) ?? o;
    const pill = document.createElement("span");
    const ends = st?.premium.trial_ends_at ? Date.parse(st.premium.trial_ends_at) : NaN;
    const label = st?.premium.active ? st.premium.source === "trial" && Number.isFinite(ends) ? `trial ${formatCountdown(ends - Date.now())}` : "premium" : "free";
    pill.className = `pill ${st?.premium.active ? "ok" : ""}`;
    pill.textContent = `${label}${st ? ` \xB7 ${st.capture.state}` : ""}`;
    row.append(name, pill);
    return row;
  }));
  $("status").textContent = status ? `${status.message} (${new Date(status.at).toLocaleTimeString()})` : "Nothing sent yet.";
  $("queue").textContent = `${queue?.length ?? 0} event(s) waiting to send`;
}
$("toggle").addEventListener("click", async () => {
  const s = await loadSettings();
  await saveSettings({ monitoring: !s.monitoring });
  await chrome.runtime.sendMessage({ kind: "sync" });
  await render();
});
$("settings").addEventListener("click", () => void chrome.runtime.openOptionsPage());
chrome.storage.onChanged.addListener(() => void render());
tick = setInterval(() => void render(), 1e3);
window.addEventListener("pagehide", () => clearInterval(tick));
void render();
//# sourceMappingURL=popup.js.map
