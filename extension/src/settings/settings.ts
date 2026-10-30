import { loadSettings, normalizeOrigin, saveSettings } from "../shared/config";
import "./mail";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const say = (t: string) => { $("msg").textContent = t; };

async function render(): Promise<void> {
  const s = await loadSettings();
  $<HTMLInputElement>("backend").value = s.backendUrl;
  $<HTMLInputElement>("key").placeholder = s.ingestKey ? "Saved (hidden). Enter a new key to replace it." : "chn_live_…";
  const ul = $("origins");
  ul.replaceChildren(...s.origins.map((o) => {
    const li = document.createElement("li");
    li.textContent = `${o} `;
    const b = document.createElement("button");
    b.type = "button"; b.className = "secondary"; b.textContent = "Revoke";
    b.addEventListener("click", async () => { await chrome.runtime.sendMessage({ kind: "revoke", origin: o }); say(`Revoked ${o}.`); await render(); });
    li.append(b);
    return li;
  }));
}

$("conn").addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = normalizeOrigin($<HTMLInputElement>("backend").value);
  if (!url) return say("Enter a valid http(s) backend URL.");
  const granted = await chrome.permissions.request({ origins: [`${url}/*`] }); // lets the worker POST to the backend
  if (!granted) return say("Permission to reach the backend was declined.");
  const key = $<HTMLInputElement>("key").value.trim();
  await saveSettings({ backendUrl: url, ...(key ? { ingestKey: key } : {}) });
  $<HTMLInputElement>("key").value = "";
  say("Connection saved.");
  await render();
});

$("auth").addEventListener("submit", async (e) => {
  e.preventDefault();
  const origin = normalizeOrigin($<HTMLInputElement>("origin").value);
  if (!origin) return say("Enter a valid website address.");
  const granted = await chrome.permissions.request({ origins: [`${origin}/*`] });
  if (!granted) return say("Permission declined. Nothing will be observed on that site.");
  const r = (await chrome.runtime.sendMessage({ kind: "authorize", origin })) as { ok: boolean };
  say(r?.ok ? `Authorised ${origin}. Turn monitoring on from the toolbar popup.` : "Could not authorise that site.");
  $<HTMLInputElement>("origin").value = "";
  await render();
});

void render();
