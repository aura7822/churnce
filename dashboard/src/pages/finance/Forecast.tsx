import { useMemo } from "react";
import type { LiquiditySuite } from "../../types";
import { Badge, Card, Empty } from "../../components/ui";
import { ChartCard, TimeChart } from "../../components/charts";
import { IconChart, IconShieldOff, IconTrendUp } from "../../components/icons";
import { kes } from "../../services/format";
import { VERDICT_LABEL, VERDICT_TONE, day } from "./common";

export function Forecast({ s }: { s: LiquiditySuite }) {
  const f = s.forecast;
  const chart = useMemo(() => {
    const ser = f.series.slice(0, 60);
    return { labels: ser.map((r) => r.date), series: [{ name: "Projected cash", values: ser.map((r) => r.cash) }, { name: "Inflow", values: ser.map((r) => r.inflow), muted: true }, { name: "Outflow", values: ser.map((r) => r.outflow), muted: true }],
      band: { name: "80% interval", lo: ser.map((r) => r.low), hi: ser.map((r) => r.high) } };
  }, [f]);
  return (
    <div className="stack">
      <ChartCard title="Cash forecast, next 60 days" icon={<IconTrendUp />}>
        {f.ready ? <TimeChart label="Projected closing cash with an 80 percent band, plus daily inflow and outflow" labels={chart.labels} series={chart.series} band={chart.band} fmtX={day} fmtY={(v) => kes(v, true)} />
          : <Empty icon={<IconTrendUp />} title="Forecast needs more history">At least three active days of captured transactions are needed before the engine projects cash.</Empty>}
      </ChartCard>
      <Card title="Multi-horizon forecast" icon={<IconChart />} sub="Inflows include invoices falling due; outflows include bills falling due and monthly obligations.">
        {!f.ready ? <Empty icon={<IconChart />} title="Not enough data yet" /> : (
          <div className="table-scroll"><table>
            <thead><tr><th>Horizon</th><th style={{ textAlign: "right" }}>Inflow</th><th style={{ textAlign: "right" }}>Outflow</th><th style={{ textAlign: "right" }}>Net</th><th style={{ textAlign: "right" }}>Low case</th><th style={{ textAlign: "right" }}>Closing cash</th></tr></thead>
            <tbody>{f.horizons.map((h) => (
              <tr key={h.days}><td><b>{h.days} days</b></td><td className="num up">{kes(h.inflow, true)}</td><td className="num down">{kes(h.outflow, true)}</td>
                <td className={`num ${h.net >= 0 ? "up" : "down"}`}>{kes(h.net, true)}</td><td className="num">{kes(h.low, true)}</td><td className="num"><b>{kes(h.closing_cash, true)}</b></td></tr>
            ))}</tbody>
          </table></div>
        )}
      </Card>
    </div>
  );
}

export function Stress({ s }: { s: LiquiditySuite }) {
  return (
    <Card title="Scenario stress tests" icon={<IconShieldOff />} sub="Each scenario shocks the baseline forecast across all banks and currencies and re-scores cash, runway and ratios.">
      {s.stress.length === 0 ? <Empty icon={<IconShieldOff />} title="No scenarios yet" /> : (
        <div className="stress-grid">{s.stress.map((r) => (
          <article key={r.id} className={`stress-card ${r.verdict}`}>
            <header><b>{r.name}</b><Badge tone={VERDICT_TONE[r.verdict]}>{VERDICT_LABEL[r.verdict]}</Badge></header>
            <p className="hint">{r.description}</p>
            <ul className="shocks">{r.shocks.map((x) => <li key={x}>{x}</li>)}</ul>
            <dl><div><dt>Lowest cash</dt><dd>{kes(r.min_cash, true)}</dd></div><div><dt>Closing cash</dt><dd>{kes(r.closing_cash, true)}</dd></div>
              <div><dt>Runway</dt><dd>{r.runway_days === null ? "Self-funding" : `${Math.round(r.runway_days)} d`}</dd></div><div><dt>LCR</dt><dd>{r.lcr === null ? "–" : `${Math.round(r.lcr * 100)}%`}</dd></div></dl>
          </article>
        ))}</div>
      )}
    </Card>
  );
}
