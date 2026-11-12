import type { LiquiditySuite } from "../../types";
import { Badge, Card, Empty, Stat } from "../../components/ui";
import { IconBank, IconClock, IconSparkle, IconTimer, IconWallet } from "../../components/icons";
import { kes } from "../../services/format";
import { days1 } from "./common";

export function Working({ s }: { s: LiquiditySuite }) {
  const w = s.working_capital;
  const release = w.recommendations.reduce((a, r) => a + r.cash_release_kes, 0);
  return (
    <div className="stack">
      <div className="kpi-grid">
        <Stat label="Receivables (AR)" value={kes(w.ar.balance, true)} note={`${w.ar.count} open · ${kes(w.ar.overdue, true)} overdue · DSO ${days1(w.ar.dso)}`} icon={<IconWallet />} tone="blue" />
        <Stat label="Payables (AP)" value={kes(w.ap.balance, true)} note={`${w.ap.count} open · ${kes(w.ap.overdue, true)} overdue · DPO ${days1(w.ap.dpo)}`} icon={<IconBank />} tone="blue" />
        <Stat label="Inventory" value={kes(w.inventory.value, true)} note={`DIO ${days1(w.inventory.dio)}`} icon={<IconTimer />} tone="blue" />
        <Stat label="Cash conversion cycle" value={w.ccc === null ? "–" : `${Math.round(w.ccc)} days`} note="DSO + DIO − DPO" icon={<IconClock />} tone="blue" />
        <Stat label="Net working capital" value={kes(w.working_capital, true)} note="AR + stock − AP" icon={<IconWallet />} tone="blue" />
        <Stat label="Releasable cash" value={kes(release, true)} note="If every fix below lands" icon={<IconSparkle />} tone="blue" />
      </div>
      <Card title="Working-capital optimisation" icon={<IconSparkle />} sub="Specific, ranked fixes across receivables, payables and stock cycles.">
        {w.recommendations.length === 0 ? <Empty icon={<IconSparkle />} title="Nothing to optimise yet" /> : (
          <ul className="wc-recs">{w.recommendations.map((r) => (
            <li key={r.id}><div><b>{r.title}</b><p className="hint">{r.detail}</p></div>{r.cash_release_kes > 0 ? <Badge tone="green">+{kes(r.cash_release_kes, true)}</Badge> : <Badge tone="">on target</Badge>}</li>
          ))}</ul>
        )}
      </Card>
    </div>
  );
}
