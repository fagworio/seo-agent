/** Camada de API tipada (fronteira única). Nunca chame fetch em componentes. */

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
  };
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
}

export interface IntegrationSource {
  source: string;
  data_status: string;
  configured: boolean;
  detail: string;
  last_window: string;
  rows: number;
  limitations: string;
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
  keyword: string;
  opportunity_type: string;
  url: string;
  implemented_action: string;
  implemented_at: string;
  baseline: Record<string, unknown>;
  verdict: string | null;
  windows: Record<string, boolean>;
  measurement_state: string;
}
