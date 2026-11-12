import type { ReactNode } from "react";
import { api } from "../../services/api";
import { useResource } from "../../hooks/useLive";
import { Badge, Button, ErrorNote, Skeleton } from "../../components/ui";
import { IconReport, IconCheck, IconWarn } from "../../components/icons";
import { Section, kes } from "./common";
import { num } from "../../services/format";

const TONE = { high: "red", medium: "amber", low: "blue" } as const;
const day = (iso: string) => new Date(iso).toLocaleDateString([], { day: "numeric", month: "short" });
const chg = (v: number | null) => (v === null ? null : <span className={v >= 0 ? "delta up" : "delta down"}>{v >= 0 ? "+" : ""}{v}% vs last week</span>);

/** Weekly report: every captured metric of the last seven days, what it calls for, and advice. Readable by every role. */
export function Weekly() {
  const r = useResource(api.weeklyReport, ["finance", "metrics"]);
  if (r.error && !r.data) return <ErrorNote message={r.error} retry={r.reload} />;
  const w = r.data;
  if (!w) return <Skeleton kind="kpis" rows={4} h={96} />;
  const tiles: [string, string, ReactNode][] = [
    ["Inflow", kes(w.week.inflow), chg(w.change_pct.inflow)], ["Outflow", kes(w.week.outflow), null], ["Net cash flow", kes(w.week.net), chg(w.change_pct.net)],
    ["Failed payments", `${num(w.week.failed)} · ${w.week.failure_rate_pct}%`, chg(w.change_pct.failed)],
  ];
  return (
    <div className="stack weekly">
      <div className="card tile">
        <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
          <div><span className="eyebrow"><IconReport /> {day(w.period.from)} to {day(w.period.to)}{w.scope ? ` · ${w.scope.site_host}` : " · all websites"}</span><h3 style={{ marginTop: 6 }}>{w.headline}</h3></div>
          <Button variant="neu" onClick={() => window.print()}>Print or save as PDF</Button>
        </div>
      </div>
      <div className="grid kpis">{tiles.map(([l, v, d]) => <div key={l} className="clay blue"><div className="k-label">{l}</div><div className="k-value">{v}</div><div className="k-note">{d}</div></div>)}</div>

      <div className="fin-cols">
        <Section title="Required actions" lede="What needs doing this week, most urgent first.">
          <ul className="wc-recs">{w.required_actions.map((a, i) => (
            <li key={i}><div><b>{a.title}</b><div className="hint">{a.detail}</div></div><span className="row" style={{ gap: 6 }}><Badge tone={TONE[a.priority]} icon={a.priority === "low" ? <IconCheck /> : <IconWarn />}>{a.priority}</Badge><Badge>{a.owner}</Badge></span></li>
          ))}</ul>
        </Section>
        <Section title="Advice from Cents AI rules" lede="Practical next steps drawn from this week's numbers.">
          <ul className="wc-recs">{w.advice.map((a, i) => <li key={i}><div><b>{a.title}</b><div className="hint">{a.detail}</div></div></li>)}</ul>
        </Section>
      </div>

      <Section title="Captured this week" lede="Everything the connected website reported, in one place.">
        <div className="fx-grid">
          {([["Events captured", w.captured.events_total], ["Last hour", w.captured.events_last_hour], ["Chunks indexed", w.captured.chunks_indexed], ["Active incidents", w.captured.incidents_active],
            ["Email drafts", w.captured.emails_draft], ["Emails approved", w.captured.emails_approved], ["Awaiting approval", w.captured.actions_awaiting_approval], ["Actions completed", w.captured.actions_completed]] as [string, number][])
            .map(([l, v]) => <div key={l} className="fx-tile"><span className="hint">{l}</span><b>{num(v)}</b></div>)}
        </div>
      </Section>

      <div className="fin-cols">
        <Section title="Cash and ratios">
          <div className="fx-grid">
            <div className="fx-tile"><span className="hint">Cash position</span><b>{kes(w.cash.total)}</b></div>
            <div className="fx-tile"><span className="hint">7-day closing</span><b>{w.cash.forecast_7 ? kes(w.cash.forecast_7.closing_cash) : "–"}</b></div>
            <div className="fx-tile"><span className="hint">30-day closing</span><b>{w.cash.forecast_30 ? kes(w.cash.forecast_30.closing_cash) : "–"}</b></div>
            <div className="fx-tile"><span className="hint">Current ratio</span><b>{w.ratios.current_ratio?.toFixed(2) ?? "–"}</b></div>
            <div className="fx-tile"><span className="hint">Quick ratio</span><b>{w.ratios.quick_ratio?.toFixed(2) ?? "–"}</b></div>
            <div className="fx-tile"><span className="hint">LCR</span><b>{w.ratios.lcr?.toFixed(2) ?? "–"}</b></div>
          </div>
        </Section>
        <Section title="Why payments failed">
          {w.week.top_failure_reasons.length === 0 ? <p className="hint">No failed payments this week.</p> : <ul className="wc-recs">{w.week.top_failure_reasons.map((x) => <li key={x.reason}><b>{x.reason}</b><Badge tone="red">{x.count}</Badge></li>)}</ul>}
          {w.week.top_sites.length > 0 && <><h4 style={{ margin: "14px 0 6px" }}>Top websites by inflow</h4><ul className="wc-recs">{w.week.top_sites.map((x) => <li key={x.site}><span className="mono">{x.site}</span><b>{kes(x.inflow)}</b></li>)}</ul></>}
        </Section>
      </div>
    </div>
  );
}
