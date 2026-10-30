import { useRef, useState } from "react";
import { useLiveMessages } from "../hooks/useLive";
import { IconDb } from "./icons";

/** Database activity indicator. Every backend message corresponds to a committed write (transactional outbox),
 *  so a flash here means the database really changed. Idle = dim tube. This is the app's only glowing element. */
const LABELS: Record<string, string> = {
  event_ingested: "event stored", chunk_created: "chunk written", pipeline_stage_changed: "stage committed", incident_updated: "incident updated",
  retrieval_completed: "retrieval logged", action_updated: "action updated", communication_updated: "email recorded", resolution_updated: "resolution saved",
  outcome_recorded: "outcome recorded", config_updated: "config saved",
};

export function DbNeon() {
  const [hot, setHot] = useState(false);
  const [last, setLast] = useState("idle");
  const [n, setN] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useLiveMessages((m) => {
    if (m.type === "hello") return;
    setLast(LABELS[m.type] ?? m.type.replace(/_/g, " "));
    setN((x) => x + 1);
    setHot(false);
    requestAnimationFrame(() => setHot(true)); // restart the flicker animation on back-to-back writes
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setHot(false), 1600);
  });
  return (
    <span key={hot ? n : "idle"} className={`db-neon ${hot ? "hot" : ""}`} role="status" aria-live="off" title="Lights up on every committed database write">
      <IconDb /><span>DB</span><span className="db-last">{last}</span>
    </span>
  );
}
