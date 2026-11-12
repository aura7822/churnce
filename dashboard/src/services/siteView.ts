import { useSyncExternalStore } from "react";

/** Administrator-only: the website whose captured metrics every page is limited to. Sent to the API as X-Churnce-Site, so all pages stay in sync. */
const KEY = "churnce.view-site";
type L = () => void;
const listeners = new Set<L>();
let current: string | null = (() => { try { return sessionStorage.getItem(KEY); } catch { return null; } })();

export const siteView = {
  get: () => current,
  set(host: string | null) {
    current = host;
    try { host ? sessionStorage.setItem(KEY, host) : sessionStorage.removeItem(KEY); } catch { /* storage blocked */ }
    listeners.forEach((l) => l());
  },
  subscribe(l: L) { listeners.add(l); return () => { listeners.delete(l); }; },
};

export const useSiteView = () => ({ host: useSyncExternalStore(siteView.subscribe, siteView.get, siteView.get), set: siteView.set });
