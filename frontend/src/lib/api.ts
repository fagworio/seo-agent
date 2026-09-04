/** Camada de API tipada (fronteira única). Nunca chame fetch em componentes. */

import type { components } from "../api/generated/schema";

export interface ApiErrorBody {
  error: { code: string; message: string; request_id: string };
}

export class ApiError extends Error {
  code: string;
  status: number;
  requestId: string;
  constructor(status: number, code: string, message: string, requestId: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  csrfToken?: string,
): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const res = await fetch(`/api/v1${path}`, {
    method,
    credentials: "include",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = (data as ApiErrorBody | null)?.error;
    throw new ApiError(
      res.status,
      err?.code ?? "UNKNOWN",
      err?.message ?? "Erro desconhecido",
      err?.request_id ?? "",
    );
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown, csrf?: string) => request<T>("POST", path, body, csrf),
  patch: <T>(path: string, body?: unknown, csrf?: string) => request<T>("PATCH", path, body, csrf),
  put: <T>(path: string, body?: unknown, csrf?: string) => request<T>("PUT", path, body, csrf),
  del: <T>(path: string, csrf?: string) => request<T>("DELETE", path, undefined, csrf),
};

export type Permission =
  | "dashboard.read"
  | "opportunity.read"
  | "opportunity.review"
  | "technical.read"
  | "technical.safe_fix"
  | "technical.approve_risky"
  | "editorial.read"
  | "editorial.review"
  | "editorial.publish_confirm"
  | "agent.read"
  | "agent.run"
  | "agent.cancel"
  | "experiment.read"
  | "integration.read"
  | "integration.manage"
  | "users.read"
  | "users.manage"
  | "settings.read"
  | "settings.manage"
  | "audit.read";

export interface User {
  id: number;
  email: string;
  name: string;
  roles: string[];
  permissions: Permission[];
  is_mfa_enabled: boolean;
}

export interface LoginResponse {
  ok: boolean;
  user?: User;
  requires_mfa?: boolean;
  mfa_user_id?: number;
  csrf_token?: string;
  message?: string;
}

export interface TodayResponse {
  today: {
    needs_attention: number;
    critical_findings: number;
    safe_fixes: number;
    organic_summary: { clicks: number; impressions: number; avg_position: number; pages: number } | null;
    recent_runs: AgentRun[];
    top_opportunities: Opportunity[];
    integration_warnings: IntegrationSource[];
    google_data: GoogleDataSummary;
    search_trend: SearchTrendPoint[];
    top_searches: SearchQuerySummary[];
    revalidations: Revalidation[];
    improvement_summary: ImprovementSummary;
  };
}

export interface SearchTrendPoint {
  window_start: string;
  window_end: string;
  clicks: number;
  impressions: number;
  ctr: number | null;
  position: number | null;
  pages: number;
  queries: number;
}

export interface SearchQuerySummary extends SearchTrendPoint {
  query: string;
  intent: string;
}

export interface GoogleDataSummary {
  data_status: string;
  connection_configured: boolean;
  gsc_window_start: string;
  gsc_window_end: string;
  gsc_rows: number;
  ga4_rows: number;
  ga4_window_end: string;
  ga4_collected_at: string;
  opportunities_total: number;
  opportunities_with_google: number;
  opportunities_without_google: number;
}

export interface Revalidation {
  id: number;
  keyword: string;
  opportunity_type: string;
  url: string;
  implemented_action: string;
  implemented_at: string;
  due_at: string;
  elapsed_days: number;
  state: "waiting_7d" | "waiting_google" | "ready" | "measured" | string;
  baseline_status: string;
  latest_google_window_end: string;
  verdict: string;
}

export interface ImprovementSummary {
  implemented: number;
  measured: number;
  improved: number;
  neutral: number;
  worsened: number;
  insufficient_data: number;
  waiting_7d: number;
  waiting_google: number;
  ready: number;
}

export interface Opportunity {
  id: string;
  source: string;
  type: string;
  status: string;
  url: string;
  title: string;
  score: number | null;
  recommendation: string;
  evidence: string;
  // campos de decisão humana — o backend deve expor via DTO (ver TODO abaixo);
  // opcionais p/ não quebrar a UI até o enriquecimento do OpportunityFeedService.
  action_class?: "observe" | "safe_fix" | "approval_required" | string;
  risk?: string;
  rollback_available?: boolean;
  decision_type?: "title_meta" | "internal_link" | "content" | "review" | string;
  related_recommendations?: string[];
  score_breakdown?: Record<string, unknown>;
  gsc_metrics?: Record<string, unknown>;
  ga4_metrics?: Record<string, unknown>;
  measurement_state?: string;
  projection?: Record<string, unknown>;
  top_queries?: Array<{ query: string; intent?: string; clicks: number; impressions: number; ctr: number | null; position: number | null }>;
  link_context?: {
    source_url?: string; target_url?: string; anchor?: string;
    source_title?: string; target_title?: string; suggested_anchor?: string;
    shared_terms?: string[]; source_excerpt?: string; insertion_instruction?: string;
    anchor_origin?: string; relevance?: "strong" | "moderate" | "weak" | string;
    confidence?: string; target_inbound_links?: number; source_outbound_links?: number;
    google_benefits?: string[]; site_benefits?: string[]; verification_steps?: string[];
  };
  data_freshness?: Record<string, string>;
}

export interface AgentRun {
  id: number;
  agent: string;
  status: string;
  trigger: string;
  intent: string | null;
  started_by: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  urls_analyzed: number;
  findings_count: number;
  opportunities_count: number;
  safe_fixes_count: number;
  executed_changes_count: number;
  comparison: Record<string, unknown> | null;
  summary: Record<string, unknown> | null;
  error: string | null;
  target_url?: string | null;
}

export interface IntegrationSource {
  source: string;
  data_status: string;
  configured: boolean;
  detail: string;
  last_window: string;
  rows: number;
  limitations: string;
  // ação de recuperação sugerida (determinística); vazia quando available
  recovery: string;
  // extras (coverage, documentos, provider, etc.) projetados pelo backend
  [key: string]: unknown;
}

export interface Agent {
  id: number;
  name: string;
  description: string;
  enabled: boolean;
}

export interface RunStep {
  stage: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface RunEvent {
  ts: string;
  event: string;
  level: string;
  message: string | null;
}

export interface RunDetail extends AgentRun {
  steps: RunStep[];
  events: RunEvent[];
}

export interface PageSummary {
  url: string;
  title: string;
  health: string;
  index_state: string;
  metrics: { position: number | null; impressions: number; clicks: number; ctr: number | null };
  primary_opportunity: string;
  captured_at: string;
  word_count: number;
}

export interface PageHistoryEntry {
  ts: string;
  source: string;
  linked_action: string;
  status_code: number | null;
  title: string;
  meta_robots: string;
  cwv: Record<string, unknown> | null;
  gsc: Record<string, unknown> | null;
  canonical: string;
  content_hash: string | null;
}

export interface Finding {
  rule_id: string;
  url: string;
  severity: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface TechnicalFinding {
  rule_id: string;
  rule: {
    rule_id: string;
    label: string;
    layer: string;
    diagnosis: string;
    severity: string;
    level: string;
    suggested_action: string;
  };
  severity: string;
  page: {
    path: string;
    finding_url: string;
    public_url: string;
    wordpress_url: string;
    wordpress_edit_url: string;
    headless: boolean;
  };
  title: string;
  google: {
    data_status: string;
    window_start: string;
    window_end: string;
    clicks: number | null;
    impressions: number | null;
    ctr: number | null;
    position: number | null;
    expected_ctr: number | null;
    expected_clicks: number | null;
    gap_clicks: number | null;
    top_queries: { query: string; clicks: number; impressions: number; ctr: number | null; position: number | null }[];
  };
  potential: {
    data_status: string;
    position: number | null;
    impressions: number | null;
    clicks: number | null;
    ctr: number | null;
    ctr_expected: number | null;
    expected_clicks: number | null;
    gap_clicks: number | null;
    conservative: number | null;
    realistic: number | null;
    optimistic: number | null;
  };
  created_at: string;
}

export interface Correction {
  fingerprint: string;
  rule_id: string;
  label: string;
  url: string;
  status: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  rollback: Record<string, unknown> | null;
  executed_at: string | null;
}

export interface ActivityEntry {
  ts: string;
  actor: string;
  type: string;
  event: string;
  summary: string;
  ref: string;
}

export interface Experiment {
  id: number;
  keyword: string;
  opportunity_type: string;
  url: string;
  implemented_action: string;
  implemented_at: string;
  baseline: Record<string, unknown>;
  current: Record<string, unknown>;
  delta: Record<string, unknown>;
  forecast: Record<string, unknown>;
  latest_result_window: string;
  revalidation: Partial<Revalidation>;
  verdict: string | null;
  windows: Record<string, boolean>;
  measurement_state: string;
  limitations?: string;
}

// Contrato OpenAPI gerado: o schema tipado oficial vem de
// `npm run generate:api` (src/api/generated/schema.d.ts). Os DTOs ricos acima
// são migrados incrementalmente para os schemas gerados conforme os modelos
// Pydantic do backend são ampliados; enquanto isso, `components` já expõe o
// contrato OpenAPI para uso direto.
export type { components, paths } from "../api/generated/schema";

// -- U1: Account & User management (do OpenAPI gerado) ----------------------
export type Account = components["schemas"]["AccountModel"];
export type UserSummary = components["schemas"]["UserSummaryModel"];
export type UserDetail = components["schemas"]["UserDetailModel"];
export type Role = components["schemas"]["RoleModel"];
export type SessionInfo = components["schemas"]["SessionModel"];
