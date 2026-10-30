import { useRef } from "react";
import { api } from "../services/api";
import { useLiveMessages, useResource } from "../hooks/useLive";
import { Badge, Card, Empty, ErrorNote, PageHead, SimBadge, Skeleton } from "../components/ui";
import { IconEvents } from "../components/icons";
import { ms, timeOf, titleCase } from "../services/format";

const OUTCOME_TONE: Record<string, "green" | "red" | "amber" | ""> = {
  success: "green", ok: "green", timeout: "red", error: "red", failure: "red", abandoned: "amber", no_results: "amber", validation_failure: "amber",
};

export function EventsPage() {
  const res = useResource(() => api.events(150));
  const seen = useRef<Set<string>>(new Set());
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Refresh (throttled) whenever the backend reports new events.
  useLiveMessages((m) => {
    if (m.type !== "event_ingested" || timer.current) return;
    timer.current = setTimeout(() => { timer.current = null; res.reload(); }, 600);
  });

  const rows = res.data?.events ?? [];
  const firstPaint = seen.current.size === 0;
  const fresh = new Set(firstPaint ? [] : rows.filter((e) => !seen.current.has(e.id)).map((e) => e.id));
  rows.forEach((e) => seen.current.add(e.id));

  return (
    <div className="page">
      <PageHead eyebrow="Collector" title="Live event stream" lede="" />
      {res.error && <ErrorNote message={res.error} retry={res.reload} />}
      <Card title="Incoming events" icon={<IconEvents />} sub={`${rows.length} most recent`}>
        {!res.data ? <Skeleton rows={6} h={40} /> : rows.length === 0 ? (
          <Empty icon={<IconEvents />} title="No events yet">Run a scripted journey from the overview or point the extension at an authorised site.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="t">
              <thead><tr><th>Time</th><th>Type</th><th>Route</th><th>Journey</th><th>Outcome</th><th className="num">Response</th><th>Session</th><th>Status</th></tr></thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.id} className={fresh.has(e.id) ? "fresh" : ""}>
                    <td className="mono">{timeOf(e.event_timestamp)}</td>
                    <td>{titleCase(e.event_type)}{e.redactions > 0 && <Badge tone="violet" title="Sensitive values were redacted before storage"> {e.redactions} redacted</Badge>}</td>
                    <td className="mono">{e.page_route}</td>
                    <td>{titleCase(e.journey_stage)}</td>
                    <td>{e.outcome ? <Badge tone={OUTCOME_TONE[e.outcome] ?? ""}>{titleCase(e.outcome)}</Badge> : "–"}</td>
                    <td className="num">{ms(e.response_time_ms)}</td>
                    <td className="mono">{e.session_id.slice(-10)} <SimBadge simulated={e.simulated} /></td>
                    <td>{e.chunk_id ? <Badge tone="teal">Chunked</Badge> : <Badge>{titleCase(e.processing_status ?? "pending")}</Badge>}</td>
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
