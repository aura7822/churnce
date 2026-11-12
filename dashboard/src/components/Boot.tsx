import { useEffect, useState } from "react";

const STEPS: [number, string][] = [
  [200, "Loading metrics"],
  [1000, "Pulling server resources"],
  [1800, "Checking backend status"],
  [2500, "Verifying database connection"],
  [3200, "Syncing review queue and RAG window"],
  [3900, "Opening realtime channel"],
  [4600, "Thanks for waiting."],
];
const TOTAL_MS = 5200;

/** Shown for about five seconds after a successful sign-in. The messages are a scripted progress narrative;
 *  the dashboard fetches its real data once it opens. */
export function Boot({ onDone }: { onDone: () => void }) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const timers = STEPS.map(([at], i) => setTimeout(() => setShown(i + 1), at));
    const done = setTimeout(onDone, TOTAL_MS);
    return () => { timers.forEach(clearTimeout); clearTimeout(done); };
  }, [onDone]);
  const finished = shown === STEPS.length;
  return (
    <div className="boot" role="status" aria-live="polite">
      <div className="boot-card">
        <div className="script-title">Lifecycle Marketing Agent</div>
        <h1>Loading dashboard{finished ? "" : <span className="boot-dots" />}</h1>
        <div className="boot-bar" aria-hidden="true"><i style={{ width: `${Math.round((shown / STEPS.length) * 100)}%` }} /></div>
        <ul className="boot-log">
          {STEPS.slice(0, shown).map(([, text], i) => <li key={text} className={i === STEPS.length - 1 ? "last" : ""}>{text}{i === STEPS.length - 1 ? "" : "…"}</li>)}
        </ul>
      </div>
    </div>
  );
}
