import { useMemo, useState, type FormEvent } from "react";
import { api } from "../services/api";
import { useResource, useServerNow } from "../hooks/useLive";
import { useAuth } from "../hooks/useAuth";
import { useToast } from "../hooks/useToast";
import type { FinanceSummary, FinTxn, PlanAccess } from "../types";
import { Badge, Banner, Button, Card, Empty, ErrorNote, Meter, Modal, PageHead, Segmented, Skeleton, Stat } from "../components/ui";
import { ChartCard, HBar, TimeChart } from "../components/charts";
import { IconActions, IconBank, IconChart, IconCoins, IconDonut, IconGlobe, IconHeart, IconSparkle, IconTimer, IconTrendUp, IconWallet, IconWarn, IconTerminal } from "../components/icons";
import { ago, kes, num, titleCase } from "../services/format";
import { Upsell } from "./finance/Upsell";
import { PingBar, CaptureControls, SyncPanel, LogTerminal } from "./finance/Capture";
import { hms } from "./finance/common";
import { useCapture } from "./finance/useCapture";
import { Positions } from "./finance/Positions";
import { Forecast, Stress } from "./finance/Forecast";
import { Working } from "./finance/Working";
import { Pooling } from "./finance/Pooling";
import { Compliance } from "./finance/Compliance";
import { Analyst, CentsChip } from "./finance/Analyst";
import { Weekly } from "./finance/Weekly";

const money = (v: number | null | undefined, _cur?: string, compact = false) => kes(v, compact);
const pc = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${v}%`);
const delta = (v: number | null | undefined) => (v === null || v === undefined ? null : <span className={v >= 0 ? "delta up" : "delta down"}>{v >= 0 ? "▲" : "▼"} {Math.abs(v)}%</span>);
const day = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString([], { day: "numeric", month: "short" });
const TONE: Record<string, "green" | "amber" | "red" | "blue"> = { good: "green", warn: "amber", bad: "red", info: "blue" };

function SettingsModal({ s, onClose, onSaved }: { s: FinanceSummary; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({ currency: "KES", opening_balance: String(s.settings.opening_balance), monthly_obligations: String(s.settings.monthly_obligations) });
  async function save(e: FormEvent) {
    e.preventDefault();
    try { await api.financeSettings({ currency: "KES", opening_balance: Number(f.opening_balance) || 0, monthly_obligations: Number(f.monthly_obligations) || 0 }); toast.ok("Finance settings saved."); onSaved(); onClose(); }
    catch (err) { toast.err((err as Error).message); }
  }
  return (
    <Modal title="Finance engine settings" onClose={onClose}>
      <form className="stack" onSubmit={save}>
        <p className="hint">All values are shown in Kenyan shillings (KES). Other currencies are converted at indicative rates.</p>
        <label className="field"><span className="label">Opening balance</span><input className="input" type="number" step="0.01" value={f.opening_balance} onChange={(e) => setF({ ...f, opening_balance: e.target.value })} /><span className="hint">Cash held before the first captured transaction.</span></label>
        <label className="field"><span className="label">Monthly obligations</span><input className="input" type="number" step="0.01" min="0" value={f.monthly_obligations} onChange={(e) => setF({ ...f, monthly_obligations: e.target.value })} /><span className="hint">Costs not captured as events (payroll, hosting, rent). Drives runway and coverage.</span></label>
        <Button variant="clay" type="submit">Save settings</Button>
      </form>
    </Modal>
  );
}

function Ledger({ site, cur }: { site: string | null; cur: string }) {
  const [tab, setTab] = useState<"all" | "failed" | "success" | "pending">("all");
  const r = useResource(() => api.financeTxns(tab, site), ["finance"], [tab, site]);
  const rows: FinTxn[] = r.data?.transactions ?? [];
  return (
    <Card title="Captured transactions" icon={<IconWallet />} sub="Newest first. Only type, status, amount, method category and failure reason are stored: never card numbers or payer identity."
      actions={<Segmented value={tab} onChange={setTab} options={[{ id: "all", label: "All" }, { id: "failed", label: "Failed" }, { id: "success", label: "Succeeded" }, { id: "pending", label: "Pending" }]} />}>
      {r.error && <ErrorNote message={r.error} retry={r.reload} />}
      {!r.data ? <Skeleton rows={4} h={34} /> : rows.length === 0 ? <Empty icon={<IconWallet />} title="No transactions in this view">Events appear here the moment the extension reports them.</Empty> : (
        <div className="table-scroll ledger">
          <table><thead><tr><th>When</th><th>Website</th><th>Type</th><th>Status</th><th>Method</th><th>Reason</th><th style={{ textAlign: "right" }}>Amount</th></tr></thead>
            <tbody>{rows.map((t) => (
              <tr key={t.id} className={t.status === "failed" ? "bad" : ""}>
                <td title={t.ts}>{ago(t.ts)}</td><td>{t.site_host}</td><td>{titleCase(t.txn_type)}</td>
                <td><Badge tone={t.status === "success" ? "green" : t.status === "failed" ? "red" : "amber"}>{t.status}</Badge>{t.simulated && <Badge tone="violet">sample</Badge>}</td>
                <td>{titleCase(t.method ?? "other")}</td>
                <td>{t.reason ? <>{titleCase(t.reason)}{t.retryable && <Badge tone="blue">retryable</Badge>}</> : "–"}</td>
                <td style={{ textAlign: "right", fontFamily: "var(--font-mono)" }}>{["refund", "chargeback", "fee", "payout"].includes(t.txn_type) ? "−" : ""}{money(t.amount, t.currency || cur)}</td>
              </tr>))}</tbody></table>
        </div>
      )}
    </Card>
  );
}

function Cashflow({ site, setSite, isAdmin }: { site: string | null; setSite: (s: string | null) => void; isAdmin: boolean }) {
  const toast = useToast();
  const [days, setDays] = useState<"7" | "30" | "90">("30");
  const [edit, setEdit] = useState(false);
  const [busy, setBusy] = useState(false);
  const r = useResource(() => api.financeSummary(Number(days), site), ["finance"], [days, site]);
  const s = r.data;

  async function sample() {
    setBusy(true);
    try { const x = await api.financeSimulate(); toast.ok(`Loaded ${num(x.transactions)} sample transactions (flagged as samples).`); r.reload(); } catch (e) { toast.err((e as Error).message); } finally { setBusy(false); }
  }

  const fc = s?.forecast;
  const chart = useMemo(() => {
    if (!s) return null;
    const hist = s.series.dates.slice(-21), n = hist.length;
    const inflow = s.series.inflow.slice(-21);
    const fdays = fc?.ready ? fc.days : [];
    const labels = [...hist, ...fdays.map((d) => d.date)];
    const none = (k: number) => Array<number | null>(Math.max(0, k)).fill(null);
    const actual: (number | null)[] = [...inflow, ...none(fdays.length)];
    const fcast: (number | null)[] = [...none(n - 1), inflow[n - 1] ?? 0, ...fdays.map((d) => d.value)];
    return {
      cash: { labels: s.series.dates, series: [{ name: "Inflow", values: s.series.inflow }, { name: "Outflow", values: s.series.outflow }, { name: "Net", values: s.series.net }] },
      fc: {
        labels,
        series: [{ name: "Actual income", values: actual }, ...(fdays.length ? [{ name: "Forecast", values: fcast, dashed: true }] : [])],
        band: fdays.length ? { name: "80% interval", lo: [...none(n), ...fdays.map((d) => d.low)], hi: [...none(n), ...fdays.map((d) => d.high)] } : undefined,
      },
    };
  }, [s, fc]);

  const cur = "KES";
  const liq = s?.liquidity;

  return (
    <div className="page">
      <PageHead eyebrow="Cashflow" title="Cashflow and payments" lede="Revenue, failed payments and income forecast, built from the transactions the extension captures on each connected website."
        actions={<div className="row" style={{ flexWrap: "wrap" }}>
          <Segmented value={days} onChange={setDays} options={[{ id: "7", label: "7d" }, { id: "30", label: "30d" }, { id: "90", label: "90d" }]} />
          {s && s.sites_available.length > 0 && <select className="input" style={{ width: "auto" }} value={site ?? ""} onChange={(e) => setSite(e.target.value || null)} aria-label="Website"><option value="">All websites</option>{s.sites_available.map((h) => <option key={h} value={h}>{h}</option>)}</select>}
          {isAdmin && s && <Button variant="ghost" className="btn-sm" onClick={() => setEdit(true)}>Settings</Button>}
        </div>} />
      {r.error && <ErrorNote message={r.error} retry={r.reload} />}
      {!s ? <Skeleton rows={3} h={110} /> : (
        <>
          {s.simulated && <Banner tone="info">This view includes flagged sample transactions. They are never produced by real sites.</Banner>}
          {s.captured === 0 && (
            <Card><Empty icon={<IconCoins />} title="No financial events captured yet">
              Turn on the finance permission in the extension and emit transaction events from the site (see Documentation).{isAdmin && <> Or explore with sample data: <Button variant="ghost" className="btn-sm" busy={busy} onClick={sample}>Load sample data</Button></>}
            </Empty></Card>
          )}

          <section className="fin-hero" aria-label="Liquidity summary">
            <div className="fin-cash"><span className="eyebrow">Cash position</span><div className="fin-big">{money(liq!.cash_position, cur, true)}</div>
              <span className="hint">{liq!.self_funding ? "Self-funding at the current pace" : `${liq!.runway_days ?? 0} days of runway`}{liq!.settled_to_owner ? ` · ${money(liq!.settled_to_owner, cur, true)} settled out` : ""}</span></div>
            <div className="fin-gauge"><span className="eyebrow">Cash health</span><div className="fin-score" data-band={liq!.health.band}>{liq!.health.score}<small>/100</small></div>
              <Meter value={liq!.health.score / 100} tone={liq!.health.band === "healthy" ? "" : liq!.health.band === "watch" ? "amber" : "red"} label="Cash health score" /><span className="hint">{titleCase(liq!.health.band)}</span></div>
            <div className="fin-mini"><span>Coverage ratio</span><b>{liq!.coverage_ratio === null ? "–" : `${liq!.coverage_ratio}×`}</b></div>
            <div className="fin-mini"><span>Avg daily net</span><b>{money(liq!.avg_daily_net, cur, true)}</b></div>
            <div className="fin-mini"><span>Next 7 days (forecast)</span><b>{money(fc?.next_7_days_income, cur, true)}</b></div>
            <div className="fin-mini"><span>Success rate</span><b>{pc(s.kpis.success_rate)}</b></div>
          </section>

          <div className="kpi-grid">
            <Stat label="Gross revenue" value={money(s.kpis.gross_revenue, cur, true)} note={<>{delta(s.deltas.gross_revenue)} vs previous {s.days}d</>} icon={<IconCoins />} tone="blue" />
            <Stat label="Net cashflow" value={money(s.kpis.net_cashflow, cur, true)} note={<>{delta(s.deltas.net_cashflow)} · refunds {money(s.kpis.refunds, cur, true)}</>} icon={<IconTrendUp />} tone="blue" />
            <Stat label="Failed payments" value={num(s.kpis.payments_failed)} note={<>{money(s.kpis.failed_value, cur, true)} at risk · {delta(s.deltas.failed)}</>} icon={<IconWarn />} tone="blue" />
            <Stat label="Avg order value" value={money(s.kpis.avg_order_value, cur)} note={`${num(s.kpis.payments_succeeded)} successful payments`} icon={<IconWallet />} tone="blue" />
            <Stat label="Pending" value={money(s.kpis.pending_value, cur, true)} note={`${num(s.kpis.payments_pending)} awaiting confirmation`} icon={<IconTimer />} tone="blue" />
            <Stat label="Chargeback rate" value={pc(s.kpis.chargeback_rate)} note={`Refund rate ${pc(s.kpis.refund_rate)} · fees ${money(s.kpis.fees, cur, true)}`} icon={<IconBank />} tone="blue" />
          </div>

          {s.insights.length > 0 && (
            <Card title="Insights" icon={<IconSparkle />} sub="Plain-language reading of the figures above. Generated from rules over your data, not guesses.">
              <ul className="insights">{s.insights.map((i, k) => <li key={k}><Badge tone={TONE[i.tone]}>{i.tone === "bad" ? "risk" : i.tone === "warn" ? "watch" : i.tone === "good" ? "good" : "note"}</Badge><span>{i.text}</span></li>)}</ul>
              {s.anomalies.length > 0 && <p className="hint">Anomalies: {s.anomalies.map((a) => `${day(a.date)} ${titleCase(a.kind)}`).join(" · ")}</p>}
            </Card>
          )}

          {chart && (
            <div className="charts charts-2">
              <ChartCard title="Cashflow" icon={<IconChart />}>
                <TimeChart label={`Inflow, outflow and net cashflow per day over ${s.days} days`} labels={chart.cash.labels} series={chart.cash.series} fmtX={day} fmtY={(v) => money(v, cur, true)} area={false} />
              </ChartCard>
              <ChartCard title="Income forecast" icon={<IconTrendUp />}>
                {fc?.ready ? <TimeChart label="Recent income and the next 14 days forecast with an 80 percent band" labels={chart.fc.labels} series={chart.fc.series} band={chart.fc.band} fmtX={day} fmtY={(v) => money(v, cur, true)} />
                  : <Empty icon={<IconTrendUp />} title="Forecast needs more history">{fc?.reason}</Empty>}
              </ChartCard>
              <ChartCard title="Why payments fail" icon={<IconWarn />}>
                {s.failure_reasons.length ? <HBar label="Failed payments by reason" data={s.failure_reasons.slice(0, 6).map((x) => ({ label: titleCase(x.reason).slice(0, 14), value: x.count }))} /> : <Empty icon={<IconWarn />} title="No failures in this period" />}
              </ChartCard>
              <ChartCard title="Payment methods" icon={<IconDonut />}>
                {s.methods.length ? <div className="method-rows">{s.methods.map((m) => (
                  <div key={m.method} className="method-row"><b>{titleCase(m.method)}</b><Meter value={(m.success_rate ?? 0) / 100} tone={(m.success_rate ?? 0) >= 90 ? "" : (m.success_rate ?? 0) >= 75 ? "amber" : "red"} label={`${m.method} success rate`} />
                    <span>{pc(m.success_rate)}</span><small>{money(m.value, cur, true)} · {m.failed} failed</small></div>))}</div> : <Empty icon={<IconDonut />} title="No payment methods yet" />}
              </ChartCard>
            </div>
          )}

          <Card title="By website" icon={<IconGlobe />} sub="Revenue, refunds and payment health for each connected website.">
            {s.sites.length === 0 ? <Empty icon={<IconGlobe />} title="No website has reported finance events" /> : (
              <div className="table-scroll"><table><thead><tr><th>Website</th><th style={{ textAlign: "right" }}>Gross</th><th style={{ textAlign: "right" }}>Refunds</th><th style={{ textAlign: "right" }}>Net</th><th style={{ textAlign: "right" }}>Failed</th><th style={{ textAlign: "right" }}>At risk</th><th style={{ textAlign: "right" }}>Success</th></tr></thead>
                <tbody>{s.sites.map((x) => <tr key={x.host}><td><button type="button" className="linkish" onClick={() => setSite(x.host)}>{x.host}</button></td><td style={{ textAlign: "right" }}>{money(x.gross, cur)}</td><td style={{ textAlign: "right" }}>{money(x.refunds, cur)}</td><td style={{ textAlign: "right" }}>{money(x.net, cur)}</td><td style={{ textAlign: "right" }}>{x.failed}</td><td style={{ textAlign: "right" }}>{money(x.failed_value, cur)}</td><td style={{ textAlign: "right" }}>{pc(x.success_rate)}</td></tr>)}</tbody></table></div>
            )}
          </Card>

          <Ledger site={site} cur={cur} />
          {s.excluded_other_currency > 0 && <p className="hint"><IconHeart /> {s.excluded_other_currency} transaction(s) in other currencies were excluded from these figures.</p>}
          <p className="hint">Operational estimates from captured events, not accounting statements. <IconActions /> Runway = cash ÷ daily net burn; coverage = (cash + forecast 30-day inflow) ÷ (obligations + forecast 30-day outflow).</p>
        </>
      )}
      {edit && s && <SettingsModal s={s} onClose={() => setEdit(false)} onSaved={r.reload} />}
    </div>
  );
}



type Tab = "weekly" | "cashflow" | "positions" | "forecast" | "stress" | "working" | "pooling" | "compliance";
const TABS: { id: Tab; label: string }[] = [
  { id: "weekly", label: "Weekly report" }, { id: "cashflow", label: "Cashflow" }, { id: "positions", label: "Cash positions" }, { id: "forecast", label: "Forecast" }, { id: "stress", label: "Stress tests" },
  { id: "working", label: "Working capital" }, { id: "pooling", label: "Pooling & sweeps" }, { id: "compliance", label: "Compliance" },
];

function Trial({ access }: { access: PlanAccess | null }) {
  const now = useServerNow(1000);
  if (!access || access.source !== "trial" || !access.trial.ends_at) return null;
  const left = Math.max(0, Math.floor((Date.parse(access.trial.ends_at) - now) / 1000));
  return <div className="trial-bar" role="status"><IconTimer /><b>Free trial</b><span>Premium for {access.trial.website_id} ends in</span><code>{hms(left)}</code></div>;
}

export function FinancePage() {
  const [centsOpen, setCentsOpen] = useState(false);
  const { me, can } = useAuth();
  const toast = useToast();
  const scoped = !!me?.scope;
  const isAdmin = can("users:manage");
  const canControl = can("finance:control");
  const [tab, setTab] = useState<Tab>("cashflow");
  const [site, setSite] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const access = useResource(api.planAccess, ["finance"]);
  const active = access.data?.active ?? true; // until the answer arrives, ask the finance endpoints themselves
  const cap = useCapture(active);
  const suite = useResource(() => api.liquiditySuite(site), ["finance"], [site, active]);
  const premiumRequired = (!!access.data && !access.data.active) || !!(suite.error && /premium|trial/i.test(suite.error) && !suite.data);
  const s = suite.data;

  async function activate() {
    setBusy(true);
    try { await api.setPlan("premium"); toast.ok("Premium activated."); access.reload(); suite.reload(); } catch (e) { toast.err((e as Error).message); } finally { setBusy(false); }
  }
  async function sample() {
    setBusy(true);
    try { const x = await api.financeSimulate(); toast.ok(`Loaded ${num(x.transactions)} sample transactions (flagged as samples).`); suite.reload(); } catch (e) { toast.err((e as Error).message); } finally { setBusy(false); }
  }
  async function act(a: "start" | "pause" | "restart" | "stop") {
    try {
      await cap.act(a);
      toast.ok({ start: "Capture started: syncing website data.", pause: "Capture paused.", restart: "Capture restarted: re-syncing.", stop: "Capture stopped." }[a]);
      if (a === "start" || a === "restart") window.setTimeout(suite.reload, 7000);
    } catch (e) { toast.err((e as Error).message); }
  }

  async function subscribe() {
    setBusy(true);
    try { await api.subscribePro(); toast.ok("Pro activated for this website. Access is back."); access.reload(); suite.reload(); } catch (e) { toast.err((e as Error).message); } finally { setBusy(false); }
  }

  if (premiumRequired) return <Upsell isAdmin={isAdmin} scoped={scoped} access={access.data} onActivate={activate} onSubscribe={subscribe} busy={busy} />;
  const st = cap.status;
  const showSync = !!st && (cap.syncing || st.state === "running");

  return (
    <div className="page fin-page">
      <PageHead eyebrow="Pro · financial liquidity" title="Finance and liquidity"
        lede="Real-time cash positions, forecasts, stress tests, working capital, pooling and compliance, built from content captured on your connected websites. All amounts are in KES."
        actions={<div className="fin-actions">
          <CentsChip open={centsOpen} onToggle={() => setCentsOpen((o) => !o)} />
          <div className="row" style={{ flexWrap: "wrap", gap: 8, justifyContent: "flex-end" }}>
          <Trial access={access.data} />
          {!scoped && s && s.banks.length > 0 && null}
          {isAdmin && !scoped ? <Button variant="ghost" className="btn-sm" busy={busy} onClick={sample}>Load sample data</Button> : canControl && <Button variant="ghost" className="btn-sm" busy={busy} onClick={sample}>Load sample data</Button>}
          </div>
        </div>} />
      <Analyst ready={!!s && (s.transactions ?? 0) > 0} open={centsOpen} onClose={() => setCentsOpen(false)} />
      <PingBar status={st} />
      <div className="fin-top">
        <CaptureControls status={st} busy={cap.busy} canControl={canControl} error={cap.error} onAct={(a) => void act(a)} />
        {showSync && st ? <SyncPanel status={st} active={cap.syncing} /> : st ? <Card title="Capture logs" icon={<IconTerminal />}><LogTerminal logs={st.logs} open /></Card> : null}
      </div>
      {suite.error && !s && <ErrorNote message={suite.error} retry={suite.reload} />}
      {s?.simulated && <Banner tone="info">This view includes flagged sample transactions. They are never produced by real sites.</Banner>}
      <div className="fin-layout">
        <div className="fin-main">
          <div className="fin-tabs" role="tablist" aria-label="Finance sections">
            {TABS.map((t) => <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} className={tab === t.id ? "on" : ""} onClick={() => setTab(t.id)}>{t.label}</button>)}
          </div>
          {tab === "weekly" ? <Weekly /> : tab === "cashflow" ? <Cashflow site={site} setSite={setSite} isAdmin={isAdmin} /> : !s ? <Skeleton rows={4} h={90} /> : (
            tab === "positions" ? <Positions s={s} /> : tab === "forecast" ? <Forecast s={s} /> : tab === "stress" ? <Stress s={s} /> : tab === "working" ? <Working s={s} /> :
            tab === "pooling" ? <Pooling s={s} canControl={canControl} scoped={scoped} reload={suite.reload} /> : <Compliance s={s} />
          )}
        </div>
      </div>
    </div>
  );
}
