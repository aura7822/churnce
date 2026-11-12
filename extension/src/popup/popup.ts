import { loadSettings, saveSettings } from "../shared/config";
import { hostOf, monitoringAllowed } from "../shared/consent";
import { formatCountdown } from "../shared/trial";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
type State = { premium: { active: boolean; source: string | null; trial_ends_at: string | null }; capture: { state: string }; rtt_ms: number | null };
let tick: ReturnType<typeof setInterval> | undefined;

async function render(): Promise<void> {
  const s = await loadSettings();
  const { status, queue, siteState } = await chrome.storage.local.get(["status", "queue", "siteState"]);
  const states = (siteState ?? {}) as Record<string, State>;
  const consented = monitoringAllowed(s.consent);
  const ready = !!s.ingestKey && s.origins.length > 0 && consented;
  $("led").className = `led ${s.monitoring && ready ? (status?.ok === false ? "bad" : "on") : ""}`;
  $("stateText").textContent = s.monitoring ? "Monitoring" : "Off";
  const rtt = s.origins.map((o) => states[o]?.rtt_ms).find(Boolean);
  $("rtt").textContent = rtt ? `ping ${rtt} ms` : "ping – ms";
  $<HTMLButtonElement>("toggle").textContent = s.monitoring ? "Turn off" : "Turn on";
  $<HTMLButtonElement>("toggle").disabled = !ready && !s.monitoring;
  $("sites").textContent = !s.origins.length ? "No authorised sites yet. Add one in settings." : consented ? "" : "Owner consent not granted yet. Open settings to grant permissions.";
  $("siteList").replaceChildren(...s.origins.map((o) => {
    const st = states[o];
    const row = document.createElement("div");
    row.className = "site-row";
    const name = document.createElement("span");
    name.className = "mono"; name.textContent = hostOf(o) ?? o;
    const pill = document.createElement("span");
    const ends = st?.premium.trial_ends_at ? Date.parse(st.premium.trial_ends_at) : NaN;
    const label = st?.premium.active ? (st.premium.source === "trial" && Number.isFinite(ends) ? `trial ${formatCountdown(ends - Date.now())}` : "premium") : "free";
    pill.className = `pill ${st?.premium.active ? "ok" : ""}`; pill.textContent = `${label}${st ? ` · ${st.capture.state}` : ""}`;
    row.append(name, pill);
    return row;
  }));
  $("status").textContent = status ? `${status.message} (${new Date(status.at).toLocaleTimeString()})` : "Nothing sent yet.";
  $("queue").textContent = `${(queue as unknown[] | undefined)?.length ?? 0} event(s) waiting to send`;
  document.body.classList.remove("loading");
}

$("toggle").addEventListener("click", async () => {
  const s = await loadSettings();
  await saveSettings({ monitoring: !s.monitoring });
  await chrome.runtime.sendMessage({ kind: "sync" });
  await render();
});
$("settings").addEventListener("click", () => void chrome.runtime.openOptionsPage());
chrome.storage.onChanged.addListener(() => void render());
tick = setInterval(() => void render(), 1000);
window.addEventListener("pagehide", () => clearInterval(tick));
void render();
