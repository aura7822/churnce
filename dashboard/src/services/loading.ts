import { useSyncExternalStore } from "react";

/** Counts first-time page loads in flight so the thin progress bar under the top bar can show them. */
let n = 0;
const ls = new Set<() => void>();
const emit = () => ls.forEach((l) => l());
export const loadingBus = {
  begin() { n += 1; emit(); },
  end() { n = Math.max(0, n - 1); emit(); },
  subscribe(l: () => void) { ls.add(l); return () => { ls.delete(l); }; },
  get: () => n,
};
export const useLoadingCount = () => useSyncExternalStore(loadingBus.subscribe, loadingBus.get, loadingBus.get);
