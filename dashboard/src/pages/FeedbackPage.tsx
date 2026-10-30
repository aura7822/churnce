import { api } from "../services/api";
import { useResource } from "../hooks/useLive";
import type { Outcome } from "../types";
import { Badge, Card, Empty, ErrorNote, PageHead, SimBadge, Skeleton, StateBadge } from "../components/ui";
import { IconFeedback, IconHandshake } from "../components/icons";
import { ago, pct, titleCase } from "../services/format";

const STRENGTH_TONE = { insufficient: "red", low: "amber", moderate: "blue", strong: "green" } as const;

function Value({ v }: { v: number | null }) {
  return <div className="big">{v === null ? "–" : pct(v, 1)}</div>;
}

function OutcomeCard({ o }: { o: Outcome }) {
  const delta = o.baseline_value !== null && o.post_value !== null ? o.post_value - o.baseline_value : null;
  return (
    <Card title={titleCase(o.metric)} icon={<IconFeedback />} sub={o.method}
      actions={<><Badge tone={STRENGTH_TONE[o.strength]}>Evidence: {titleCase(o.strength)}</Badge><SimBadge simulated={o.simulated} /></>}>
      <div className="cmp">
        <div className="col"><span className="label">Before fix</span><Value v={o.baseline_value} /><span className="hint">{o.n_baseline} journeys</span></div>
        <div className="col"><span className="label">After fix</span><Value v={o.post_value} /><span className="hint">{o.n_post} journeys</span></div>
      </div>
      {delta !== null && <p style={{ marginTop: 12 }}>Change: <b style={{ color: delta >= 0 ? "var(--green)" : "var(--red)" }}>{delta >= 0 ? "+" : ""}{(delta * 100).toFixed(1)} points</b></p>}
      {o.details.caveats && o.details.caveats.length > 0 && <ul className="facts" style={{ marginTop: 10 }}>{o.details.caveats.map((c, i) => <li key={i}>{c}</li>)}</ul>}
      <p className="hint" style={{ marginTop: 8 }}>{ago(o.created_at)}</p>
    </Card>
  );
}

export function FeedbackPage() {
  const outcomes = useResource(api.outcomes, ["outcomes"]);
  const resolutions = useResource(api.resolutions, ["resolutions"]);
  const o = outcomes.data?.outcomes ?? [];
  const r = resolutions.data?.resolutions ?? [];

  return (
    <div className="page">
      <PageHead eyebrow="" title="< Examination />" />
      {(outcomes.error || resolutions.error) && <ErrorNote message={(outcomes.error || resolutions.error)!} retry={() => { outcomes.reload(); resolutions.reload(); }} />}

      <h3>Outcomes</h3>
      {!outcomes.data ? <Skeleton rows={2} h={170} /> : o.length === 0 ? (
        <Card><Empty icon={<IconFeedback />} title="No outcomes measured yet">Record a verified resolution, run healthy journeys, then choose “Evaluate outcome” on the incident.</Empty></Card>
      ) : <div className="grid two">{o.map((x) => <OutcomeCard key={x.id} o={x} />)}</div>}

      <h3>Resolutions</h3>
      <Card>
        {!resolutions.data ? <Skeleton rows={3} h={40} /> : r.length === 0 ? <Empty icon={<IconHandshake />} title="No resolutions recorded" /> : (
          <div className="table-wrap">
            <table className="t">
              <thead><tr><th>Category</th><th>Status</th><th>Sources</th><th>Approved claims</th><th>Verified</th></tr></thead>
              <tbody>
                {r.map((x) => (
                  <tr key={x.resolution_id}>
                    <td>{titleCase(x.issue_category)}</td>
                    <td><StateBadge state={x.resolution_status} /></td>
                    <td>{x.verification_sources.map((s) => <div key={s.ref} className="mono">{s.type}: {s.ref} ({s.status})</div>)}</td>
                    <td>{x.approved_claims.join("; ") || "–"}</td>
                    <td>{x.verified_at ? ago(x.verified_at) : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
