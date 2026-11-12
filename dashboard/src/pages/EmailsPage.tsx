import { useEffect, useState } from "react";
import { api } from "../services/api";
import { useResource } from "../hooks/useLive";
import { useAuth } from "../hooks/useAuth";
import { useToast } from "../hooks/useToast";
import type { Email } from "../types";
import { Badge, Banner, Button, Card, Empty, ErrorNote, PageHead, PolicyChecks, Skeleton, StateBadge, Toggle } from "../components/ui";
import { IconCheck, IconClock, IconMail, IconSave, IconSend, IconX } from "../components/icons";
import { ago, dateTimeOf, num } from "../services/format";

const EDITABLE = new Set(["draft", "approved"]);

function Counter({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return <div className={`mail-counter ${tone ?? ""}`}><b>{num(value)}</b><span>{label}</span></div>;
}

function DraftCard({ e, onChanged, canAct }: { e: Email; onChanged: () => void; canAct: boolean }) {
  const toast = useToast();
  const [subject, setSubject] = useState(e.subject);
  const [body, setBody] = useState(e.body);
  const [busy, setBusy] = useState<string | null>(null);
  useEffect(() => { setSubject(e.subject); setBody(e.body); }, [e.id, e.subject, e.body]);
  const dirty = subject !== e.subject || body !== e.body;
  const editable = EDITABLE.has(e.status) && canAct;

  async function run(kind: "save" | "approve" | "send" | "reject") {
    setBusy(kind);
    try {
      if (kind === "save" || (dirty && kind !== "reject")) await api.editEmail(e.id, subject.trim(), body.trim());
      if (kind === "approve" || (kind === "send" && e.status === "draft")) await api.approveEmail(e.id);
      if (kind === "send") await api.sendEmail(e.id);
      if (kind === "reject") await api.rejectEmail(e.id);
      toast.ok(kind === "save" ? "Draft saved." : kind === "approve" ? "Email approved." : kind === "send" ? "Email sent (or recorded as simulated when SMTP is off)." : "Email rejected.");
      onChanged();
    } catch (err) { toast.err((err as Error).message); } finally { setBusy(null); }
  }

  return (
    <article className="mail-draft" aria-label={`Draft to ${e.customer_ref ?? "customer"}`}>
      <header className="row">
        <span className="chip-address">{e.customer_ref ?? "customer"}</span>
        <span className="hint mono">{e.recipient ?? "address on file"}</span>
        <span className="spacer" />
        <StateBadge state={e.status} />
        {e.holdout && <Badge tone="blue">Holdout</Badge>}
      </header>
      <label className="field"><span className="label">Subject</span>
        <input className="input" value={subject} maxLength={120} disabled={!editable} onChange={(x) => setSubject(x.target.value)} />
      </label>
      <label className="field"><span className="label">Message</span>
        <textarea className="input" rows={6} value={body} maxLength={1500} disabled={!editable} onChange={(x) => setBody(x.target.value)} />
      </label>
      {e.policy_result.checks && e.policy_result.checks.length > 0 && <PolicyChecks checks={e.policy_result.checks} />}
      <footer className="row">
        <span className="hint">{e.generated_by ? `Drafted by ${e.generated_by} · ` : ""}{ago(e.created_at)}</span>
        <span className="spacer" />
        {!canAct && EDITABLE.has(e.status) && <span className="hint">View only: your role cannot edit or send emails.</span>}
        {editable && <>
          <Button variant="ghost" busy={busy === "reject"} icon={<IconX />} onClick={() => void run("reject")}>Reject</Button>
          <Button variant="neu" busy={busy === "save"} icon={<IconSave />} disabled={!dirty} onClick={() => void run("save")}>Save edits</Button>
          {e.status === "draft" && <Button variant="neu" busy={busy === "approve"} icon={<IconCheck />} onClick={() => void run("approve")}>Approve</Button>}
          <Button variant="clay" busy={busy === "send"} icon={<IconSend />} onClick={() => void run("send")}>Send now</Button>
        </>}
      </footer>
    </article>
  );
}

export function EmailsPage() {
  const { me, can } = useAuth();
  const canAct = can("emails:approve");
  const toast = useToast();
  const summary = useResource(api.emailsSummary, ["emails", "metrics"]);
  const list = useResource(api.emails, ["emails"]);
  const s = summary.data;
  const [enabled, setEnabled] = useState(false);
  const [delay, setDelay] = useState(10);
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (s) { setEnabled(s.auto_send.enabled); setDelay(s.auto_send.delay_minutes); } }, [s?.auto_send.enabled, s?.auto_send.delay_minutes]); // eslint-disable-line react-hooks/exhaustive-deps

  async function saveAuto(nextEnabled = enabled, nextDelay = delay) {
    setSaving(true);
    try { await api.setAutoSend(nextEnabled, Math.max(1, Math.min(1440, Math.round(nextDelay) || 10))); toast.ok(nextEnabled ? "Auto-send is on." : "Auto-send is off."); summary.reload(); }
    catch (err) { toast.err((err as Error).message); setEnabled(!nextEnabled); } finally { setSaving(false); }
  }
  const reloadAll = () => { summary.reload(); list.reload(); };
  const drafts = (list.data?.emails ?? []).filter((e) => EDITABLE.has(e.status));

  return (
    <div className="page">
      <PageHead eyebrow="Win-back" title="Customer emails"
        lede={me?.scope ? `Drafts generated from resolved issues on ${me.scope.site_host}. Edit them, send them, or let auto-send do it.` : "Drafts generated from resolved issues. Edit them, send them, or let auto-send do it."} />

      {summary.error && <ErrorNote message={summary.error} retry={summary.reload} />}

      <div className="mail-counters">
        {!s ? <Skeleton rows={1} h={72} /> : <>
          <Counter label="Emails sent so far" value={s.sent_count + s.simulated_count} tone="primary" />
          <Counter label="Delivered by SMTP" value={s.sent_count} />
          <Counter label="Recorded as simulated" value={s.simulated_count} />
          <Counter label="Drafts waiting" value={s.draft_count} />
          <Counter label="Blocked by policy" value={s.blocked_count} />
        </>}
      </div>

      <div className="grid-2">
        <Card title="Auto-send" icon={<IconClock />} sub="Approved-quality drafts that pass every policy check are sent after the delay (at most 25 per minute). SMTP delivery is used when configured.">
          <div className="row" style={{ gap: 14, flexWrap: "wrap" }}>
            <Toggle checked={enabled} disabled={saving || !s || !canAct} label="Auto-send emails" onChange={(v) => { setEnabled(v); void saveAuto(v, delay); }} />
            <span>{enabled ? "On" : "Off"}</span>
            <label className="row" style={{ gap: 8 }}>
              <span className="label">Wait</span>
              <input className="input" type="number" min={1} max={1440} value={delay} style={{ width: 90 }} onChange={(x) => setDelay(Number(x.target.value))} onBlur={() => enabled && void saveAuto(enabled, delay)} aria-label="Delay in minutes before auto-send" />
              <span className="hint">minutes</span>
            </label>
          </div>
          {s && <Banner tone="info" icon={<IconMail />}>{s.auto_send.smtp_configured ? "SMTP is configured: emails are delivered to the customer's inbox." : "SMTP is not configured: sends are recorded as simulated and nothing leaves the system."}</Banner>}
        </Card>

        <Card title="Sent to" icon={<IconSend />} sub="Customers who have received an email, newest first.">
          {!s ? <Skeleton rows={4} h={36} /> : s.recipients.length === 0 ? <Empty icon={<IconSend />} title="Nothing sent yet">Approve or send a draft below, or turn on auto-send.</Empty> : (
            <div className="table-wrap" style={{ maxHeight: 320 }}>
              <table className="t">
                <thead><tr><th>Customer</th><th>Address</th><th>Subject</th><th>Sent</th><th>Delivery</th></tr></thead>
                <tbody>{s.recipients.map((r) => (
                  <tr key={r.id}>
                    <td><span className="chip-address">{r.customer_ref}</span></td>
                    <td className="mono">{r.email_masked}</td>
                    <td>{r.subject}<div className="hint">{r.issue}</div></td>
                    <td title={r.sent_at ?? ""}>{dateTimeOf(r.sent_at)}</td>
                    <td><Badge tone={r.delivery === "smtp" ? "green" : "blue"}>{r.delivery === "smtp" ? "Delivered" : "Simulated"}</Badge></td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <Card title="Drafts" icon={<IconMail />} sub="Edit the wording, then approve or send. Nothing is sent to a customer who opted out, is suppressed, or was contacted recently.">
        {list.error && <ErrorNote message={list.error} retry={list.reload} />}
        {!list.data ? <Skeleton rows={3} h={120} /> : drafts.length === 0 ? <Empty icon={<IconMail />} title="No drafts waiting">Win-back emails appear here when an issue is resolved and verified.</Empty> : (
          <div className="mail-drafts">{drafts.map((e) => <DraftCard key={e.id} e={e} onChanged={reloadAll} canAct={canAct} />)}</div>
        )}
      </Card>
    </div>
  );
}
