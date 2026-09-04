"""Schemas Pydantic do control plane (/api/v1). Contractos tipados p/ OpenAPI + TS."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# -- auth --------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class MfaVerifyRequest(BaseModel):
    user_id: int
    code: str = Field(min_length=6, max_length=6)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=1)


class UserModel(BaseModel):
    id: int
    email: str
    name: str = ""
    roles: list[str] = []
    permissions: list[str] = []
    is_mfa_enabled: bool = False


class LoginResponse(BaseModel):
    ok: bool
    requires_mfa: bool = False
    mfa_user_id: int | None = None
    user: UserModel | None = None
    csrf_token: str | None = None
    message: str | None = None


class MeResponse(BaseModel):
    user: UserModel
    csrf_token: str


class OkModel(BaseModel):
    ok: bool = True
    message: str | None = None
    revoked: int | None = None


class RollbackPreviewModel(BaseModel):
    ok: bool = True
    reversible: bool
    strategy: str


class AuthSettingsModel(BaseModel):
    mfa_login_required: bool = False


class MfaLoginRequest(BaseModel):
    enabled: bool


class SessionModel(BaseModel):
    id: int
    created_at: str
    last_seen_at: str
    expires_at: str
    ip_hash: str | None = None
    user_agent: str | None = None
    revoked_at: str | None = None


# -- read models (produto) ---------------------------------------------------
class OpportunityModel(BaseModel):
    id: str
    source: str
    type: str = ""
    status: str = ""
    url: str = ""
    title: str = ""
    score: float | None = None
    evidence: str = ""
    recommendation: str = ""
    action_class: str = "approval_required"
    risk: str = "review_required"
    rollback_available: bool = False
    decision_type: str = "review"
    related_recommendations: list[str] = []
    score_breakdown: dict[str, Any] = {}
    gsc_metrics: dict[str, Any] = {}
    ga4_metrics: dict[str, Any] = {}
    measurement_state: str = "not_measurable"
    projection: dict[str, Any] = {}
    top_queries: list[dict[str, Any]] = []
    link_context: dict[str, Any] = {}
    data_freshness: dict[str, str] = {}


class OrganicSummaryModel(BaseModel):
    window_start: str = ""
    clicks: int = 0
    impressions: int = 0
    avg_position: float | None = None
    pages: int = 0


class SearchTrendPointModel(BaseModel):
    window_start: str = ""
    window_end: str = ""
    clicks: float = 0
    impressions: float = 0
    ctr: float | None = None
    position: float | None = None
    pages: int = 0
    queries: int = 0


class SearchQueryModel(BaseModel):
    query: str
    intent: str = ""
    clicks: float = 0
    impressions: float = 0
    ctr: float | None = None
    position: float | None = None
    pages: int = 0
    window_start: str = ""
    window_end: str = ""


class GoogleDataSummaryModel(BaseModel):
    data_status: str = "missing"
    connection_configured: bool = False
    gsc_window_start: str = ""
    gsc_window_end: str = ""
    gsc_rows: int = 0
    ga4_rows: int = 0
    ga4_window_end: str = ""
    ga4_collected_at: str = ""
    opportunities_total: int = 0
    opportunities_with_google: int = 0
    opportunities_without_google: int = 0


class RevalidationModel(BaseModel):
    id: int
    keyword: str = ""
    opportunity_type: str = ""
    url: str = ""
    implemented_action: str = ""
    implemented_at: str = ""
    due_at: str = ""
    elapsed_days: int = 0
    state: str = "waiting_7d"
    baseline_status: str = "missing"
    latest_google_window_end: str = ""
    verdict: str = ""


class ImprovementSummaryModel(BaseModel):
    implemented: int = 0
    measured: int = 0
    improved: int = 0
    neutral: int = 0
    worsened: int = 0
    insufficient_data: int = 0
    waiting_7d: int = 0
    waiting_google: int = 0
    ready: int = 0


class AgentRunModel(BaseModel):
    id: int
    agent: str
    status: str
    trigger: str = ""
    intent: str | None = None
    started_by: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    urls_analyzed: int = 0
    findings_count: int = 0
    opportunities_count: int = 0
    safe_fixes_count: int = 0
    executed_changes_count: int = 0
    comparison: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    error: str | None = None
    target_url: str | None = None
    sources: list[str] | None = None


class RunStepModel(BaseModel):
    stage: str
    status: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None


class RunEventModel(BaseModel):
    ts: str = ""
    event: str = ""
    level: str = "info"
    message: str | None = None


class RunDetailModel(AgentRunModel):
    steps: list[RunStepModel] = []
    events: list[RunEventModel] = []


class IntegrationSourceModel(BaseModel):
    source: str
    data_status: str
    configured: bool = False
    detail: str = ""
    last_window: str = ""
    rows: int = 0
    limitations: str = ""
    recovery: str = ""
    # extras (coverage, documentos, provider, staleness…) projetados pelo
    # backend: qualquer campo adicional é aceito e repassado ao frontend.
    model_config = ConfigDict(extra="allow")


class TodayModel(BaseModel):
    needs_attention: int = 0
    critical_findings: int = 0
    safe_fixes: int = 0
    organic_summary: OrganicSummaryModel | None = None
    recent_runs: list[AgentRunModel] = []
    top_opportunities: list[OpportunityModel] = []
    integration_warnings: list[IntegrationSourceModel] = []
    google_data: GoogleDataSummaryModel = GoogleDataSummaryModel()
    search_trend: list[SearchTrendPointModel] = []
    top_searches: list[SearchQueryModel] = []
    revalidations: list[RevalidationModel] = []
    improvement_summary: ImprovementSummaryModel = ImprovementSummaryModel()


class PageSummaryModel(BaseModel):
    url: str
    title: str = ""
    health: str = ""
    index_state: str = ""
    word_count: int = 0
    captured_at: str = ""
    metrics: dict[str, Any] = {}
    primary_opportunity: str = ""


class ActivityEntryModel(BaseModel):
    ts: str = ""
    actor: str = ""
    type: str = ""
    event: str = ""
    summary: str = ""
    ref: str = ""


class ExperimentModel(BaseModel):
    id: int = 0
    keyword: str = ""
    opportunity_type: str = ""
    url: str = ""
    implemented_action: str = ""
    implemented_at: str = ""
    baseline: dict[str, Any] = {}
    current: dict[str, Any] = {}
    delta: dict[str, Any] = {}
    forecast: dict[str, Any] = {}
    latest_result_window: str = ""
    revalidation: dict[str, Any] = {}
    verdict: str | None = None
    windows: dict[str, bool] = {}
    measurement_state: str = "waiting_data"
    limitations: str = ""


class RuleModel(BaseModel):
    rule_id: str
    label: str
    layer: str = ""
    diagnosis: str = ""
    severity: str = "medium"
    level: str = "observe"
    suggested_action: str = ""


class GoogleModel(BaseModel):
    data_status: str = "missing"
    window_start: str = ""
    window_end: str = ""
    clicks: int | None = None
    impressions: int | None = None
    ctr: float | None = None
    position: float | None = None
    expected_ctr: float | None = None
    expected_clicks: float | None = None
    gap_clicks: float | None = None
    top_queries: list[dict[str, Any]] = []


class PotentialModel(BaseModel):
    data_status: str = "missing"
    conservative: float | None = None
    realistic: float | None = None
    optimistic: float | None = None
    ctr_expected: float | None = None
    expected_clicks: float | None = None
    gap_clicks: float | None = None


class PageIdentityModel(BaseModel):
    path: str = ""
    finding_url: str = ""
    public_url: str = ""
    wordpress_url: str = ""
    wordpress_edit_url: str = ""
    headless: bool = False


class TechnicalFindingModel(BaseModel):
    rule_id: str
    rule: RuleModel
    severity: str = "medium"
    page: PageIdentityModel
    title: str = ""
    google: GoogleModel
    potential: PotentialModel
    created_at: str = ""


class CorrectionModel(BaseModel):
    fingerprint: str
    rule_id: str = ""
    label: str = ""
    url: str = ""
    status: str = ""
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    rollback: dict[str, Any] | None = None
    executed_at: str | None = None


class WorkItemDecisionModel(BaseModel):
    reason: str = Field(default="")


class EditorialTransitionRequest(BaseModel):
    published_url: str = Field(default="")


# -- envelopes (mesma forma que o frontend já consome) ----------------------
class AgentModel(BaseModel):
    id: int
    name: str
    description: str = ""
    enabled: bool = True


class TodayEnvelope(BaseModel):
    today: TodayModel


class WorkItemsEnvelope(BaseModel):
    work_items: list[OpportunityModel]


class PagesEnvelope(BaseModel):
    pages: list[PageSummaryModel]
    total: int = 0


class FindingsEnvelope(BaseModel):
    findings: list[TechnicalFindingModel]


class ActionsEnvelope(BaseModel):
    corrections: list[CorrectionModel]


class IntegrationsEnvelope(BaseModel):
    integrations: list[IntegrationSourceModel]


class ActivityEnvelope(BaseModel):
    activity: list[ActivityEntryModel]


class ExperimentsEnvelope(BaseModel):
    experiments: list[ExperimentModel]


class RunsEnvelope(BaseModel):
    runs: list[AgentRunModel]


class EditorialEnvelope(BaseModel):
    editorial: list[OpportunityModel]


class RunCreateRequest(BaseModel):
    intent: str | None = None
    mode: str | None = None
    target_url: str | None = None
    sources: list[str] | None = None


# -- U1: Account (self-service) ----------------------------------------------
class AccountModel(BaseModel):
    id: int
    name: str
    email: str
    is_mfa_enabled: bool
    must_change_password: bool
    roles: list[str] = []
    permissions: list[str] = []
    created_at: str = ""
    last_login_at: str | None = None


class UpdateProfileRequest(BaseModel):
    name: str = Field(min_length=1)


class ChangeEmailRequest(BaseModel):
    new_email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=1)


class MfaConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class MfaSetupResponse(BaseModel):
    secret: str
    issuer: str = "SEO Agent"


# -- U1: Administração (users) ----------------------------------------------
class UserSummaryModel(BaseModel):
    id: int
    email: str
    name: str = ""
    is_active: bool = True
    is_mfa_enabled: bool = False
    roles: list[str] = []
    last_login_at: str | None = None
    created_at: str = ""


class UserDetailModel(UserSummaryModel):
    permissions: list[str] = []
    must_change_password: bool = False


class CreateUserRequest(BaseModel):
    email: str
    name: str = ""
    password: str | None = None
    roles: list[str] = []
    require_password_change: bool = True
    require_mfa: bool = False


class UpdateUserRequest(BaseModel):
    name: str | None = None
    email: str | None = None


class RolesRequest(BaseModel):
    roles: list[str]


class RoleModel(BaseModel):
    name: str
    description: str = ""
    permissions: list[str] = []


class PermissionModel(BaseModel):
    name: str


class RolesEnvelope(BaseModel):
    roles: list[RoleModel]


class PermissionsEnvelope(BaseModel):
    permissions: list[PermissionModel]


class AgentsEnvelope(BaseModel):
    agents: list[AgentModel]


def model_validate_factory(m):  # helper p/ construir a partir de dicts
    pass
