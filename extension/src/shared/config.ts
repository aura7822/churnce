export interface Settings {
  backendUrl: string;
  ingestKey: string;
  /** Origins (scheme + host + port) the operator explicitly authorised, e.g. "https://shop.example.com". */
  origins: string[];
  monitoring: boolean;
  /** Pull customer email drafts from Churnce so they can be edited here. Needs an operator sign-in. */
  emailRetrieve: boolean;
  /** Send eligible drafts automatically once they are old enough to have been reviewed. */
  emailAutoSend: boolean;
  /** Minutes a draft must wait before auto-send may pick it up (time to edit it). */
  emailAutoSendDelayMin: number;
}

export const DEFAULTS: Settings = { backendUrl: "http://localhost:8000", ingestKey: "", origins: [], monitoring: false, emailRetrieve: false, emailAutoSend: false, emailAutoSendDelayMin: 10 };

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
