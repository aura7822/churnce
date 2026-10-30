import { useEffect, useState } from "react";

const STEPS: [number, string][] = [
  [200, "Loading metrics..."],
  [1000, "Pulling server resources..."],
  [1800, "Checking backend status..."],
  [2500, "Verifying database connection..."],
  [3200, "Testing RAG APIs..."],
  [3900, "Opening realtime channel..."],
  [4600, "Thanks for waiting!."],
];
const TOTAL_MS = 15000;
const FINAL_PROGRESS = 97.3;
const ACCELERATION_MS = 4300;
const HOLD_MS = 1500;
const FINALIZE_MS = TOTAL_MS - (ACCELERATION_MS + HOLD_MS);

/** Shown for about seven seconds after a successful sign-in. The progress accelerates quickly,
 * pauses near the finish line, and then opens the dashboard. */
export function Boot({ onDone }: { onDone: () => void }) {
  const [shown, setShown] = useState(0);

  useEffect(() => {
    const started = performance.now();
    let frame = 0;

    const update = (now: number) => {
      const elapsed = now - started;
      if (elapsed >= TOTAL_MS) {
        setShown(100);
        onDone();
        return;
      }
      let next = 0;
      if (elapsed < ACCELERATION_MS) {
        const t = elapsed / ACCELERATION_MS;
        next = FINAL_PROGRESS * (t * t * (3 - 2 * t));
      } else if (elapsed < ACCELERATION_MS + HOLD_MS) {
        next = FINAL_PROGRESS;
      } else {
        const t = (elapsed - ACCELERATION_MS - HOLD_MS) / FINALIZE_MS;
        next = FINAL_PROGRESS + (100 - FINAL_PROGRESS) * t;
      }

      setShown(next);
      frame = requestAnimationFrame(update);
    };

    frame = requestAnimationFrame(update);
    return () => cancelAnimationFrame(frame);
  }, [onDone]);

  const currentStep = Math.min(STEPS.length, Math.max(1, Math.ceil((shown / 100) * STEPS.length)));
  const finished = shown >= 100;

  return (
    <div className="boot" role="status" aria-live="polite">
      <div className="boot-content">
        <div className="script-title"> The Lifecycle Marketing Agent</div>
        <h1>Connecting to Dashboard...{finished ? "" : <span className="boot-dots" />}</h1>
        <div className="boot-meta">
          <div className="boot-percent">{shown.toFixed(1)}%</div>
          <div className="boot-label">Boot sequence</div>
        </div>
        <div className="boot-bar" aria-hidden="true"><i style={{ width: `${Math.min(shown, 100)}%` }} /></div>
        <ul className="boot-log">
          {STEPS.slice(0, currentStep).map(([, text], i) => <li key={text} className={i === STEPS.length - 1 ? "last" : ""}>{text}{i === STEPS.length - 1 ? "" : "…"}</li>)}
        </ul>
      </div>
    </div>
  );
}
