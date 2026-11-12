import { loadSettings, normalizeOrigin, saveSettings } from "../shared/config";
import { monitoringAllowed } from "../shared/consent";
import { authoriseSite } from "./authorise";
import { initIdentity, renderIdentity } from "./identity";
import { renderConsent } from "./sites";
import { $, ask, locked, siteIds } from "./ui";

const say = (t: string) => { $("msg").textContent = t; };
type State = { premium: { active: boolean }; capture: { state: string }; rtt_ms: number | null };

function flow(done: Record<string, boolean>): void {
  const order = ["connect", "consent", "authorise", "creds", "signin", "plan"];
  const first = order.find((k) => !done[k]);
  document.querySelectorAll<HTMLElement>("#flow li").forEach((li) => { const k = li.dataset.step!; li.className = done[k] ? "done" : k === first ? "now" : ""; });
}

async function render(): Promise<void> {
  const s = await loadSettings();
  const consented = monitoringAllowed(s.consent);
  const { status, siteState } = await chrome.storage.local.get(["status", "siteState"]);
  const states = (siteState ?? {}) as Record<string, State>;
  const ids = await siteIds();
  const signed = !!(await chrome.storage.session.get("signedIn")).signedIn;

  $<HTMLInputElement>("backend").value = s.backendUrl;
  $<HTMLInputElement>("dashUrl").value = s.dashboardUrl;
  $<HTMLInputElement>("key").placeholder = s.ingestKey ? "Saved (hidden). Enter a new key to replace it." : "chn_live_…";
  await renderConsent();
  locked($("auth"), !consented); // owner consent comes before site authorisation
  locked($("credsCard"), !s.origins.length || !consented);

  const ready = !!s.ingestKey && s.origins.length > 0 && consented;
  const first = s.origins.map((o) => states[o]).find(Boolean);
  $("led").className = `led ${s.monitoring && ready ? (status?.ok === false ? "bad" : "on") : ""}`;
  $("stateText").textContent = s.monitoring && ready ? "Monitoring live" : s.ingestKey ? "Connected, monitoring off" : "Not connected";
  $("rttChip").textContent = first?.rtt_ms ? `ping ${first.rtt_ms} ms` : "ping – ms";
  $("statusLine").textContent = status ? `${status.message} (${new Date(status.at).toLocaleTimeString()})` : "Nothing sent yet.";
  const tog = $<HTMLInputElement>("monitorToggle");
  tog.checked = s.monitoring; tog.disabled = !ready && !s.monitoring;

  await renderIdentity();
  document.body.classList.remove("loading");
  flow({ connect: !!s.ingestKey, consent: consented, authorise: s.origins.length > 0, creds: Object.values(ids).some((i) => i.website_id), signin: signed, plan: Object.values(states).some((x) => x.premium.active) });
}

$("conn").addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = normalizeOrigin($<HTMLInputElement>("backend").value);
  if (!url) return say("Enter a valid http(s) backend URL.");
  const granted = await chrome.permissions.request({ origins: [`${url}/*`] }); // lets the worker POST to the backend
  if (!granted) return say("Permission to reach the backend was declined.");
  const key = $<HTMLInputElement>("key").value.trim();
  const dash = normalizeOrigin($<HTMLInputElement>("dashUrl").value);
  await saveSettings({ backendUrl: url, ...(key ? { ingestKey: key } : {}), ...(dash ? { dashboardUrl: dash } : {}) });
  $<HTMLInputElement>("key").value = "";
  say("Connection saved.");
  await ask({ kind: "site:heartbeat" });
  await render();
});

$("monitorToggle").addEventListener("change", async () => {
  await saveSettings({ monitoring: $<HTMLInputElement>("monitorToggle").checked });
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

chrome.storage.onChanged.addListener((c) => { if (c.siteState || c.status || c.siteIds) void render(); });
void initIdentity(() => void render()).then(render);
