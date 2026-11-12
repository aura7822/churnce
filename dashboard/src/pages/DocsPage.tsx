import { useState, type FormEvent, type ReactNode } from "react";
import { api } from "../services/api";
import { useResource } from "../hooks/useLive";
import { useToast } from "../hooks/useToast";
import { Button, Card, PageHead, Segmented, Skeleton } from "../components/ui";
import { IconDocs, IconFile, IconInfo, IconLock, IconStar, IconStarFill, IconSend } from "../components/icons";
import { ago } from "../services/format";

type Tab = "guide" | "faq" | "privacy" | "eula";

const H = ({ id, children }: { id: string; children: ReactNode }) => <h3 id={id} className="doc-h">{children}</h3>;

function Guide() {
  const toc: [string, string][] = [["start", "Getting started"], ["extension", "The extension and consent"], ["finance", "Finance and liquidity"], ["siteid", "Website ID and password"], ["pipeline", "How data flows"], ["sites", "Sites and roles"], ["logs", "Logs and live activity"], ["rag", "Retrieval and reasoning"], ["email", "Win-back emails"], ["api", "API and deployment"]];
  return (
    <div className="doc-layout">
      <nav className="doc-toc" aria-label="On this page"><div className="label">On this page</div>{toc.map(([id, l]) => <a key={id} href={`#/docs?s=${id}`} onClick={(e) => { e.preventDefault(); document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" }); }}>{l}</a>)}</nav>
      <div className="doc-body">
        <H id="start">Getting started</H>
        <p>Churnce watches how customers move through a website, turns repeated friction into evidence, diagnoses likely causes, and drafts targeted win-back messages. A person approves every step that leaves the system.</p>
        <ol>
          <li>Deploy the backend and open this dashboard. Sign in with an operator account.</li>
          <li>Install the Churnce Observer extension, enter the backend URL and ingest key, and authorise a website.</li>
          <li>In the extension settings, grant the consent permissions for that website and turn monitoring on.</li>
          <li>Watch the site appear under <b>Sites</b>, then follow events through the <b>Chunk lab</b>.</li>
        </ol>
        <H id="extension">The extension and consent</H>
        <p>The extension only runs on websites the owner explicitly authorises and consents for. Monitoring stays off until the owner accepts the permissions below.</p>
        <table className="doc-table"><thead><tr><th>Permission</th><th>What is read</th><th>What is never read</th></tr></thead><tbody>
          <tr><td><b>Session</b></td><td>Anonymous session id, page route, timing, clicks by element category, error and slow-response signals</td><td>Keystrokes, form values, page text</td></tr>
          <tr><td><b>Cookies</b></td><td>Counts and flags: how many cookies, whether a session cookie exists, secure and HTTP-only ratios</td><td>Cookie values, tokens, or anything that could be used to hijack a session</td></tr>
          <tr><td><b>User data</b></td><td>A pseudonymous customer reference, only if the site publishes one on its &lt;html&gt; element (data-churnce-customer), used to link sessions and respect consent</td><td>Names, emails, phone numbers, addresses, payment details</td></tr>
          <tr><td><b>Transactions <span className="tag-premium">PRO</span></b></td><td>Transaction type, status, amount, currency, payment-method category and failure reason, plus the site&apos;s own opaque order reference</td><td>Card or account numbers, payer names, emails, addresses or any payer identity</td></tr>
        </tbody></table>
        <H id="finance">Finance and liquidity (Premium)</H>
        <p>Premium adds a cashflow and liquidity engine. Your site reports each transaction with one line of code; the extension whitelists the fields and drops everything else before sending:</p>
        <pre className="codeblock">{`window.dispatchEvent(new CustomEvent("churnce:transaction", { detail: JSON.stringify({
  txn_type: "payment",      // payment | subscription | refund | chargeback | fee | payout | invoice | bill | inventory_in | inventory_out
  status: "failed",         // success | failed | pending
  amount: 6400, currency: "KES", method: "mobile_money",
  bank: "Equity Bank",      // a label, never an account number
  due_at: "2026-12-01",     // invoices and bills only
  reason: "timeout",        // failed only
  event_id: "order_1042"    // your own reference, not a card number
}) }))`}</pre>
        <p>Transactions are stored only while Premium is active <em>and</em> the site owner granted the Transactions permission. Premium is KES 333 and every amount is shown in KES (other currencies are converted at indicative rates). Start the 72-hour free trial per website ID from the extension settings, where the plan and its features are listed. The finance page then shows connected-site ping, start, pause, restart and stop controls for real-time capture, sync progress with logs, multi-bank cash positions, 7 to 90-day forecasts, stress tests, working capital (AR, AP, stock), sweeping rules, current, quick and liquidity coverage ratios, and <b>Cents AI</b>, a virtual analyst you can chat with.</p>
        <H id="siteid">Website ID and password</H>
        <p>After you fill in the website name and owner in the extension, <b>Generate website ID and password</b> creates an ID such as <code>WS-ABC123</code> and a one-time password (only a hash is stored). Sign in from the dashboard&rsquo;s <b>Website ID</b> tab, choose Data Analyst, Developer or Website Owner, and you see only that website&rsquo;s events, chunks, incidents, customers and emails. Server-wide areas such as Backend logs show a 403 page. Name, owner and ID appear on the dashboard as soon as they are saved.</p>
        <p>Personal and sensitive values are redacted in the browser before anything is sent, and again on the backend. The owner can withdraw consent or revoke the site at any time; withdrawal takes effect on the next heartbeat.</p>
        <H id="pipeline">How data flows</H>
        <p>Events become <b>chunks</b> (short episodes). Each chunk waits at a 30-second review gate where you can edit, extend by 30 seconds, inject now or discard. Approved chunks are embedded with NVIDIA Nemotron and stored in PostgreSQL with pgvector. Incidents are built from indexed evidence.</p>
        <H id="sites">Sites and roles</H>
        <p>The <b>Sites</b> page lists every connected website. An administrator picks the dashboard role the site&rsquo;s owner or developer receives: Data Analyst, Developer or Website Owner (Admin needs a named account). Enable access from the extension settings to mint a single-use sign-in link valid for 24 hours; revoking access signs the owner out immediately. Role changes are written to the audit log.</p>
        <H id="logs">Logs and live activity</H>
        <p>Open any site to see its log lines and the extension&rsquo;s live activity. The <b>Backend logs</b> page shows server logs and health indicators including the database ping. The overview line graph plots events per connected site in real time.</p>
        <H id="rag">Retrieval and reasoning</H>
        <p>Retrieve embeds your question, finds similar evidence, then asks Gemma (through the Gemini API) to classify the lifecycle stage, summarise the evidence, name recurring patterns, separate symptoms from root causes, and propose recommendations. Every answer cites the evidence it used; if the model is unavailable a rules-based baseline answers instead.</p>
        <H id="email">Win-back emails</H>
        <p>Each issue gets its own tailored draft. Open <b>Customer emails</b> in the dashboard after signing in with your website ID to edit it, see how many emails were sent and to whom, then send manually or enable auto-send, which only picks up drafts that passed every policy check (consent, suppression, contact frequency, verified fix, approved claims) and never customers in the holdout group.</p>
        <H id="api">API and deployment</H>
        <p>All endpoints live under <code>/api/v1</code>. Deployment guides for Neon and Docker are in the repository&rsquo;s <code>docs/</code> folder.</p>
      </div>
    </div>
  );
}

const FAQS: [string, string][] = [
  ["Does the extension read passwords or personal information?", "No. It never records keystrokes or form values. The session, cookie and user-data permissions cover identifiers, counts and flags only, and the browser redacts personal values before anything is sent."],
  ["Why does the extension ask for cookie access?", "To tell whether a visitor has a live session (for example, signed in versus expired) and to spot sessions dropping mid-journey. It reports counts and flags such as whether a session cookie exists. It does not send cookie values."],
  ["Who can see a connected site's logs and activity?", "Administrators and developers."],
  ["What happens when I enable owner dashboard access?", "A single-use link is created for the role you assigned. It expires after 24 hours or at first use. The signed-in owner gets exactly that role's permissions, and you can revoke it at any time."],
  ["Can I change a site's role later?", "Yes, on the Sites page. The change applies to the owner's next request and is recorded in the audit log."],
  ["Why is a site shown as offline?", "Sites are online while their extension sent an event or heartbeat in the last 90 seconds. Check that the browser is open, monitoring is on and the backend is reachable."],
  ["What does the 30-second review gate do?", "It holds each chunk so a person can edit, extend, inject or discard it before it enters the knowledge base."],
  ["Are emails sent without approval?", "Only if you enable auto-send, and only for drafts that passed every policy check and waited the delay you chose."],
  ["Where is my data stored?", "In your PostgreSQL database (Neon in the default setup). Retention is configurable and purges run on a schedule."],
  ["The backend is asleep on a free host. What breaks?", "Nothing is lost, but timers and auto-send pause until it wakes. Use an always-on instance for production."],
];

function Faq() {
  return (
    <div className="stack">
      {FAQS.map(([q, a], i) => (
        <details key={q} className="faq" open={i === 0}><summary>{q}</summary><p>{a}</p></details>
      ))}
    </div>
  );
}

function Legal({ kind }: { kind: "privacy" | "eula" }) {
  return kind === "privacy" ? (
    <div className="doc-body legal">
      <p className="hint">Effective 1 November 2026. This is a working template for the operator of a Churnce deployment; have it reviewed by counsel for your jurisdiction before relying on it.</p>
      <H id="p1">1. Who we are</H><p>The operator of this Churnce deployment (&ldquo;we&rdquo;) is the controller of data collected through the dashboard and, for monitored websites, a processor on behalf of each website owner.</p>
      <H id="p2">2. What we collect</H>
      <ul><li><b>Session data:</b> anonymous session identifier, page routes, timings, element categories and error signals.</li><li><b>Cookie signals:</b> counts and flags (presence of a session cookie, secure and HTTP-only ratios). Cookie values are never collected.</li><li><b>User data:</b> a pseudonymous customer reference supplied by the site, and consent and suppression state.</li><li><b>Dashboard accounts:</b> name, work email, role and audit entries of actions taken.</li><li><b>Feedback:</b> ratings and comments you submit on this documentation.</li></ul>
      <H id="p3">3. What we do not collect</H><p>Keystrokes, form field values, passwords, payment details, and page content. Detected personal values are redacted in the browser and again on the server.</p>
      <H id="p4">4. Why we use it</H><p>To detect friction, diagnose likely causes, recommend fixes, and prepare win-back messages that a person approves. We do not sell data.</p>
      <H id="p5">5. Consent and website owners</H><p>Monitoring runs only on websites whose owner explicitly authorised them and accepted the extension permissions. Website owners are responsible for informing their visitors and obtaining consent where the law requires it. Consent can be withdrawn in the extension at any time.</p>
      <H id="p6">6. Service providers</H><p>Evidence text may be sent to NVIDIA (embeddings) and Google (Gemma through the Gemini API) to produce retrieval and reasoning results, and to the configured email provider to deliver approved messages. Data is stored in your PostgreSQL database.</p>
      <H id="p7">7. Retention and deletion</H><p>Events and evidence are kept for the configured retention period and then purged. Audit entries are retained to show who did what. Ask us to delete data tied to a customer reference and we will remove it from the database and the vector index.</p>
      <H id="p8">8. Security</H><p>Passwords are hashed with PBKDF2, sessions use signed expiring tokens, ingest keys are write-only and stored hashed, and secrets are masked in logs. No system is perfectly secure; report suspected issues to the operator immediately.</p>
      <H id="p9">9. Your rights</H><p>Depending on where you live you may have rights to access, correct, delete or object to processing of your data. Contact the operator of your deployment to exercise them.</p>
      <H id="p10">10. Changes and contact</H><p>We will post changes here with a new effective date. Contact the administrator of your deployment with questions.</p>
    </div>
  ) : (
    <div className="doc-body legal">
      <p className="hint">Effective 1 November 2026. A working template for the operator of a Churnce deployment; have counsel review it before use.</p>
      <H id="e1">1. Agreement</H><p>By installing the extension or using the dashboard you accept this End User Licence Agreement (&ldquo;EULA&rdquo;). If you accept for an organisation, you confirm you may bind it.</p>
      <H id="e2">2. Licence</H><p>You receive a limited, non-exclusive, non-transferable, revocable licence to use Churnce for your organisation&rsquo;s internal business purposes, subject to this EULA.</p>
      <H id="e3">3. Your responsibilities</H>
      <ul><li>Install and enable the extension only on websites you own or are authorised to monitor.</li><li>Obtain any visitor consent and give any notices the law requires, and do not use Churnce to collect sensitive personal information.</li><li>Keep credentials and ingest keys secret and assign roles on a least-privilege basis.</li><li>Review messages before they are sent. You are responsible for the content and for complying with email and marketing law.</li></ul>
      <H id="e4">4. Restrictions</H><p>You may not reverse engineer the software except where the law allows, remove notices, circumvent consent or redaction controls, use the service to harass or deceive, or resell it without permission.</p>
      <H id="e5">5. AI-generated content</H><p>Diagnoses, recommendations and email drafts are produced by AI and may be wrong or incomplete. They are suggestions for a human to check, not professional advice.</p>
      <H id="e6">6. Data</H><p>You keep ownership of your data. You grant us the rights needed to process it to provide the service, as described in the Privacy Policy.</p>
      <H id="e7">7. Availability and updates</H><p>The service may change or be interrupted, including by free-tier hosting limits. We may issue updates and discontinue features with reasonable notice.</p>
      <H id="e8">8. Warranty disclaimer</H><p>To the fullest extent permitted by law, the software is provided &ldquo;as is&rdquo; without warranties of any kind, including merchantability, fitness for a particular purpose and non-infringement.</p>
      <H id="e9">9. Limitation of liability</H><p>To the fullest extent permitted by law, we are not liable for indirect, incidental or consequential damages, or lost profits or data, and our total liability is limited to the fees you paid in the 12 months before the claim.</p>
      <H id="e10">10. Termination</H><p>We may suspend access if you breach this EULA. You may stop at any time by removing the extension and closing your account. Sections that by nature should survive will.</p>
      <H id="e11">11. Governing law</H><p>This EULA is governed by the laws of the jurisdiction named by the operator of your deployment.</p>
    </div>
  );
}

function Stars({ value, onPick, size = 26 }: { value: number; onPick?: (n: number) => void; size?: number }) {
  const [hov, setHov] = useState(0);
  const shown = hov || value;
  return (
    <div className="stars" role={onPick ? "radiogroup" : "img"} aria-label={`${value} out of 5 stars`} onMouseLeave={() => setHov(0)}>
      {[1, 2, 3, 4, 5].map((n) => {
        const on = n <= shown;
        const icon = on ? <IconStarFill style={{ fontSize: size }} /> : <IconStar style={{ fontSize: size }} />;
        return onPick
          ? <button type="button" key={n} role="radio" aria-checked={value === n} aria-label={`${n} star${n > 1 ? "s" : ""}`} className={`star ${on ? "on" : ""}`} onMouseEnter={() => setHov(n)} onClick={() => onPick(n)}>{icon}</button>
          : <span key={n} className={`star ${on ? "on" : ""}`}>{icon}</span>;
      })}
    </div>
  );
}

function Feedback() {
  const toast = useToast();
  const fb = useResource(api.docFeedback);
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!rating) return toast.err("Pick a star rating first.");
    setBusy(true);
    try { await api.sendDocFeedback(rating, comment); toast.ok("Thanks for the feedback."); setRating(0); setComment(""); fb.reload(); }
    catch (err) { toast.err((err as Error).message); } finally { setBusy(false); }
  }
  const d = fb.data;
  return (
    <Card className="feedback" title="Rate this documentation" icon={<IconStar />} sub="Tell us what helped and what was missing.">
      <div className="fb-grid">
        <div className="fb-summary">
          {!d ? <Skeleton rows={2} h={30} /> : (<>
            <div className="fb-avg">{d.count ? d.average.toFixed(1) : "–"}<small>/ 5</small></div>
            <Stars value={Math.round(d.average)} size={20} />
            <span className="hint">{d.count} rating{d.count === 1 ? "" : "s"}</span>
            <div className="fb-bars">{[5, 4, 3, 2, 1].map((n) => <div key={n} className="fb-bar"><span>{n}</span><div><i style={{ width: `${d.count ? (d.distribution[String(n)] / d.count) * 100 : 0}%` }} /></div><span>{d.distribution[String(n)]}</span></div>)}</div>
          </>)}
        </div>
        <form onSubmit={submit} className="stack">
          <div className="field"><span className="label">Your rating</span><Stars value={rating} onPick={setRating} /></div>
          <div className="field"><label htmlFor="fbc">Comment (optional)</label><textarea id="fbc" className="input" rows={4} maxLength={1000} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="What would make this page better?" /><span className="hint">{comment.length}/1000</span></div>
          <div><Button variant="clay" busy={busy} icon={<IconSend />} type="submit">Submit feedback</Button></div>
        </form>
      </div>
      {d && d.entries.length > 0 && (
        <div className="fb-list">
          {d.entries.slice(0, 8).map((e) => (
            <div key={e.id} className="fb-item"><div className="row" style={{ justifyContent: "space-between" }}><b>{e.author}{e.mine ? " (you)" : ""}</b><span className="hint">{ago(e.created_at)}</span></div><Stars value={e.rating} size={14} />{e.comment && <p>{e.comment}</p>}</div>
          ))}
        </div>
      )}
    </Card>
  );
}

export function DocsPage() {
  const [tab, setTab] = useState<Tab>("guide");
  return (
    <div className="page docs">
      <PageHead eyebrow="Help centre" title="Documentation" lede="How Churnce works, what the extension may access, answers to common questions, and the legal terms." />
      <Segmented<Tab> value={tab} onChange={setTab} options={[
        { id: "guide", label: "Documentation", icon: <IconDocs /> }, { id: "faq", label: "FAQs", icon: <IconInfo /> },
        { id: "privacy", label: "Privacy policy", icon: <IconLock /> }, { id: "eula", label: "EULA", icon: <IconFile /> },
      ]} />
      <Card className="doc-card">{tab === "guide" ? <Guide /> : tab === "faq" ? <Faq /> : <Legal kind={tab} />}</Card>
      <Feedback />
    </div>
  );
}
