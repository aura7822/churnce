import { loadSettings, saveSettings } from "../shared/config";
import { getStoredTheme, initTheme, toggleTheme } from "../shared/theme";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

function syncThemeButton(): void {
  const mode = getStoredTheme();
  $<HTMLButtonElement>("themeToggle").textContent = mode === "dark" ? "Light mode" : "Dark mode";
  $<HTMLButtonElement>("themeToggle").setAttribute("aria-label", `Switch to ${mode === "dark" ? "light" : "dark"} mode`);
}

async function render(): Promise<void> {
  const s = await loadSettings();
  const { status, queue } = await chrome.storage.local.get(["status", "queue"]);
  const ready = !!s.ingestKey && s.origins.length > 0;
  $("led").className = `led ${s.monitoring && ready ? (status?.ok === false ? "bad" : "on") : ""}`;
  $("stateText").textContent = s.monitoring ? "Monitoring" : "Off";
  $<HTMLButtonElement>("toggle").textContent = s.monitoring ? "Turn off" : "Turn on";
  $<HTMLButtonElement>("toggle").disabled = !ready && !s.monitoring;
  $("sites").textContent = s.origins.length ? `Authorised: ${s.origins.join(", ")}` : "No authorised sites yet. Add one in settings.";
  $("status").textContent = status ? `${status.message} (${new Date(status.at).toLocaleTimeString()})` : "Nothing sent yet.";
  $("queue").textContent = `${(queue as unknown[] | undefined)?.length ?? 0} event(s) waiting to send`;
  syncThemeButton();
}

$("toggle").addEventListener("click", async () => {
  const s = await loadSettings();
  await saveSettings({ monitoring: !s.monitoring });
  await chrome.runtime.sendMessage({ kind: "sync" });
  await render();
});
$("themeToggle").addEventListener("click", () => {
  toggleTheme();
  syncThemeButton();
});
$("settings").addEventListener("click", () => void chrome.runtime.openOptionsPage());
chrome.storage.onChanged.addListener(() => void render());
initTheme();
void render();
