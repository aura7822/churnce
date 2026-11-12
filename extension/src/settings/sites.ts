import { loadSettings, saveSettings } from "../shared/config";
import { monitoringAllowed, REQUIRED_SCOPES, SCOPE_COPY, type Scope } from "../shared/consent";
import { $, ask } from "./ui";

/** Step 2: explicit, scoped owner consent. It comes BEFORE site authorisation, which stays locked until it is granted. */
const SCOPES: Scope[] = ["session", "user_data", "finance", "cookies"];
let wired = false;

function scopeRow(s: Scope, on: boolean): HTMLElement {
  const c = SCOPE_COPY[s];
  const l = document.createElement("label");
  l.className = "check scope";
  const i = document.createElement("input");
  i.type = "checkbox"; i.dataset.scope = s; i.checked = on || c.required; i.disabled = c.required;
  const t = document.createElement("span");
  const b = document.createElement("b");
  b.textContent = `${c.title}${c.required ? " · required" : " · optional"}`;
  const r = document.createElement("span");
  r.className = "note"; r.textContent = ` Reads: ${c.reads} Never reads: ${c.never}`;
  t.append(b, document.createElement("br"), r);
  l.append(i, t);
  return l;
}

export async function renderConsent(): Promise<void> {
  const s = await loadSettings();
  const have = new Set(s.consent?.scopes ?? []);
  $("scopes").replaceChildren(...SCOPES.map((x) => scopeRow(x, have.has(x))));
  $<HTMLInputElement>("owner").checked = !!s.consent;
  $("consentStatus").textContent = monitoringAllowed(s.consent)
    ? `Granted ${new Date(s.consent!.acceptedAt).toLocaleString()}: ${s.consent!.scopes.join(", ")}.`
    : "Not granted yet. Site authorisation stays locked and monitoring stays off until the required permissions are granted.";
  if (wired) return;
  wired = true;

  $("grant").addEventListener("click", async () => {
    const msg = $("consentStatus");
    const picked = [...document.querySelectorAll<HTMLInputElement>("#scopes input")].filter((i) => i.checked || i.disabled).map((i) => i.dataset.scope as Scope);
    if (!REQUIRED_SCOPES.every((r) => picked.includes(r))) return void (msg.textContent = "Session and usage data are both required for real-time monitoring.");
    if (!$<HTMLInputElement>("owner").checked) return void (msg.textContent = "Confirm that you own or are authorised to monitor this website.");
    if (picked.includes("cookies") && !(await chrome.permissions.request({ permissions: ["cookies"] }))) {
      picked.splice(picked.indexOf("cookies"), 1);
      msg.textContent = "Cookie summary declined by the browser; the other permissions were saved.";
    }
    await saveSettings({ consent: { scopes: picked, acceptedAt: new Date().toISOString(), extensionVersion: chrome.runtime.getManifest().version } });
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
