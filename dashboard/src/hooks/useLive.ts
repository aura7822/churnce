import { useCallback, useEffect, useRef, useState } from "react";
import { socket, type ConnState } from "../services/socket";
import type { LiveMessage } from "../types";
import { serverNow } from "../services/api";
import { loadingBus } from "../services/loading";

/** Which WebSocket message types should refresh which data. The dashboard re-reads backend state
 *  when the backend says something changed; it never guesses pipeline progress on its own. */
export type Topic = "events" | "chunks" | "metrics" | "incidents" | "retrievals" | "actions" | "emails" | "resolutions" | "outcomes" | "config" | "sites" | "finance";
const TOPICS: Record<string, Topic[]> = {
  event_ingested: ["metrics"],
  chunk_created: ["chunks", "metrics"],
  pipeline_stage_changed: ["chunks", "metrics"],
  incident_updated: ["incidents", "metrics", "actions"],
  retrieval_completed: ["retrievals", "incidents"],
  action_updated: ["actions", "incidents", "metrics", "emails"],
  communication_updated: ["emails", "metrics"],
  resolution_updated: ["resolutions", "incidents", "actions"],
  outcome_recorded: ["outcomes", "incidents"],
  config_updated: ["config", "metrics"],
  site_activity: ["sites"],
  finance_update: ["finance", "sites"],
};

export function useConnection(): ConnState {
  const [s, setS] = useState<ConnState>(socket.state);
  useEffect(() => socket.onState(setS), []);
  return s;
}

export function useLiveMessages(fn: (m: LiveMessage) => void) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => socket.on((m) => ref.current(m)), []);
}

export interface Resource<T> { data: T | null; error: string | null; loading: boolean; reload: () => void }

/** Fetch + auto-refresh when relevant live messages arrive (debounced) and once when the socket reconnects. */
export function useResource<T>(load: () => Promise<T>, topics: Topic[] = [], deps: unknown[] = []): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loadRef = useRef(load);
  loadRef.current = load;
  const alive = useRef(true);
  const seq = useRef(0);
  const firstDone = useRef<() => void>(() => undefined);

  const run = useCallback(() => {
    const mine = ++seq.current;
    loadRef.current()
      .then((d) => { if (alive.current && mine === seq.current) { setData(d); setError(null); } })
      .catch((e: Error) => { if (alive.current && mine === seq.current) setError(e.message); })
      .finally(() => { if (alive.current && mine === seq.current) setLoading(false); firstDone.current(); });
  }, []);

  useEffect(() => {
    alive.current = true; setLoading(true);
    loadingBus.begin();
    let ended = false;
    const end = () => { if (!ended) { ended = true; loadingBus.end(); } };
    run();
    const t = setInterval(() => { if (!alive.current) { end(); clearInterval(t); } }, 250); // never leave the bar running after unmount
    const stop = setTimeout(end, 8000);
    // first response ends the bar
    const off = () => { end(); clearInterval(t); clearTimeout(stop); };
    firstDone.current = off;
    return () => { alive.current = false; off(); };
  }, [run, ...deps]); // eslint-disable-line react-hooks/exhaustive-deps

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const debounced = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(run, 250);
  }, [run]);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  useLiveMessages((m) => {
    if (topics.length && (TOPICS[m.type] ?? []).some((t) => topics.includes(t))) debounced();
    if (m.type === "hello") debounced();
  });

  return { data, error, loading, reload: run };
}

/** Re-render at a steady cadence; returns the BACKEND-synchronised "now" in ms. */
export function useServerNow(intervalMs = 200): number {
  const [now, setNow] = useState(serverNow());
  useEffect(() => {
    const id = setInterval(() => setNow(serverNow()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
