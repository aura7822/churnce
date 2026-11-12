import { api } from "../../services/api";
import { useResource } from "../../hooks/useLive";
import { Button, PageHead } from "../../components/ui";
import { IconCheck, IconLock, IconSparkle } from "../../components/icons";
import { kes } from "../../services/format";
import type { PlanAccess } from "../../types";

const FREE = ["Live event stream for your website", "Chunk lab and RAG review", "Action centre and customer emails", "Documentation and overview metrics"];

/** The plans page, shown over a blurred copy of the section once a website's free trial has ended (or was never started).
 *  Subscribing to Pro re-grants access for that website ID straight away. */
export function Upsell({ isAdmin, scoped, access, onActivate, onSubscribe, busy, feature = "Finance and liquidity", lede = "Cash positions, forecasts, stress tests, working capital, pooling and compliance for every connected website." }: { isAdmin: boolean; scoped: boolean; access: PlanAccess | null; onActivate: () => void; onSubscribe: () => void; busy: boolean; feature?: string; lede?: string }) {
  const plan = useResource(api.plan, ["finance"]);
  const price = plan.data?.price_kes?.premium ?? 333;
  const ended = !!access?.trial?.used && !access?.active;
  const wid = access?.trial?.website_id;
  const headline = ended ? `Your 72-hour free trial${wid ? ` for ${wid}` : ""} has ended` : `${feature} is a Pro feature`;
  const sub = ended ? "Subscribe to Pro to unlock this section again. Everything you captured is kept." : scoped ? "Start the free trial from the Churnce extension (72 hours, once per website ID), or subscribe to Pro now." : "Start a free trial from the extension settings of a connected website, or activate Pro for the organisation.";
  return (
    <div className="page">
      <PageHead eyebrow="Pro" title={feature} lede={lede} />
      <div className="gate">
        <div className="gate-blur" aria-hidden="true">
          <div className="grid kpis">{[0, 1, 2, 3].map((i) => <div key={i} className="clay"><div className="k-label">Cash position</div><div className="k-value">KES {(1250000 + i * 387000).toLocaleString("en-KE")}</div><div className="k-note">live</div></div>)}</div>
          <div className="card" style={{ marginTop: 16, minHeight: 220 }}><h3>Forecast</h3><div className="skel" style={{ height: 150, marginTop: 12 }} /></div>
          <div className="grid-2" style={{ marginTop: 16 }}><div className="card" style={{ minHeight: 140 }}><div className="skel" style={{ height: 100 }} /></div><div className="card" style={{ minHeight: 140 }}><div className="skel" style={{ height: 100 }} /></div></div>
        </div>
        <div className="gate-over" role="region" aria-label="Plans">
          <div style={{ display: "grid", justifyItems: "center", width: "100%" }}>
            <div className="plans-head"><span className="eyebrow"><IconLock /> Locked</span><h2>{headline}</h2><p className="hint">{sub}</p></div>
            <div className="plans">
              <article className="plan-card">
                <span className="eyebrow">Free</span>
                <div className="plan-price">{kes(0)}<small> / month</small></div>
                <ul>{FREE.map((f) => <li key={f}><IconCheck />{f}</li>)}</ul>
                <Button variant="neu" disabled>Current plan</Button>
              </article>
              <article className="plan-card pro">
                <span className="eyebrow">{plan.data?.name ?? "Churnce Pro"}</span>
                <div className="plan-price">{kes(price)}<small> / month</small></div>
                <ul>{(plan.data?.features ?? []).slice(0, 6).map((f) => <li key={f.id}><IconSparkle />{f.title}</li>)}</ul>
                {scoped
                  ? <Button variant="clay" className="amber" busy={busy} icon={<IconSparkle />} onClick={onSubscribe}>Subscribe to Pro</Button>
                  : isAdmin ? <Button variant="clay" className="amber" busy={busy} icon={<IconSparkle />} onClick={onActivate}>Activate Pro</Button> : null}
                <small className="hint" style={{ color: "inherit", opacity: .8 }}>Billing is not connected yet, so subscribing records your plan without charging a card.</small>
              </article>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
