import type { LiquiditySuite, Ratio } from "../../types";
import { Badge, Banner, Card, Meter } from "../../components/ui";
import { IconInfo, IconShieldOff } from "../../components/icons";
import { kes } from "../../services/format";
import { VERDICT_LABEL, VERDICT_TONE } from "./common";

function Gauge({ r, pct }: { r: Ratio; pct?: boolean }) {
  const v = r.value, shown = v === null ? "–" : pct ? `${Math.round(v * 100)}%` : `${v.toFixed(2)}×`;
  const need = pct ? `${Math.round(r.threshold * 100)}%` : `${r.threshold.toFixed(1)}×`;
  return (
    <div className={`ratio-card ${r.status}`}>
      <header><span>{r.label}</span><Badge tone={VERDICT_TONE[r.status]}>{VERDICT_LABEL[r.status]}</Badge></header>
      <div className="ratio-val">{shown}</div>
      <Meter value={v === null ? 1 : v / (r.threshold * 2)} tone={r.status === "pass" ? "" : r.status === "warn" ? "amber" : "red"} label={`${r.label} against threshold`} />
      <small className="hint">Target ≥ {need}</small>
    </div>
  );
}

export function Compliance({ s }: { s: LiquiditySuite }) {
  const c = s.compliance;
  return (
    <Card title="Liquidity compliance metrics" icon={<IconShieldOff />} sub="Current ratio, quick ratio and liquidity coverage ratio computed from captured cash, receivables, payables and stock.">
      <div className="ratio-grid"><Gauge r={c.current_ratio} /><Gauge r={c.quick_ratio} /><Gauge r={c.lcr} pct /></div>
      <div className="row" style={{ gap: 18, flexWrap: "wrap", margin: "12px 0" }}>
        <span className="chip-address">HQLA {kes(c.hqla, true)}</span><span className="chip-address">Net 30-day outflow {kes(c.net_outflow_30d, true)}</span>
      </div>
      {c.notes.map((n, i) => <Banner key={i} tone="info" icon={<IconInfo />}>{n}</Banner>)}
    </Card>
  );
}
