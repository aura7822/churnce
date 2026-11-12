export type Role = "administrator" | "data_analyst" | "developer" | "website_owner";
/** Present when the user signed in with a website ID: every query is limited to that website. */
export interface SiteScope { site_host: string; website_id: string; name: string; owner_name: string }

export interface Me {
  user: { id: string; name: string; email: string; role: Role };
  organization: { id: string; name: string };
  environment: "demo" | "production";
  permissions: string[];
  scope: SiteScope | null;
  view?: SiteScope | null;
}
export interface LoginResult {
  token: string;
  user: Me["user"];
  organization: Me["organization"];
  environment: Me["environment"];
  scope?: SiteScope | null;
}

export interface EventRow {
  id: string;
  session_id: string;
  event_type: string;
  page_route: string;
  journey_stage: string;
  element_category: string | null;
  outcome: string | null;
  response_time_ms: number | null;
  event_timestamp: string;
  received_at?: string;
  redactions: number;
  chunk_id?: string | null;
  processing_status?: "pending" | "chunked" | "no_episode";
  simulated: boolean;
}

export type ChunkState =
  | "CREATED" | "PENDING_REVIEW" | "APPROVED" | "VALIDATING" | "REJECTED" | "DISCARDED"
  | "QUEUED_FOR_INGESTION" | "EMBEDDING" | "INDEXED" | "AVAILABLE_FOR_RETRIEVAL";

export interface Chunk {
  id: string;
  session_id: string;
  journey_stage: string;
  signal: string;
  issue_signature: string;
  summary: string;
  original_summary: string;
  events: string[];
  source_event_ids: string[];
  observations: Record<string, string | number | boolean | null>;
  sensitivity_status: "clean" | "filtered" | "flagged";
  state: ChunkState;
  stage: string;
  version: number;
  review_mode: "auto" | "manual";
  review_deadline: string | null;
  held: boolean;
  seconds_remaining: number | null;
  validation_errors: string[];
  created_at: string;
  updated_at: string;
  approved_by: string | null;
  edited_by: string | null;
  indexed_at: string | null;
  edited: boolean;
  simulated: boolean;
  source_events?: EventRow[];
}

export interface Candidate {
  evidence_id: string;
  collection: string;
  source_ref: string;
  title: string;
  snippet: string;
  vector_score: number;
  rerank_score: number;
  effective_at: string;
  age_days: number;
  access: string;
  kept: boolean;
  dropped_reason: string | null;
}
export interface Retrieval {
  id: string;
  incident_id: string | null;
  purpose: string;
  query: string;
  filters: Record<string, unknown>;
  candidates: Candidate[];
  context: string;
  embedding_provider: string;
  rerank_provider: string;
  latency_ms: number;
  created_at: string;
  reasoning?: Reasoning | null;
}
export interface Reasoning {
  provider: string; notes: string[]; latency_ms: number;
  email_draft?: { subject: string; body: string; issue: string; generated_by: string; preview: boolean } | null;
  answer: {
    lifecycle_stage: string; summary: string; recurring_patterns: string[];
    causes: { description: string; kind: "symptom" | "root_cause"; confidence: number; evidence_ids: string[] }[];
    feature_requests: string[]; ux_problems: string[];
    recommendations: { action: string; rationale: string; priority: string; evidence_ids: string[] }[];
    marketing_draft_notes: string[]; unresolved_questions: string[]; evidence_ids: string[]; confidence: number;
  };
}
export interface RetrievalSummary {
  id: string; incident_id: string | null; purpose: string; query: string; kept: number; candidates: number; latency_ms: number; created_at: string;
}

export interface Hypothesis { description: string; confidence: number; evidence_ids: string[] }
export interface Incident {
  id: string;
  title: string;
  issue_signature: string;
  journey_stage: string;
  signal: string;
  incident_type: string;
  status: string;
  severity: "low" | "medium" | "high" | "critical";
  severity_score: number;
  affected_sessions: number;
  chunk_ids: string[];
  lifecycle_stage: string;
  observed_facts: string[];
  hypotheses: Hypothesis[];
  evidence_ids: string[];
  unresolved_questions: string[];
  recommended_action: { type?: string; priority?: string; reason?: string };
  customer_message_eligible: boolean;
  analysis_provider: string;
  analysis_notes: string[];
  last_retrieval_id: string | null;
  regression_count: number;
  resolution_id: string | null;
  first_seen_at: string;
  last_seen_at: string;
  analyzed_at: string | null;
  resolved_at: string | null;
  simulated: boolean;
}
export interface IncidentDetail extends Incident {
  chunks: { id: string; summary: string; session_id: string; created_at: string }[];
  actions: Action[];
  retrieval: Retrieval | null;
  resolution: Resolution | null;
  outcomes: Outcome[];
}

export interface PolicyCheck { name: string; passed: boolean; detail: string }
export interface Action {
  id: string;
  incident_id: string;
  incident_title?: string | null;
  resolution_id: string | null;
  type: string;
  category: "engineering" | "support" | "marketing" | "analytical";
  title: string;
  rationale: string;
  priority: string;
  score: number;
  score_breakdown: Record<string, unknown>;
  payload: Record<string, unknown>;
  status: string;
  policy_result: { allowed?: boolean; requires_approval?: boolean; checks?: PolicyCheck[] };
  decided_by: string | null;
  decided_at: string | null;
  executed_at: string | null;
  execution_result: Record<string, unknown>;
  error: string | null;
  created_at: string;
}

export interface ResolutionSource { type: "release" | "test_run" | "telemetry" | "engineering_approval"; ref: string; status: string; detail?: string }
export interface Resolution {
  resolution_id: string;
  incident_id: string;
  issue_category: string;
  resolution_status: "verified" | "pending_verification";
  verification_sources: ResolutionSource[];
  approved_claims: string[];
  segment_available: boolean;
  email_eligible: boolean;
  verification_notes: string[];
  verified_at: string | null;
  created_by: string;
  created_at: string;
}

export interface Email {
  id: string;
  incident_id: string;
  resolution_id: string;
  customer_id: string;
  customer_ref: string | null;
  recipient: string | null;
  subject: string;
  body: string;
  claims_used: string[];
  status: "draft" | "approved" | "sent_simulated" | "blocked" | "rejected";
  policy_result: { checks?: PolicyCheck[] };
  holdout: boolean;
  generated_by: string;
  approved_by: string | null;
  approved_at: string | null;
  sent_at: string | null;
  created_at: string;
}

export interface Outcome {
  id: string;
  incident_id: string;
  resolution_id: string | null;
  metric: string;
  baseline_value: number | null;
  post_value: number | null;
  n_baseline: number;
  n_post: number;
  method: string;
  strength: "insufficient" | "low" | "moderate" | "strong";
  details: { caveats?: string[]; [k: string]: unknown };
  simulated: boolean;
  created_at: string;
}

export interface Metrics {
  events_total: number;
  events_last_hour: number;
  sessions_total: number;
  chunks_total: number;
  chunks_pending_review: number;
  chunks_in_flight: number;
  chunks_indexed: number;
  chunks_rejected: number;
  chunks_discarded: number;
  chunk_states: Record<string, number>;
  incidents_active: number;
  incidents_total: number;
  recommendations_total: number;
  actions_awaiting_approval: number;
  actions_completed: number;
  actions_failed: number;
  emails_draft: number;
  emails_approved: number;
  processing_latency_ms: { p50: number | null; p95: number | null; samples: number };
  environment: "demo" | "production";
  monitoring_enabled: boolean;
  health: {
    scheduler: { healthy: boolean; last_tick: string | null; ticks: number; last_error: string | null };
    realtime_subscribers: number;
    providers: {
      llm: { provider: string; label: string; ready: boolean; fallback: string };
      embeddings: { provider: string; model: string; ready: boolean };
      rerank: { provider: string; ready: boolean };
    };
    knowledge: Record<string, number>;
  };
  server_time: string;
}

export interface AuditRow {
  id: string; actor: string; action: string; entity_type: string; entity_id: string;
  from_state: string | null; to_state: string | null; detail: Record<string, unknown>; ts: string;
}

export interface Config {
  site_name: string;
  environment: string;
  authorized_domains: string[];
  allowed_event_types: string[];
  ingest_key_prefix: string;
  monitoring_enabled: boolean;
  review_policy: "auto_approve_filtered" | "manual" | "restricted";
  review_seconds: number;
  retention_days: number;
  journey_map: Record<string, string>;
  holdout_pct: number;
  contact_frequency_days: number;
  brand_tone: string;
  cta_url: string;
  updated_at: string;
}

export interface Customer { id: string; ref: string; email: string | null; consent: "opt_in" | "opt_out" | "unknown"; suppressed: boolean; last_contacted_at: string | null }
export interface UserRow { id: string; name: string; email: string; role: Role; active: boolean }
export interface Scenario { id: string; label: string; description: string }
export interface Collection { name: string; passages: number }

export interface LiveMessage { type: string; ts?: string; server_time?: string; [k: string]: unknown }

export interface LogLine { id: number; ts: string; level: "INFO" | "WARNING" | "ERROR" | "CRITICAL"; logger: string; message: string }
export interface LogsResponse {
  logs: LogLine[];
  buffered: number;
  server_time: string;
  indicators: {
    database: { ok: boolean; latency_ms: number; error: string | null; engine: string; host: string; neon: boolean; pooled: boolean; tls: string | null; pool: { size?: number; in_use?: number; overflow?: number } };
    scheduler: { healthy: boolean; last_tick: string | null; ticks: number; last_error: string | null };
    realtime_subscribers: number;
    providers: Metrics["health"]["providers"];
    errors_5m: number; warnings_5m: number; uptime_seconds: number; environment: string; version: string;
  };
}

// ── connected websites, series, documentation feedback ──
export interface SiteRow {
  id: string; host: string; role: Role; access_enabled: boolean; online: boolean; monitoring: boolean; event_count: number;
  website_id: string | null; name: string; owner_name: string; has_credentials: boolean;
  consent: { scopes: ("session" | "cookies" | "user_data" | "finance")[]; accepted_at: string | null; extension_version: string | null };
  consented: boolean;
  cookie_summary: { total?: number; session_cookies?: number; secure?: number; http_only?: number; session_present?: boolean };
  first_seen: string; last_seen: string;
  plan?: { active: boolean; source: "org" | "pro" | "trial" | null; subscribed: boolean; trial_used: boolean; trial_ends_at: string | null; seconds_left: number };
}
export interface SitesResponse { sites: SiteRow[]; roles: Role[]; server_time: string }
export interface FeedRow { id: number; ts: string; kind: "log" | "activity"; level: "INFO" | "WARNING" | "ERROR"; message: string }
export interface SiteFeed { site: SiteRow; rows: FeedRow[]; server_time: string }
export interface SitesSeries { step_seconds: number; buckets: string[]; series: { host: string; counts: number[]; total: number; online: boolean }[]; server_time: string }
export interface Timeseries {
  hours: string[]; events: number[]; chunks: number[]; incidents: number[];
  event_types: { label: string; value: number }[]; journey_stages: { label: string; value: number }[]; server_time: string;
}
export interface DocFeedbackResponse {
  average: number; count: number; distribution: Record<string, number>;
  entries: { id: string; author: string; rating: number; comment: string; created_at: string; mine: boolean }[];
}

// ── premium plan and finance / liquidity ──
export interface PlanInfo {
  plan: "free" | "premium"; name: string; price_kes?: { free: number; premium: number }; features: { id: string; title: string; text: string }[]; activated_at: string | null; activated_by: string | null;
  billing: string; finance: { currency: string; opening_balance: number; monthly_obligations: number };
}
export interface FinKpis {
  transactions: number; payments_succeeded: number; payments_failed: number; payments_pending: number; gross_revenue: number; refunds: number; chargebacks: number; fees: number;
  payouts: number; outflow: number; net_cashflow: number; success_rate: number | null; avg_order_value: number | null; refund_rate: number | null; chargeback_rate: number | null;
  failed_value: number; pending_value: number;
}
export interface FinForecastDay { date: string; value: number; low: number; high: number; outflow: number; net: number }
export interface FinanceSummary {
  currency: string; days: number; captured: number; excluded_other_currency: number; kpis: FinKpis; previous: FinKpis;
  deltas: { gross_revenue: number | null; net_cashflow: number | null; failed: number | null; success_rate_pts: number | null };
  series: { dates: string[]; inflow: number[]; outflow: number[]; net: number[]; failed_value: number[]; failed_count: number[]; count: number[] };
  liquidity: { cash_position: number; opening_balance: number; monthly_obligations: number; avg_daily_net: number; runway_days: number | null; self_funding: boolean; coverage_ratio: number | null; settled_to_owner: number; health: { score: number; band: "healthy" | "watch" | "at_risk" } };
  forecast: { ready: boolean; reason: string | null; horizon_days: number; days: FinForecastDay[]; next_7_days_income: number | null; next_14_days_income: number | null; trend_per_day: number | null; band: string };
  failure_reasons: { reason: string; count: number; value: number; share: number | null }[];
  methods: { method: string; succeeded: number; failed: number; value: number; success_rate: number | null }[];
  sites: { host: string; gross: number; refunds: number; net: number; succeeded: number; failed: number; failed_value: number; success_rate: number | null }[];
  anomalies: { date: string; kind: string; value: number; expected: number | null; z: number | null }[];
  insights: { tone: "good" | "warn" | "bad" | "info"; text: string }[];
  sites_available: string[]; site: string | null; simulated: boolean; settings: PlanInfo["finance"]; server_time: string;
}
export interface FinTxn { id: string; site_host: string; txn_type: string; status: "success" | "failed" | "pending"; amount: number; currency: string; native_amount?: number; native_currency?: string; bank?: string | null; due_at?: string | null; method: string | null; reason: string | null; retryable: boolean; ts: string; simulated: boolean }

// ── plans, trial, capture control, liquidity suite, Cents AI, emails (contract shared by backend, dashboard, extension) ──
export interface TrialInfo { available: boolean; active: boolean; used: boolean; ends_at: string | null; seconds_left: number; website_id: string | null }
export interface PlanAccess {
  plan: "free" | "premium"; active: boolean; source: "org" | "pro" | "trial" | null; subscribed?: boolean; price_kes: { free: number; premium: number };
  trial: TrialInfo; trial_sites: { website_id: string; host: string; ends_at: string; seconds_left: number }[];
}
export type CaptureState = "running" | "paused" | "stopped";
export interface CaptureSite {
  host: string; name: string; website_id: string | null; online: boolean; last_seen: string | null; seconds_since_seen: number | null; rtt_ms: number | null;
  txn_count: number; last_txn_at: string | null; sync: "idle" | "syncing" | "live" | "paused" | "stopped";
}
export interface CaptureStatus {
  state: CaptureState; since: string | null; sites: CaptureSite[]; logs: { ts: string; level: "INFO" | "WARNING" | "ERROR"; host: string; msg: string }[];
  syncing_until: string | null; server_time: string;
}
export type Verdict = "pass" | "warn" | "fail";
export interface BankPosition { bank: string; currency: string; native_balance: number; balance_kes: number; inflow_kes_30d: number; outflow_kes_30d: number; share_pct: number }
export interface HorizonRow { days: number; inflow: number; outflow: number; net: number; low: number; high: number; closing_cash: number }
export interface StressRow { id: string; name: string; description: string; shocks: string[]; min_cash: number; closing_cash: number; runway_days: number | null; lcr: number | null; current_ratio: number | null; verdict: Verdict }
export interface WorkingCapital {
  ar: { balance: number; overdue: number; count: number; dso: number | null };
  ap: { balance: number; overdue: number; count: number; dpo: number | null };
  inventory: { value: number; dio: number | null };
  ccc: number | null; working_capital: number;
  recommendations: { id: string; title: string; detail: string; cash_release_kes: number }[];
}
export interface SweepRule { id: string; name: string; kind: "target_balance" | "zero_balance" | "threshold"; source_bank: string; dest_bank: string; threshold_kes: number; target_kes: number; enabled: boolean; last_run_at: string | null }
export interface SweepProposal { rule_id: string; from_bank: string; to_bank: string; amount_kes: number; reason: string }
export interface SweepLogRow { id: string; at: string; rule_id: string; rule_name: string; from_bank: string; to_bank: string; amount_kes: number; mode: "auto" | "manual" }
export interface Ratio { value: number | null; threshold: number; status: Verdict; label: string }
export interface LiquiditySuite {
  currency: "KES"; as_of: string; simulated: boolean; transactions?: number;
  banks: BankPosition[]; currencies: { currency: string; balance_native: number; balance_kes: number; fx_rate_to_kes: number }[];
  forecast: { ready: boolean; horizons: HorizonRow[]; series: { date: string; inflow: number; outflow: number; net: number; cash: number; low: number; high: number }[] };
  stress: StressRow[]; working_capital: WorkingCapital;
  pooling: { rules: SweepRule[]; proposals: SweepProposal[]; pooled_balance_kes: number; idle_cash_kes: number; sweep_log: SweepLogRow[] };
  compliance: { current_ratio: Ratio; quick_ratio: Ratio; lcr: Ratio; hqla: number; net_outflow_30d: number; notes: string[] };
}
export interface AnalystAdvice { title: string; detail: string; priority: "high" | "medium" | "low" }
export interface AnalystSummary { summary: string; highlights: string[]; advice: AnalystAdvice[]; risks: string[]; provider: string; model: string; generated_at: string }
export interface AnalystTurn { role: "user" | "analyst"; text: string }
export interface EmailsSummary {
  sent_count: number; simulated_count: number; draft_count: number; blocked_count: number;
  auto_send: { enabled: boolean; delay_minutes: number; smtp_configured: boolean };
  recipients: { id: string; customer_ref: string; email_masked: string; subject: string; sent_at: string | null; delivery: "smtp" | "simulated"; issue: string }[];
  server_time: string;
}

// ── weekly report ──
export interface WeekWindow { inflow: number; outflow: number; net: number; failed: number; failed_amount: number; succeeded: number; pending: number; failure_rate_pct: number; refunds: number; chargebacks: number; fees: number; top_failure_reasons: { reason: string; count: number }[]; top_sites: { site: string; inflow: number }[] }
export interface WeeklyReport {
  period: { from: string; to: string; days: number }; currency: "KES"; headline: string; week: WeekWindow; previous_week: WeekWindow;
  change_pct: { inflow: number | null; failed: number | null; net: number | null };
  cash: { total: number; banks: { bank: string; balance_kes: number; share_pct: number }[]; forecast_7: { days: number; net: number; closing_cash: number; low: number } | null; forecast_30: { days: number; net: number; closing_cash: number; low: number } | null };
  ratios: { current_ratio: number | null; quick_ratio: number | null; lcr: number | null; current_status: string; quick_status: string; lcr_status: string };
  working_capital: { ar: unknown; ap: unknown; inventory: unknown; ccc_days: number | null; net: number };
  captured: { events_total: number; events_last_hour: number; chunks_indexed: number; incidents_active: number; emails_draft: number; emails_approved: number; actions_awaiting_approval: number; actions_completed: number };
  required_actions: { priority: "high" | "medium" | "low"; title: string; detail: string; owner: string }[];
  advice: { title: string; detail: string }[];
  scope: SiteScope | null; server_time: string;
}

// ── codebase analyser ──
export interface CodeProject { id: string; name: string; source: "zip" | "github"; repo: string; branch: string; status: string; error: string; site_host: string | null; files: number; lines: number; stats: { languages?: Record<string, number>; issues?: number; high_issues?: number }; created_by: string; created_at: string; analysed_at: string | null }
export interface ReportedBug { id: string; title: string; severity: string; signal: string; journey_stage: string; affected_sessions: number; status: string }
export interface BlastLayer { depth: number; files: string[]; count: number }
export interface Blast { path: string; affected: number; percent_of_codebase: number; risk: "low" | "medium" | "high"; layers: BlastLayer[]; entry_points: string[]; tests: string[]; depends_on: string[] }
export interface CodeCandidate { path: string; confidence: number; score: number; reasons: string[]; matches: { line: number; text: string }[]; blast: Blast }
export interface CodeIssue { path: string; line: number; rule: string; severity: "high" | "medium" | "low"; message: string }
export interface CodeAnalysis {
  signals: { kind: string; tokens: string[]; phrases: string[]; routes: string[] }; candidates: CodeCandidate[]; what_if: { scenario: string; effect: string; advice: string }[]; related_issues: CodeIssue[];
  stats: { files: number; lines: number; languages: Record<string, number>; issues: number; high_issues: number }; bug: { title: string; severity?: string; signal?: string; incident_id: string | null }; project: CodeProject;
}
