import type { Consent } from "./consent";

export interface Settings {
  backendUrl: string;
  ingestKey: string;
  /** Origins (scheme + host + port) the operator explicitly authorised, e.g. "https://shop.example.com". */
  origins: string[];
  monitoring: boolean;
  /** What the site owner explicitly allowed. Monitoring stays off until the required scopes are granted. */
  consent: Consent | null;
  /** Where the dashboard is hosted, used by the "Open dashboard" button in the sign-in card. */
  dashboardUrl: string;
}

export const DEFAULTS: Settings = { backendUrl: "http://localhost:8000", ingestKey: "", origins: [], monitoring: false, consent: null, dashboardUrl: "http://localhost:5173" };

export async function loadSettings(): Promise<Settings> {
  const got = await chrome.storage.local.get("settings");
  return { ...DEFAULTS, ...(got.settings as Partial<Settings> | undefined) };
}

export async function saveSettings(patch: Partial<Settings>): Promise<Settings> {
  const next = { ...(await loadSettings()), ...patch };
  await chrome.storage.local.set({ settings: next });
  return next;
}

export function normalizeOrigin(input: string): string | null {
  try {
    const u = new URL(input.includes("://") ? input : `https://${input}`);
    if (u.protocol !== "http:" && u.protocol !== "https:") return null;
    return u.origin;
  } catch {
    return null;
  }
}

export type EventType =
  | "page_view" | "page_load" | "click" | "repeated_click" | "interaction_failure" | "form_validation_failure"
  | "search" | "search_no_results" | "abandonment" | "error_message" | "workflow_completed" | "slow_response" | "inactivity";

/** Matches the backend EventIn schema. Nothing outside this shape can be sent. */
export interface OutEvent {
  event_id: string;
  session_id: string;
  event_type: EventType;
  page_route: string;
  element_category?: string;
  event_timestamp: string;
  response_time_ms?: number;
  outcome?: string;
  consent_state: "authorized";
  site_host: string;
  meta?: Record<string, string | number | boolean>;
}
