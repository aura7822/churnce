import { api } from "../services/api";
import { useResource } from "../hooks/useLive";
import { usePoll } from "../hooks/usePoll";
import { TimeChart } from "./charts";
import { Empty, Skeleton } from "./ui";
import { IconGlobe } from "./icons";

const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

/** Live line graph: one line per connected website, events received per 15 s bucket. Re-reads on every
 *  `site_activity` push and every 5 s so the time axis keeps moving when a site goes quiet. */
export function SiteActivityChart({ minutes = 15, height = 240 }: { minutes?: number; height?: number }) {
  const r = useResource(() => api.sitesSeries(minutes), ["sites"], [minutes]);
  usePoll(r.reload, 5000);
  const d = r.data;
  if (!d) return <Skeleton rows={1} h={height} />;
  if (d.series.length === 0) return <Empty icon={<IconGlobe />} title="No connected websites yet">Authorise a site in the extension and turn monitoring on. Each site will appear here as its own line.</Empty>;
  return (
    <TimeChart
      live label={`Events received per ${d.step_seconds} seconds for each connected website`} height={height} unit=" ev"
      labels={d.buckets} fmtX={clock}
      series={d.series.map((s) => ({ name: s.host, values: s.counts, muted: !s.online }))}
    />
  );
}
