/** Small DOM helpers shared by the settings modules. */
export const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
export const ask = <R = Record<string, unknown>>(m: Record<string, unknown>) => chrome.runtime.sendMessage(m) as Promise<R & { ok: boolean; error?: string }>;
export function icon(el: Element, name: string): void { el.querySelector("use")?.setAttribute("href", `#i-${name}`); }
export function locked(card: HTMLElement, on: boolean): void {
  card.classList.toggle("is-locked", on);
  card.querySelectorAll<HTMLElement>(":scope > *:not(.lock-veil)").forEach((e) => { e.inert = on; }); // inert: not focusable, not clickable, hidden from assistive tech while locked
}
export interface SiteIds { website_id: string; name: string; owner_name: string }
export async function siteIds(): Promise<Record<string, SiteIds>> { return ((await chrome.storage.local.get("siteIds")).siteIds as Record<string, SiteIds> | undefined) ?? {}; }
