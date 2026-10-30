export type Role = "administrator" | "product_analyst" | "engineer" | "marketing_operator" | "reviewer";

export interface Me {
  user: { id: string; name: string; email: string; role: Role };
  organization: { id: string; name: string };
  environment: "demo" | "production";
  permissions: string[];
}
export interface LoginResult {
  token: string;
  user: Me["user"];
  organization: Me["organization"];
  environment: Me["environment"];
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
