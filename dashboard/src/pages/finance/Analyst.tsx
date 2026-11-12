import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../../services/api";
import type { AnalystSummary, AnalystTurn } from "../../types";
import { Badge, Button, Empty, Skeleton } from "../../components/ui";
import { IconCaretDown, IconSend, IconSparkle } from "../../components/icons";

const PRIORITY = { high: "red", medium: "amber", low: "blue" } as const;
const SUGGESTIONS = ["How is my cash position?", "Will I run out of cash in 30 days?", "Explain my liquidity coverage ratio", "Which invoices should I chase first?"];

/** Original mascot for Cents AI: a flat coin-bot. Square, no gradients, so it matches the rest of the interface. */
export function CentsMascot({ className = "cents-mascot" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 64 64" role="img" aria-label="Cents AI mascot">
      <rect x="30" y="2" width="4" height="9" fill="currentColor" /><rect x="27" y="0" width="10" height="5" fill="#ffc46b" />
      <rect x="8" y="12" width="48" height="44" fill="#ffc46b" stroke="#17231d" strokeWidth="3" />
      <rect x="14" y="19" width="36" height="22" fill="#17231d" />
      <rect x="20" y="25" width="8" height="8" fill="#fcdb32" /><rect x="36" y="25" width="8" height="8" fill="#fcdb32" />
      <rect x="22" y="48" width="20" height="4" fill="#17231d" />
      <text x="32" y="40" textAnchor="middle" fontFamily="monospace" fontWeight="700" fontSize="9" fill="#ffc46b">KES</text>
      <rect x="2" y="26" width="6" height="14" fill="#17231d" /><rect x="56" y="26" width="6" height="14" fill="#17231d" />
    </svg>
  );
}

/** Cents AI: the virtual financial analyst. Summarises the liquidity metrics (Gemini when a key is configured, rules otherwise) and answers questions. */
/** Compact launcher: sits above the top-right actions. Only a click opens the full-width window. */
export function CentsChip({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button type="button" className="cents-chip" aria-expanded={open} aria-controls="cents-panel" onClick={onToggle}>
      <CentsMascot className="cents-mascot-sm" />
      <span className="cents-chip-say"><b>Talk to Cents AI now</b></span>
      <IconCaretDown className={open ? "flip" : ""} />
    </button>
  );
}

export function Analyst({ ready, open, onClose }: { ready: boolean; open: boolean; onClose: () => void }) {
  const [sum, setSum] = useState<AnalystSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [turns, setTurns] = useState<AnalystTurn[]>([{ role: "analyst", text: "Hi, I'm Cents AI. Ask me about your cash, forecasts, stress tests, working capital or ratios." }]);
  const [msg, setMsg] = useState("");
  const [sending, setSending] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [turns, sending]);

  async function summarise() {
    setBusy(true); setErr(null);
    try { setSum(await api.analystSummary()); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  useEffect(() => { if (open && ready && !sum && !busy) void summarise(); }, [open, ready]); // eslint-disable-line react-hooks/exhaustive-deps

  async function send(text: string) {
    const t = text.trim();
    if (!t || sending) return;
    const history = turns.slice(-8);
    setTurns((x) => [...x, { role: "user", text: t }]);
    setMsg(""); setSending(true);
    try { const r = await api.analystChat(t, history); setTurns((x) => [...x, { role: "analyst", text: r.reply }]); }
    catch (e) { setTurns((x) => [...x, { role: "analyst", text: `I couldn't answer that: ${(e as Error).message}` }]); } finally { setSending(false); }
  }
  const submit = (e: FormEvent) => { e.preventDefault(); void send(msg); };

  return (
    <section className="cents" aria-label="Cents AI">
      {open && (
        <div id="cents-panel" className="cents-panel">
          <div className="cents-win-head"><CentsMascot className="cents-mascot-sm" /><b>Cents AI · virtual financial analyst</b><span className="spacer" /><button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>Close</button></div>
          <div>
            <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
              <Badge tone={sum?.provider === "gemini" ? "violet" : ""}>{sum ? (sum.provider === "gemini" ? "Gemini" : "Rules engine") : "…"}</Badge>
              <Button variant="neu" busy={busy} onClick={summarise} disabled={!ready}>Refresh</Button>
            </div>
{err && <p className="fin-err" role="alert">{err}</p>}
      <div className="cents-summary" aria-live="polite">
        {busy && !sum ? <Skeleton rows={4} h={18} /> : !sum ? <Empty icon={<IconSparkle />} title="Waiting for data">Capture some transactions and Cents AI will summarise them.</Empty> : (
          <>
            <p className="cents-lede">{sum.summary}</p>
            {sum.highlights.length > 0 && <ul className="cents-hl">{sum.highlights.map((h, i) => <li key={i}>{h}</li>)}</ul>}
            {sum.risks.length > 0 && <div className="cents-risks">{sum.risks.map((r, i) => <Badge key={i} tone="red">{r}</Badge>)}</div>}
            <ol className="cents-advice">{sum.advice.map((a, i) => <li key={i}><Badge tone={PRIORITY[a.priority]}>{a.priority}</Badge><div><b>{a.title}</b><p className="hint">{a.detail}</p></div></li>)}</ol>
            <small className="hint">Advice is generated from your captured metrics and is not financial, legal or tax advice.</small>
          </>
        )}
      </div>
          </div>
          <div className="cents-chatcol">
      <div className="cents-chat" role="log" aria-label="Chat with Cents AI" aria-live="polite">
        {turns.map((t, i) => <div key={i} className={`bubble ${t.role}`}>{t.text}</div>)}
        {sending && <div className="bubble analyst typing" aria-label="Cents AI is typing"><i /><i /><i /></div>}
        <div ref={end} />
      </div>
      <div className="cents-suggest">{SUGGESTIONS.map((q) => <button key={q} type="button" className="chip" disabled={!ready || sending} onClick={() => void send(q)}>{q}</button>)}</div>
      <form className="cents-form" onSubmit={submit}>
        <input className="input" value={msg} maxLength={800} onChange={(e) => setMsg(e.target.value)} placeholder="Ask Cents AI about your finances…" aria-label="Message to Cents AI" disabled={!ready} />
        <Button variant="clay" type="submit" busy={sending} icon={<IconSend />} disabled={!ready || !msg.trim()}>Send</Button>
      </form>
          </div>
        </div>
      )}
    </section>
  );
}
