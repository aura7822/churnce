import { loadSettings, saveSettings } from "../shared/config";
import { failedChecks, type Draft } from "../shared/outreach";

/** Customer-email section of the settings window. Every backend call goes through the service worker. */
const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const say = (t: string) => { $("mailStatus").textContent = t; };
type Reply = { ok: boolean; error?: string; drafts?: Draft[]; operator?: { name: string } };
const ask = (m: Record<string, unknown>) => chrome.runtime.sendMessage(m) as Promise<Reply>;

function field(label: string, el: HTMLElement): HTMLLabelElement {
  const l = document.createElement("label");
  l.append(label, el);
  return l;
}

function renderDraft(d: Draft): HTMLElement {
  const box = document.createElement("details");
  box.className = "draft";
  const sum = document.createElement("summary");
  sum.textContent = d.subject || "(no subject)";
  const badge = document.createElement("span");
  badge.className = "badge";
  badge.textContent = d.status;
  sum.append(badge);
  const fails = failedChecks(d);
  if (d.holdout || fails.length) { const b = document.createElement("span"); b.className = "badge bad"; b.textContent = d.holdout ? "holdout" : "policy"; sum.append(b); }
  box.append(sum);

  const meta = document.createElement("p");
  meta.className = "meta";
  meta.textContent = `To ${d.recipient ?? d.customer_ref ?? "customer"} · ${d.generated_by} · ${d.delivery_mode === "smtp" ? "will be delivered by email" : "simulated delivery (SMTP not configured)"}`;
  const subject = document.createElement("input");
  subject.value = d.subject;
  subject.maxLength = 120;
  const body = document.createElement("textarea");
  body.value = d.body;
  body.maxLength = 1500;
  const problems = document.createElement("p");
  problems.className = "note";
  problems.textContent = fails.length ? `Blocked by: ${fails.map((c) => c.detail || c.name).join("; ")}` : "";

  const run = async (btn: HTMLButtonElement, m: Record<string, unknown>, ok: string) => {
    btn.disabled = true;
    const r = await ask(m);
    btn.disabled = false;
    if (!r.ok) return say(r.error ?? "Failed.");
    say(ok);
    if (r.drafts) renderDrafts(r.drafts);
  };
  const save = document.createElement("button"); save.type = "button"; save.className = "secondary"; save.textContent = "Save edit";
  save.addEventListener("click", () => void run(save, { kind: "emails:save", id: d.id, subject: subject.value, body: body.value }, "Saved. It needs approval again before sending."));
  const send = document.createElement("button"); send.type = "button"; send.textContent = "Send now";
  send.disabled = d.holdout || fails.length > 0;
  send.addEventListener("click", () => {
    const edited = subject.value !== d.subject || body.value !== d.body;
    if (edited) return say("Save your edit first.");
    void run(send, { kind: "emails:send", id: d.id }, d.delivery_mode === "smtp" ? "Sent." : "Recorded as a simulated send.");
  });
  const reject = document.createElement("button"); reject.type = "button"; reject.className = "secondary"; reject.textContent = "Reject";
  reject.addEventListener("click", () => void run(reject, { kind: "emails:reject", id: d.id }, "Rejected."));
  const actions = document.createElement("div");
  actions.className = "actions";
  actions.append(save, send, reject);
  box.append(meta, field("Subject", subject), field("Message", body), problems, actions);
  return box;
}

function renderDrafts(drafts: Draft[]): void {
  const list = $("drafts");
  list.replaceChildren(...(drafts.length ? drafts.map(renderDraft) : [Object.assign(document.createElement("p"), { className: "note", textContent: "No drafts waiting. They appear after an issue has a verified fix." })]));
}

async function render(): Promise<void> {
  const s = await loadSettings();
  const { operator } = (await chrome.storage.session.get("operator")) as { operator?: { name: string; role: string } };
  const { drafts, outreachStatus } = (await chrome.storage.local.get(["drafts", "outreachStatus"])) as { drafts?: Draft[]; outreachStatus?: { message: string; at: string } };
  $<HTMLInputElement>("retrieve").checked = s.emailRetrieve;
  $<HTMLInputElement>("auto").checked = s.emailAutoSend;
  $<HTMLInputElement>("auto").disabled = !s.emailRetrieve;
  $<HTMLSelectElement>("delay").value = String(s.emailAutoSendDelayMin);
  $("login").hidden = !!operator;
  $("signed").hidden = !operator;
  $("who").textContent = operator ? `Signed in as ${operator.name} (${operator.role.replace("_", " ")})` : "";
  if (outreachStatus) say(`${outreachStatus.message} (${new Date(outreachStatus.at).toLocaleTimeString()})`);
  renderDrafts(operator && s.emailRetrieve ? drafts ?? [] : []);
}

$("login").addEventListener("submit", async (e) => {
  e.preventDefault();
  const r = await ask({ kind: "auth:login", email: $<HTMLInputElement>("opEmail").value.trim(), password: $<HTMLInputElement>("opPass").value });
  $<HTMLInputElement>("opPass").value = "";
  if (!r.ok) return say(r.error ?? "Sign-in failed.");
  say("Signed in.");
  await render();
  if ((await loadSettings()).emailRetrieve) void $("refresh").click();
});
$("logout").addEventListener("click", async () => { await ask({ kind: "auth:logout" }); say("Signed out."); await render(); });
$("retrieve").addEventListener("change", async (e) => {
  const on = (e.target as HTMLInputElement).checked;
  await saveSettings({ emailRetrieve: on, ...(on ? {} : { emailAutoSend: false }) });
  await render();
  if (on) void $("refresh").click();
});
$("auto").addEventListener("change", async (e) => {
  const on = (e.target as HTMLInputElement).checked;
  if (on && !confirm("Eligible emails will be sent to customers without a final click from you. Continue?")) { (e.target as HTMLInputElement).checked = false; return; }
  await saveSettings({ emailAutoSend: on });
  say(on ? "Auto-send is on." : "Auto-send is off.");
});
$("delay").addEventListener("change", async (e) => { await saveSettings({ emailAutoSendDelayMin: Number((e.target as HTMLSelectElement).value) }); });
$("refresh").addEventListener("click", async () => {
  const r = await ask({ kind: "emails:refresh" });
  if (!r.ok) return say(r.error ?? "Could not refresh.");
  say(`${r.drafts?.length ?? 0} draft(s).`);
  renderDrafts(r.drafts ?? []);
});

void render();
