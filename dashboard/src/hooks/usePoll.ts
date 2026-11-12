import { useEffect, useRef } from "react";

/** Calls `fn` every `ms` while the tab is visible. Used for live graphs whose x-axis must keep moving between pushes. */
export function usePoll(fn: () => void, ms: number) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    const id = setInterval(() => { if (!document.hidden) ref.current(); }, ms);
    return () => clearInterval(id);
  }, [ms]);
}
