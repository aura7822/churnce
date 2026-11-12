import { useCallback, useEffect, useRef, useState } from "react";
import { api, serverNow } from "../../services/api";
import { useLiveMessages } from "../../hooks/useLive";
import type { CaptureStatus } from "../../types";

/** Polls capture status: every 1.5 s while a sync is running, every 5 s otherwise, and immediately on finance/site live messages. */
export function useCapture(enabled: boolean) {
  const [status, setStatus] = useState<CaptureStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const alive = useRef(true);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const syncing = (s: CaptureStatus | null) => !!s && s.state === "running" && (s.sites.some((x) => x.sync === "syncing") || (!!s.syncing_until && new Date(s.syncing_until).getTime() > serverNow()));

  const load = useCallback(async () => {
    try { const s = await api.captureStatus(); if (alive.current) { setStatus(s); setError(null); } return s; }
    catch (e) { if (alive.current) setError((e as Error).message); return null; }
  }, []);

  useEffect(() => {
    alive.current = true;
    if (!enabled) return () => { alive.current = false; };
    let stop = false;
    const loop = async () => {
      const s = await load();
      if (!stop) timer.current = setTimeout(loop, syncing(s) ? 1500 : 5000);
    };
    void loop();
    return () => { stop = true; alive.current = false; if (timer.current) clearTimeout(timer.current); };
  }, [enabled, load]);

  useLiveMessages((m) => { if (enabled && (m.type === "finance_update" || m.type === "site_activity")) void load(); });

  const act = useCallback(async (action: "start" | "pause" | "restart" | "stop") => {
    setBusy(action);
    try { const s = await api.captureAction(action); setStatus(s); setError(null); return s; }
    finally { setBusy(null); }
  }, []);

  return { status, error, busy, act, reload: load, syncing: syncing(status) };
}
