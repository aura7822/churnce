import type {
  LogsResponse,
  Action, AuditRow, Chunk, Collection, Config, Customer, Email, EventRow, Incident, IncidentDetail, LoginResult, Me,
  Metrics, Outcome, Resolution, ResolutionSource, Retrieval, RetrievalSummary, Scenario, UserRow,
} from "../types";

const BASE = (import.meta.env?.VITE_API_URL ?? "").replace(/\/$/, "");
const V1 = `${BASE}/api/v1`;
const TOKEN_KEY = "churnce.token";

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

// ── token storage (sessionStorage: cleared when the tab closes; never logged) ──
let memoryToken: string | null = null;
export const tokenStore = {
  get(): string | null {
    if (memoryToken) return memoryToken;
    try { memoryToken = sessionStorage.getItem(TOKEN_KEY); } catch { /* storage blocked */ }
    return memoryToken;
  },
  set(t: string) { memoryToken = t; try { sessionStorage.setItem(TOKEN_KEY, t); } catch { /* ignore */ } },
  clear() { memoryToken = null; try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ } },
};

// ── server clock sync: countdowns must follow the backend's clock, not the browser's ──
let clockOffsetMs = 0;
export const serverNow = () => Date.now() + clockOffsetMs;
export function syncClock(serverTime?: string | null) {
  if (!serverTime) return;
  const t = Date.parse(serverTime);
  if (!Number.isNaN(t)) clockOffsetMs = t - Date.now();
}

let onUnauthorized: (() => void) | null = null;
export const setUnauthorizedHandler = (fn: () => void) => { onUnauthorized = fn; };

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const tok = tokenStore.get();
  if (tok) headers.Authorization = `Bearer ${tok}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`${V1}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError("Cannot reach the Churnce API. Check that the backend is running.", 0);
  }
  if (res.status === 401 && tok && !path.startsWith("/auth/")) { tokenStore.clear(); onUnauthorized?.(); }
  const text = await res.text();
  let data: unknown = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* non-JSON error body */ }
  if (!res.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    const msg = typeof detail === "string" ? detail
      : Array.isArray(detail) ? detail.map((d: { msg?: string; loc?: unknown[] }) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`).join("; ")
      : `Request failed (${res.status})`;
    throw new ApiError(msg, res.status);
  }
  const st = (data as { server_time?: string } | null)?.server_time;
  if (st) syncClock(st);
  return data as T;
}
const get = <T,>(p: string) => request<T>("GET", p);
const post = <T,>(p: string, b?: unknown) => request<T>("POST", p, b ?? {});
const patch = <T,>(p: string, b: unknown) => request<T>("PATCH", p, b);

export const api = {
  login: (email: string, password: string) => post<LoginResult>("/auth/login", { email, password }),
  me: () => get<Me>("/me"),
  metrics: () => get<Metrics>("/metrics"),
  events: (limit = 150) => get<{ events: EventRow[] }>(`/events?limit=${limit}`),
  chunks: (state?: string, limit = 100) => get<{ chunks: Chunk[]; server_time: string }>(`/chunks?limit=${limit}${state ? `&state=${state}` : ""}`),
  pendingChunks: () => get<{ chunks: Chunk[]; server_time: string }>("/chunks/pending"),
  chunk: (id: string) => get<Chunk>(`/chunks/${id}`),
  editChunk: (id: string, version: number, summary: string) => patch<Chunk>(`/chunks/${id}`, { version, summary }),
  holdChunk: (id: string) => post<Chunk>(`/chunks/${id}/hold`),
  approveChunk: (id: string, version?: number) => post<Chunk>(`/chunks/${id}/approve`, version === undefined ? {} : { version }),
  extendChunk: (id: string) => post<Chunk>(`/chunks/${id}/extend`),
  discardChunk: (id: string) => post<Chunk>(`/chunks/${id}/discard`),
  retrievals: () => get<{ retrievals: RetrievalSummary[] }>("/rag/retrievals?limit=30"),
  retrieval: (id: string) => get<Retrieval>(`/rag/retrievals/${id}`),
  ragSearch: (query: string, collections?: string[]) => post<Retrieval>("/rag/search", { query, collections }),
  collections: () => get<{ collections: Collection[] }>("/rag/collections"),
  addDocument: (d: { collection: string; source_ref: string; title: string; body: string }) => post<{ passages: number; unchanged: boolean }>("/rag/documents", d),
  incidents: () => get<{ incidents: Incident[] }>("/incidents"),
  incident: (id: string) => get<IncidentDetail>(`/incidents/${id}`),
  analyze: (id: string) => post<Incident>(`/incidents/${id}/analyze`),
  evaluate: (id: string) => post<{ outcomes: Outcome[] }>(`/incidents/${id}/evaluate`),
  outcomes: () => get<{ outcomes: Outcome[] }>("/outcomes"),
  recommendations: () => get<{ recommendations: Action[] }>("/recommendations"),
  approveAction: (id: string) => post<Action>(`/actions/${id}/approve`),
  rejectAction: (id: string) => post<Action>(`/actions/${id}/reject`),
  resolutions: () => get<{ resolutions: Resolution[] }>("/resolutions"),
  createResolution: (d: { incident_id: string; issue_category: string; sources: ResolutionSource[]; approved_claims: string[]; segment_available: boolean }) => post<Resolution>("/resolutions", d),
  addSource: (id: string, source: ResolutionSource) => post<Resolution>(`/resolutions/${id}/sources`, { source }),
  emails: () => get<{ emails: Email[] }>("/emails"),
  approveEmail: (id: string) => post<Email>(`/emails/${id}/approve`),
  rejectEmail: (id: string) => post<Email>(`/emails/${id}/reject`),
  sendEmail: (id: string) => post<Email>(`/emails/${id}/send`),
  logs: (after = 0, level: "INFO" | "WARNING" | "ERROR" = "INFO") => get<LogsResponse>(`/logs?after=${after}&level=${level}&limit=400`),
  audit: (limit = 120) => get<{ audit: AuditRow[] }>(`/audit?limit=${limit}`),
  config: () => get<Config>("/config"),
  patchConfig: (c: Partial<Config>) => patch<Config>("/config", c),
  rotateKey: () => post<{ ingest_key: string; note: string }>("/config/rotate-key"),
  runRetention: () => post<Record<string, number>>("/governance/retention/run"),
  customers: () => get<{ customers: Customer[] }>("/customers"),
  patchCustomer: (id: string, b: { consent?: string; suppressed?: boolean }) => patch<Customer>(`/customers/${id}`, b),
  users: () => get<{ users: UserRow[]; roles: string[] }>("/users"),
  scenarios: () => get<{ scenarios: Scenario[]; enabled: boolean }>("/demo/scenarios"),
  simulate: (scenario: string, sessions: number) => post<{ accepted: number; sessions: number }>("/demo/simulate", { scenario, sessions }),
};

export const wsUrl = () => {
  if (BASE) return BASE.replace(/^http/, "ws") + "/api/v1/stream";
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/api/v1/stream`;
};
