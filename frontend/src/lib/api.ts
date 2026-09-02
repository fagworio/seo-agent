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
}

export interface IntegrationSource {
  source: string;
  data_status: string;
  detail: string;
  rows: number;
  limitations: string;
}
