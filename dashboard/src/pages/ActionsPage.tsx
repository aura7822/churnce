import { useState } from "react";
import { api } from "../services/api";
import { useResource } from "../hooks/useLive";
import { useAuth } from "../hooks/useAuth";
import { useToast } from "../hooks/useToast";
import type { Action, Email } from "../types";
import { Badge, Button, Card, Empty, ErrorNote, Meter, PageHead, PolicyChecks, Segmented, Skeleton, StateBadge } from "../components/ui";
import { IconActions, IconBug, IconCheck, IconMail, IconSend, IconTicket, IconX } from "../components/icons";
import { ago, titleCase } from "../services/format";

type Tab = "actions" | "emails";

/** The backend sends {factors, weights, eligible}. Accept that shape or a flat {name: number} map and ignore anything else. */
function factorsOf(b: unknown): Record<string, number> {
  const src = (b && typeof b === "object" && "factors" in b ? (b as { factors: unknown }).factors : b) as Record<string, unknown> | null;
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(src ?? {})) if (typeof v === "number" && Number.isFinite(v)) out[k] = v;
  return out;
}

function ActionCard({ a, onChanged }: { a: Action; onChanged: () => void }) {
  const { can } = useAuth();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const decidable = a.status === "AWAITING_APPROVAL" && can(`actions:approve:${a.category}`);

  async function decide(kind: "approve" | "reject") {
    setBusy(kind);
    try { await (kind === "approve" ? api.approveAction(a.id) : api.rejectAction(a.id)); toast.ok(kind === "approve" ? "Approved." : "Declined."); onChanged(); }
    catch (e) { toast.err((e as Error).message); } finally { setBusy(null); }
  }
  const ref = (a.execution_result as { summary?: string; note?: string }) ?? {};

  return (
    <Card className="action-card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row"><Badge tone="blue" icon={a.category === "engineering" ? <IconBug /> : a.category === "marketing" ? <IconMail /> : <IconTicket />}>{titleCase(a.category)}</Badge><Badge tone={a.priority === "critical" || a.priority === "high" ? "amber" : ""}>{titleCase(a.priority)}</Badge></div>
        <StateBadge state={a.status} />
      </div>
      <h4>{a.title}</h4>
      <p className="card-sub">{a.rationale}</p>
      {a.incident_title && <p className="hint">Incident: {a.incident_title}</p>}
      <details>
        <summary className="hint" style={{ cursor: "pointer" }}>Score {Number(a.score ?? 0).toFixed(1)} and policy checks</summary>
        <div className="stack" style={{ marginTop: 10 }}>
          {Object.entries(factorsOf(a.score_breakdown)).map(([k, v]) => <div className="score" key={k}><span>{titleCase(k)}</span><Meter value={v} tone="blue" label={k} /><span className="mono">{v.toFixed(2)}</span></div>)}
          <PolicyChecks checks={a.policy_result?.checks} />
        </div>
      </details>
      {a.error && <p role="alert" style={{ color: "var(--red)" }}>{a.error}</p>}
      {ref.summary && <p className="hint">Result: <span className="mono">{ref.summary}</span>{ref.note ? ` · ${ref.note}` : ""}</p>}
      {decidable && (
        <div className="row">
          <Button variant="clay" icon={<IconCheck />} busy={busy === "approve"} onClick={() => decide("approve")}>Approve</Button>
          <Button variant="clay-rose" icon={<IconX />} busy={busy === "reject"} onClick={() => decide("reject")}>Decline</Button>
        </div>
      )}
      <span className="hint">{ago(a.created_at)}{a.decided_by ? ` · decided by ${a.decided_by}` : ""}</span>
    </Card>
  );
}

function EmailCard({ e, onChanged }: { e: Email; onChanged: () => void }) {
  const { can } = useAuth();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const allowed = can("emails:approve");
  async function run(name: string, fn: () => Promise<unknown>, ok: string) {
    setBusy(name);
    try { await fn(); toast.ok(ok); onChanged(); } catch (err) { toast.err((err as Error).message); } finally { setBusy(null); }
  }
  return (
    <Card className="action-card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row"><Badge tone="blue" icon={<IconMail />}>{e.recipient ?? e.customer_ref ?? "Customer"}</Badge>{e.holdout && <Badge tone="violet" title="Held out of the campaign to measure its real effect">Holdout</Badge>}<Badge>{e.generated_by}</Badge></div>
        <StateBadge state={e.status} />
      </div>
      <div className="mail"><div className="subject">{e.subject}</div><p>{e.body}</p></div>
      <details><summary className="hint" style={{ cursor: "pointer" }}>Policy checks and claims used</summary><div className="stack" style={{ marginTop: 10 }}><PolicyChecks checks={e.policy_result?.checks} /><div className="row">{(e.claims_used ?? []).map((c) => <span key={c} className="chip">{c}</span>)}</div></div></details>
      {allowed && e.status === "draft" && !e.holdout && (
        <div className="row">
          <Button variant="clay" icon={<IconCheck />} busy={busy === "a"} onClick={() => run("a", () => api.approveEmail(e.id), "Draft approved.")}>Approve</Button>
          <Button variant="clay-rose" icon={<IconX />} busy={busy === "r"} onClick={() => run("r", () => api.rejectEmail(e.id), "Draft rejected.")}>Reject</Button>
        </div>
      )}
      {allowed && e.status === "approved" && <Button variant="clay-amber" icon={<IconSend />} busy={busy === "s"} onClick={() => run("s", () => api.sendEmail(e.id), "Sent through the simulated provider.")}>Send (simulated)</Button>}
    </Card>
  );
}

export function ActionsPage() {
  const [tab, setTab] = useState<Tab>("actions");
  const acts = useResource(api.recommendations, ["actions"]);
  const mails = useResource(api.emails, ["emails"]);
  const list = acts.data?.recommendations ?? [];
  const waiting = list.filter((a) => a.status === "AWAITING_APPROVAL");
  const rest = list.filter((a) => a.status !== "AWAITING_APPROVAL");
  const drafts = mails.data?.emails ?? [];

  return (
    <div className="page">
      <PageHead eyebrow="Next best action" title="< actionCenter />" lede="" />
      <Segmented<Tab> value={tab} onChange={setTab} options={[
        { id: "actions", label: "Actions", count: waiting.length, icon: <IconActions /> },
        { id: "emails", label: "Email drafts", count: drafts.filter((d) => d.status === "draft").length, icon: <IconMail /> },
      ]} />
      {(acts.error || mails.error) && <ErrorNote message={(acts.error || mails.error)!} retry={() => { acts.reload(); mails.reload(); }} />}

      {tab === "actions" ? (
        !acts.data ? <Skeleton rows={3} h={150} /> : list.length === 0 ? <Card><Empty icon={<IconActions />} title="No actions proposed">They appear after an incident is analysed.</Empty></Card> : (
          <>
            {waiting.length > 0 && <div className="grid two">{waiting.map((a) => <ActionCard key={a.id} a={a} onChanged={acts.reload} />)}</div>}
            {rest.length > 0 && <><h3>History</h3><div className="grid two">{rest.map((a) => <ActionCard key={a.id} a={a} onChanged={acts.reload} />)}</div></>}
          </>
        )
      ) : (
        !mails.data ? <Skeleton rows={3} h={200} /> : drafts.length === 0 ? <Card><Empty icon={<IconMail />} title="No email drafts">Drafts are prepared only after a resolution is verified.</Empty></Card> : (
          <div className="grid two">{drafts.map((e) => <EmailCard key={e.id} e={e} onChanged={mails.reload} />)}</div>
        )
      )}
    </div>
  );
}
