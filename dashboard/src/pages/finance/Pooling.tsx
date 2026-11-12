import { useState, type FormEvent } from "react";
import { api } from "../../services/api";
import { useToast } from "../../hooks/useToast";
import type { LiquiditySuite, SweepRule } from "../../types";
import { Badge, Banner, Button, Card, Empty, Modal, Toggle } from "../../components/ui";
import { IconBank, IconPlay, IconPlus, IconRefresh, IconTrash } from "../../components/icons";
import { dateTimeOf } from "../../services/format";
import { kes } from "./common";

const KIND_LABEL = { target_balance: "Target balance", zero_balance: "Zero balance", threshold: "Threshold" } as const;
const KIND_HELP = {
  target_balance: "Keep a fixed balance in the source account and sweep the excess to the destination.",
  zero_balance: "Sweep the entire source balance to the destination every cycle (header-account pooling).",
  threshold: "Sweep only once the source balance goes above the trigger, down to the target.",
} as const;

function RuleModal({ banks, rule, onClose, onSaved }: { banks: string[]; rule: SweepRule | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({ name: rule?.name ?? "", kind: rule?.kind ?? "target_balance", source_bank: rule?.source_bank ?? banks[0] ?? "", dest_bank: rule?.dest_bank ?? banks[1] ?? banks[0] ?? "", threshold_kes: String(rule?.threshold_kes ?? 0), target_kes: String(rule?.target_kes ?? 0) });
  const [busy, setBusy] = useState(false);
  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try { await api.saveSweepRule({ ...(rule ? { id: rule.id } : {}), name: f.name.trim(), kind: f.kind, source_bank: f.source_bank, dest_bank: f.dest_bank, threshold_kes: Number(f.threshold_kes) || 0, target_kes: Number(f.target_kes) || 0, enabled: rule?.enabled ?? true }); toast.ok("Sweeping rule saved."); onSaved(); onClose(); }
    catch (err) { toast.err((err as Error).message); } finally { setBusy(false); }
  }
  return (
    <Modal title={rule ? "Edit sweeping rule" : "New sweeping rule"} onClose={onClose}>
      <form className="stack" onSubmit={save}>
        <label className="field"><span className="label">Name</span><input className="input" required maxLength={80} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Daily M-Pesa to KCB" /></label>
        <label className="field"><span className="label">Rule type</span><select className="input" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as SweepRule["kind"] })}>{Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select><span className="hint">{KIND_HELP[f.kind]}</span></label>
        <div className="grid-2">
          <label className="field"><span className="label">From</span><input className="input" list="banks" required value={f.source_bank} onChange={(e) => setF({ ...f, source_bank: e.target.value })} /></label>
          <label className="field"><span className="label">To</span><input className="input" list="banks" required value={f.dest_bank} onChange={(e) => setF({ ...f, dest_bank: e.target.value })} /></label>
        </div>
        <datalist id="banks">{banks.map((b) => <option key={b} value={b} />)}</datalist>
        <div className="grid-2">
          {f.kind === "threshold" && <label className="field"><span className="label">Trigger above (KES)</span><input className="input" type="number" min={0} value={f.threshold_kes} onChange={(e) => setF({ ...f, threshold_kes: e.target.value })} /></label>}
          {f.kind !== "zero_balance" && <label className="field"><span className="label">Keep in source (KES)</span><input className="input" type="number" min={0} value={f.target_kes} onChange={(e) => setF({ ...f, target_kes: e.target.value })} /></label>}
        </div>
        <div className="row" style={{ justifyContent: "flex-end", gap: 8 }}><Button variant="ghost" type="button" onClick={onClose}>Cancel</Button><Button variant="clay" busy={busy} type="submit">Save rule</Button></div>
      </form>
    </Modal>
  );
}

export function Pooling({ s, canControl, scoped, reload }: { s: LiquiditySuite; canControl: boolean; scoped: boolean; reload: () => void }) {
  const toast = useToast();
  const [edit, setEdit] = useState<SweepRule | "new" | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const p = s.pooling;
  const banks = s.banks.map((b) => b.bank);
  const writable = canControl && !scoped;

  async function run() {
    setBusy("run");
    try { const r = await api.runSweeps(); toast.ok(r.executed.length ? `${r.executed.length} sweep(s) executed.` : "Nothing to sweep right now."); reload(); } catch (e) { toast.err((e as Error).message); } finally { setBusy(null); }
  }
  async function toggle(r: SweepRule, enabled: boolean) {
    setBusy(r.id);
    try { await api.saveSweepRule({ ...r, enabled }); reload(); } catch (e) { toast.err((e as Error).message); } finally { setBusy(null); }
  }
  async function del(r: SweepRule) {
    setBusy(r.id);
    try { await api.deleteSweepRule(r.id); reload(); } catch (e) { toast.err((e as Error).message); } finally { setBusy(null); }
  }

  return (
    <div className="stack">
      <div className="kpi-grid">
        <div className="clay blue"><div className="k-label">Pooled balance</div><div className="k-value">{kes(p.pooled_balance_kes, true)}</div><div className="k-note">across {banks.length} account(s)</div></div>
        <div className="clay blue"><div className="k-label">Idle cash</div><div className="k-value">{kes(p.idle_cash_kes, true)}</div><div className="k-note">above 30-day outflows</div></div>
        <div className="clay blue"><div className="k-label">Proposed sweeps</div><div className="k-value">{p.proposals.length}</div><div className="k-note">{kes(p.proposals.reduce((a, x) => a + x.amount_kes, 0), true)} to move</div></div>
      </div>
      {scoped && <Banner tone="info">Sweeping rules move cash organisation-wide, so a website-ID session can view them but not change them.</Banner>}
      <Card title="Sweeping rules" icon={<IconBank />} sub="Enabled rules run automatically about once a minute while capture is running. Transfers are recorded as position adjustments; the transaction ledger is never altered."
        actions={writable ? <><Button variant="neu" icon={<IconPlus />} onClick={() => setEdit("new")} disabled={banks.length < 1}>Add rule</Button><Button variant="clay" icon={<IconPlay />} busy={busy === "run"} onClick={run} disabled={p.proposals.length === 0}>Run now</Button></> : undefined}>
        {p.rules.length === 0 ? <Empty icon={<IconBank />} title="No sweeping rules">Add a target-balance, zero-balance or threshold rule to pool cash automatically.</Empty> : (
          <ul className="rule-list">{p.rules.map((r) => (
            <li key={r.id} className={r.enabled ? "" : "off"}>
              <div><b>{r.name}</b><div className="hint">{KIND_LABEL[r.kind]} · {r.source_bank} → {r.dest_bank}{r.kind !== "zero_balance" ? ` · keep ${kes(r.target_kes, true)}` : ""}{r.kind === "threshold" ? ` · above ${kes(r.threshold_kes, true)}` : ""}</div>{r.last_run_at && <div className="hint">Last run {dateTimeOf(r.last_run_at)}</div>}</div>
              <div className="row" style={{ gap: 8 }}>
                <Toggle checked={r.enabled} disabled={!writable || busy === r.id} label={`Enable ${r.name}`} onChange={(v) => void toggle(r, v)} />
                {writable && <><Button variant="ghost" onClick={() => setEdit(r)}>Edit</Button><Button variant="ghost" icon={<IconTrash />} aria-label={`Delete ${r.name}`} onClick={() => void del(r)} /></>}
              </div>
            </li>
          ))}</ul>
        )}
      </Card>
      <div className="grid-2">
        <Card title="Proposed transfers" icon={<IconRefresh />} sub="What the enabled rules would move right now.">
          {p.proposals.length === 0 ? <Empty icon={<IconRefresh />} title="No transfers proposed" /> : <ul className="prop-list">{p.proposals.map((x, i) => <li key={i}><b>{kes(x.amount_kes)}</b><span>{x.from_bank} → {x.to_bank}</span><small className="hint">{x.reason}</small></li>)}</ul>}
        </Card>
        <Card title="Sweep log" icon={<IconBank />} sub="Executed transfers, newest first.">
          {p.sweep_log.length === 0 ? <Empty icon={<IconBank />} title="Nothing swept yet" /> : <ul className="prop-list">{p.sweep_log.map((x) => <li key={x.id}><b>{kes(x.amount_kes)}</b><span>{x.from_bank} → {x.to_bank}</span><small className="hint">{x.rule_name} · {dateTimeOf(x.at)} <Badge tone={x.mode === "auto" ? "violet" : "blue"}>{x.mode}</Badge></small></li>)}</ul>}
        </Card>
      </div>
      {edit && <RuleModal banks={banks} rule={edit === "new" ? null : edit} onClose={() => setEdit(null)} onSaved={reload} />}
    </div>
  );
}
