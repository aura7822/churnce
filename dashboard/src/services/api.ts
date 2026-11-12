import type { CodeAnalysis, CodeProject, ReportedBug, WeeklyReport } from "../types";
import { siteView } from "./siteView";
import type {
  LogsResponse,
  Action, AuditRow, Chunk, Collection, Config, Customer, Email, EventRow, Incident, IncidentDetail, LoginResult, Me,
  Metrics, Outcome, SitesResponse, SiteRow, SiteFeed, SitesSeries, Timeseries, DocFeedbackResponse, PlanInfo, PlanAccess, CaptureStatus, LiquiditySuite, SweepRule, SweepProposal, SweepLogRow, AnalystSummary, AnalystTurn, EmailsSummary, FinanceSummary, FinTxn, Role, Resolution, ResolutionSource, Retrieval, RetrievalSummary, Scenario, UserRow,
} from "../types";

const BASE = (import.meta.env?.VITE_API_URL ?? "").replace(/\/$/, "");
const V1 = `${BASE}/api/v1`;
const TOKEN_KEY = "churnce.token";

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string) {
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
  const view = siteView.get();
  if (view && tok) headers["X-Churnce-Site"] = view; // administrator looking at one website
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
    throw new ApiError(msg, res.status, (data as { code?: string } | null)?.code);
  }
  const st = (data as { server_time?: string } | null)?.server_time;
  if (st) syncClock(st);
  return data as T;
}
const get = <T,>(p: string) => request<T>("GET", p);
const post = <T,>(p: string, b?: unknown) => request<T>("POST", p, b ?? {});
const patch = <T,>(p: string, b: unknown) => request<T>("PATCH", p, b);
const put = <T,>(p: string, b: unknown) => request<T>("PUT", p, b);

export const api = {
  login: (email: string, password: string) => post<LoginResult>("/auth/login", { email, password }),
  siteLogin: (website_id: string, password: string, role: Role) => post<LoginResult>("/auth/site-login", { website_id, password, role }),
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
  editEmail: (id: string, subject: string, body: string) => patch<Email>(`/emails/${id}`, { subject, body }),
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
  sites: () => get<SitesResponse>("/sites"),
  patchSite: (id: string, b: { role?: Role; access_enabled?: boolean }) => patch<SiteRow>(`/sites/${id}`, b),
  siteFeed: (id: string, after = 0) => get<SiteFeed>(`/sites/${id}/feed?after=${after}&limit=300`),
  sitesSeries: (minutes = 15) => get<SitesSeries>(`/sites-series?minutes=${minutes}`),
  timeseries: (hours = 24) => get<Timeseries>(`/timeseries?hours=${hours}`),
  docFeedback: () => get<DocFeedbackResponse>("/docs/feedback"),
  sendDocFeedback: (rating: number, comment: string) => post<{ ok: boolean }>("/docs/feedback", { rating, comment }),
  redeemSiteAccess: (code: string) => post<LoginResult>("/auth/site-access", { code }),
  planAccess: () => get<PlanAccess>("/plan/access"),
  codeProjects: () => get<{ projects: CodeProject[] }>("/analyser/projects"),
  reportedBugs: () => get<{ bugs: ReportedBug[] }>("/analyser/bugs"),
  addGithub: (b: { repo: string; branch?: string; token?: string; name?: string; site_host?: string | null }) => post<CodeProject>("/analyser/projects/github", b),
  deleteCodeProject: (id: string) => request<{ ok: boolean }>("DELETE", `/analyser/projects/${id}`),
  analyseCode: (id: string, b: { incident_id?: string | null; description?: string }) => post<CodeAnalysis>(`/analyser/projects/${id}/analyse`, b),
  /** Zip upload with real progress (fetch cannot report upload progress). Sends the raw file as the request body. */
  uploadCodeZip: (file: File, name: string, onProgress: (pct: number) => void, site_host?: string | null) => new Promise<CodeProject>((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", `${V1}/analyser/projects/zip?name=${encodeURIComponent(name)}${site_host ? `&site_host=${encodeURIComponent(site_host)}` : ""}`);
    const tok = tokenStore.get();
    if (tok) x.setRequestHeader("Authorization", `Bearer ${tok}`);
    const view = siteView.get();
    if (view && tok) x.setRequestHeader("X-Churnce-Site", view);
    x.setRequestHeader("Content-Type", "application/zip");
    x.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(Math.round((100 * e.loaded) / e.total)); };
    x.onerror = () => reject(new ApiError("Upload failed. Check your connection and that the backend is running.", 0));
    x.onload = () => {
      let data: { detail?: unknown } & CodeProject = {} as never;
      try { data = JSON.parse(x.responseText); } catch { /* non-JSON */ }
      if (x.status >= 200 && x.status < 300) return resolve(data);
      reject(new ApiError(typeof data.detail === "string" ? data.detail : `Upload failed (${x.status})`, x.status));
    };
    x.send(file);
  }),
  weeklyReport: () => get<WeeklyReport>("/finance/weekly-report"),
  subscribePro: () => post<{ access: PlanAccess }>("/plan/subscribe", {}),
  liquiditySuite: (site?: string | null) => get<LiquiditySuite>(`/finance/liquidity${site ? `?site=${encodeURIComponent(site)}` : ""}`),
  captureStatus: () => get<CaptureStatus>("/finance/capture"),
  captureAction: (action: "start" | "pause" | "restart" | "stop") => post<CaptureStatus>("/finance/capture", { action }),
  sweepRules: () => get<{ rules: SweepRule[]; proposals: SweepProposal[]; log: SweepLogRow[] }>("/finance/sweeps"),
  saveSweepRule: (r: Partial<SweepRule> & { name: string }) => post<{ rule: SweepRule }>("/finance/sweeps", r),
  deleteSweepRule: (id: string) => request<{ ok: boolean }>("DELETE", `/finance/sweeps/${encodeURIComponent(id)}`),
  runSweeps: () => post<{ executed: SweepLogRow[] }>("/finance/sweeps/run"),
  analystSummary: () => post<AnalystSummary>("/finance/analyst/summary"),
  analystChat: (message: string, history: AnalystTurn[]) => post<{ reply: string; provider: string; model: string }>("/finance/analyst/chat", { message, history }),
  emailsSummary: () => get<EmailsSummary>("/emails/summary"),
  setAutoSend: (enabled: boolean, delay_minutes: number) => put<EmailsSummary["auto_send"]>("/emails/auto-send", { enabled, delay_minutes }),
  plan: () => get<PlanInfo>("/plan"),
  setPlan: (plan: "free" | "premium") => post<PlanInfo>("/plan", { plan }),
  financeSummary: (days = 30, site?: string | null) => get<FinanceSummary>(`/finance/summary?days=${days}${site ? `&site=${encodeURIComponent(site)}` : ""}`),
  financeTxns: (status: string, site?: string | null) => get<{ transactions: FinTxn[] }>(`/finance/transactions?status=${status}&limit=80${site ? `&site=${encodeURIComponent(site)}` : ""}`),
  financeSettings: (b: { currency: string; opening_balance: number; monthly_obligations: number }) => put<{ finance: PlanInfo["finance"] }>("/finance/settings", b),
  financeSimulate: () => post<{ transactions: number }>("/finance/simulate?days=30"),
  digest: (b: { retrieval_id?: string; query?: string }) => post<Retrieval>("/rag/digest", b),
  simulate: (scenario: string, sessions: number) => post<{ accepted: number; sessions: number }>("/demo/simulate", { scenario, sessions }),
};

export const wsUrl = () => {
  if (BASE) return BASE.replace(/^http/, "ws") + "/api/v1/stream";
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/api/v1/stream`;
};
