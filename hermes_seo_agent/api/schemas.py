"""Schemas Pydantic do control plane (/api/v1). Contractos tipados p/ OpenAPI + TS."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


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


class OrganicSummaryModel(BaseModel):
    window_start: str = ""
    clicks: int = 0
    impressions: int = 0
    avg_position: float | None = None
    pages: int = 0


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


class TodayModel(BaseModel):
    needs_attention: int = 0
    critical_findings: int = 0
    safe_fixes: int = 0
    organic_summary: OrganicSummaryModel | None = None
    recent_runs: list[AgentRunModel] = []
    top_opportunities: list[OpportunityModel] = []
    integration_warnings: list[IntegrationSourceModel] = []


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
    keyword: str = ""
    opportunity_type: str = ""
    url: str = ""
    implemented_action: str = ""
    implemented_at: str = ""
    verdict: str | None = None
    measurement_state: str = "waiting_data"


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
    expected_clicks: int | None = None
    gap_clicks: int | None = None
    top_queries: list[dict[str, Any]] = []


class PotentialModel(BaseModel):
    data_status: str = "missing"
    conservative: int | None = None
    realistic: int | None = None
    optimistic: int | None = None
    ctr_expected: float | None = None
    expected_clicks: int | None = None
    gap_clicks: int | None = None


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
    url: str = ""
    status: str = ""
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    rollback: dict[str, Any] | None = None
    executed_at: str | None = None


class WorkItemDecisionModel(BaseModel):
    reason: str = Field(default="")


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


class AgentsEnvelope(BaseModel):
    agents: list[AgentModel]


def model_validate_factory(m):  # helper p/ construir a partir de dicts
    pass
