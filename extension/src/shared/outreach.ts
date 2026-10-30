/** Customer email drafts as the backend serves them (GET /api/v1/emails). Pure helpers, no browser APIs, so they are unit-tested. */
export interface PolicyCheck { name: string; passed: boolean; detail: string }
export interface Draft {
  id: string;
  status: "draft" | "approved" | "sent" | "sent_simulated" | "blocked" | "rejected";
  subject: string;
  body: string;
  recipient: string | null;        // masked by the backend unless the operator may see it
  customer_ref: string | null;
  holdout: boolean;
  generated_by: string;
  created_at: string;
  delivery_mode?: "smtp" | "simulated";
  policy_result?: { checks?: PolicyCheck[] };
}

export const OPEN_STATUSES = ["draft", "approved"] as const;

export function failedChecks(d: Draft): PolicyCheck[] {
  return (d.policy_result?.checks ?? []).filter((c) => !c.passed);
}

/** Auto-send picks up a draft only when every policy check passed, it is not in the holdout group, it has content,
 *  and it has waited at least `delayMin` minutes since creation (the window in which an operator can still edit it). */
export function autoSendEligible(d: Draft, delayMin: number, now: number = Date.now()): boolean {
  if (!(d.status === "draft" || d.status === "approved")) return false;
  if (d.holdout || !d.subject.trim() || !d.body.trim()) return false;
  if ((d.policy_result?.checks ?? []).length === 0 || failedChecks(d).length > 0) return false;
  const age = now - Date.parse(d.created_at);
  return Number.isFinite(age) && age >= Math.max(0, delayMin) * 60_000;
}
