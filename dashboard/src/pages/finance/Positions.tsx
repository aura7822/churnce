import type { LiquiditySuite } from "../../types";
import { Badge, Card, Empty } from "../../components/ui";
import { Donut } from "../../components/charts";
import { IconBank, IconGlobe } from "../../components/icons";
import { kes } from "../../services/format";

export function Positions({ s }: { s: LiquiditySuite }) {
  const total = s.banks.reduce((a, b) => a + b.balance_kes, 0);
  return (
    <div className="fin-cols">
      <Card className="fin-wide" title="Cash positions by bank" icon={<IconBank />} sub="Settled balance per account, converted to KES. Bank names are labels sent by the site, never account numbers.">
        {s.banks.length === 0 ? <Empty icon={<IconBank />} title="No bank positions yet">Positions appear as soon as captured payments carry a bank label.</Empty> : (
          <div className="table-scroll"><table>
            <thead><tr><th>Bank</th><th>Currency</th><th style={{ textAlign: "right" }}>Balance (KES)</th><th style={{ textAlign: "right" }}>In · 30d</th><th style={{ textAlign: "right" }}>Out · 30d</th><th style={{ textAlign: "right" }}>Share</th></tr></thead>
            <tbody>{s.banks.map((b) => (
              <tr key={b.bank}><td><b>{b.bank}</b></td><td><Badge tone={b.currency === "KES" ? "violet" : "blue"}>{b.currency}</Badge></td>
                <td className="num">{kes(b.balance_kes)}</td><td className="num up">{kes(b.inflow_kes_30d, true)}</td><td className="num down">{kes(b.outflow_kes_30d, true)}</td>
                <td className="num">{b.share_pct.toFixed(0)}%<div className="fin-bar sm"><i style={{ width: `${Math.max(0, Math.min(100, b.share_pct))}%` }} /></div></td></tr>
            ))}</tbody>
            <tfoot><tr><td colSpan={2}>Pooled total</td><td className="num"><b>{kes(total)}</b></td><td colSpan={3} /></tr></tfoot>
          </table></div>
        )}
      </Card>
      <Card title="Allocation" icon={<IconBank />}>
        {s.banks.some((b) => b.balance_kes > 0) ? <Donut label="Cash by bank" data={s.banks.filter((b) => b.balance_kes > 0).map((b) => ({ label: b.bank, value: Math.round(b.balance_kes) }))} /> : <Empty icon={<IconBank />} title="Nothing to allocate" />}
      </Card>
      <Card className="fin-wide" title="Currency exposure" icon={<IconGlobe />} sub="Native balances and the indicative rate used to express them in KES. Override rates with the FX_RATES_JSON setting.">
        {s.currencies.length === 0 ? <Empty icon={<IconGlobe />} title="No currencies yet" /> : (
          <div className="fx-grid">{s.currencies.map((c) => (
            <div key={c.currency} className="fx-tile"><span className="chip-address">{c.currency}</span><b>{c.balance_native.toLocaleString("en-KE", { maximumFractionDigits: 0 })}</b>
              <small>{c.currency === "KES" ? "base currency" : `1 ${c.currency} = KES ${c.fx_rate_to_kes}`}</small><span className="hint">{kes(c.balance_kes, true)}</span></div>
          ))}</div>
        )}
      </Card>
    </div>
  );
}
