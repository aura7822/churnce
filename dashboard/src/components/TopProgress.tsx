import { useEffect, useState } from "react";
import { useLoadingCount } from "../services/loading";

/** Indeterminate bar under the top bar. Appears after 120 ms (no flicker on fast loads) and stays for at least 350 ms once shown. */
export function TopProgress() {
  const busy = useLoadingCount() > 0;
  const [show, setShow] = useState(false);
  useEffect(() => {
    let t: ReturnType<typeof setTimeout>;
    if (busy) t = setTimeout(() => setShow(true), 120);
    else t = setTimeout(() => setShow(false), 350);
    return () => clearTimeout(t);
  }, [busy]);
  return <div className={`top-progress ${show ? "on" : ""}`} role="progressbar" aria-busy={show} aria-label="Loading"><i /></div>;
}
