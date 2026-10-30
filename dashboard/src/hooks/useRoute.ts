import { useEffect, useState } from "react";

/** Tiny hash router: no dependency, deep-linkable, survives refresh behind any static host. */
export function useRoute(fallback: string): [string, (r: string) => void] {
  const read = () => (location.hash.replace(/^#\/?/, "") || fallback).split("?")[0];
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const on = () => setRoute(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return [route, (r) => { location.hash = `/${r}`; }];
}
