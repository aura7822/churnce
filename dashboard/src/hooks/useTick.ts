import { useEffect, useState } from "react";

/** Re-renders every `ms` milliseconds; used for live countdowns. */
export function useTick(ms = 1000): number {
  const [n, setN] = useState(0);
  useEffect(() => { const t = setInterval(() => setN((x) => x + 1), ms); return () => clearInterval(t); }, [ms]);
  return n;
}
