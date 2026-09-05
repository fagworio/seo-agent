"""Aplicação FastAPI do control plane (/api/v1).

Routers tipados (Pydantic + operation IDs únicos) reusando AuthService,
ControlPlaneService e AgentRunService. Substitui o transporte catch-all
(ADR-0009) como camada de serviço; erros consistentes via ApiError.

Rodar: uvicorn hermes_seo_agent.api.app:app (ou create_app(storage_path, config)).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse

from .deps import Services, authenticated, get_services, register_error_handlers
from .http import session_cookie_name
from .schemas import (
    AccountModel,
    ActionsEnvelope,
    ActivityEnvelope,
    ActivityEntryModel,
    AgentRunModel,
    AgentsEnvelope,
    AuthSettingsModel,
    CampaignCreateRequest,
    CampaignDetailModel,
    CampaignPreviewModel,
    CampaignPreviewRequest,
    CampaignResolveRequest,
    CampaignResolveResponse,
    CampaignsEnvelope,
    CampaignScheduleRequest,
    ChangeEmailRequest,
    ChangePasswordRequest,
    CreateUserRequest,
    EditorialTransitionRequest,
    EditorialEnvelope,
    ExperimentsEnvelope,
    FindingsEnvelope,
    ForgotPasswordRequest,
    IntegrationsEnvelope,
    LoginRequest,
    LoginResponse,
    MeResponse,
    MfaConfirmRequest,
    MfaLoginRequest,
    MfaSetupResponse,
    MfaVerifyRequest,
    OkModel,
    PagesEnvelope,
    PermissionsEnvelope,
    ResetPasswordRequest,
    RolesEnvelope,
    RevalidationResultModel,
    RevalidationsEnvelope,
    RollbackPreviewModel,
    RolesRequest,
    RunCreateRequest,
    RunDetailModel,
    RunsEnvelope,
    SessionModel,
    TechnicalFindingModel,
    TodayEnvelope,
    UpdateProfileRequest,
    UpdateUserRequest,
    UserDetailModel,
    UserModel,
    UserSummaryModel,
    WorkItemDecisionModel,
    WorkItemsEnvelope,
)

from ..auth.service import AuthError
from ..auth.totp import generate_secret
from ..services.agent_runs import REFRESH_SOURCES
from ..services.improvement_campaigns import ImprovementCampaignService
from .errors import BadRequest, Forbidden, NotFound, PreconditionFailed, ReauthRequired


def _set_session_cookie(response: Response, services: Services, token: str) -> None:
    name = session_cookie_name(services.config)
    response.set_cookie(
        key=name,
        value=token,
        httponly=True,
        secure=getattr(services.config, "session_cookie_secure", True),
        samesite="strict",
        path="/",
        max_age=getattr(services.config, "session_idle_seconds", 8 * 3600),
    )


def _clear_session_cookie(response: Response, services: Services) -> None:
    response.set_cookie(
        key=session_cookie_name(services.config),
        value="",
        httponly=True,
        secure=getattr(services.config, "session_cookie_secure", True),
        samesite="strict",
        path="/",
        max_age=0,
    )


def auth_router() -> APIRouter:
    r = APIRouter(prefix="/auth", tags=["auth"])

    @r.post("/login", response_model=LoginResponse, operation_id="auth_login")
    def login(request: Request, body: LoginRequest, response: Response,
              services: Services = Depends(get_services)) -> dict[str, Any]:
        res = services.auth.login(
            body.email, body.password,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        if not res.ok:
            return {"ok": False, "message": "Email ou senha inválidos."}
        if res.requires_mfa:
            return {"ok": True, "requires_mfa": True, "mfa_user_id": res.mfa_user_id,
                    "user": res.user}
        _set_session_cookie(response, services, res.session_token or "")
        return {"ok": True, "user": res.user, "csrf_token": res.csrf_token}

    @r.post("/mfa/verify", response_model=LoginResponse, operation_id="auth_mfa_verify")
    def mfa_verify(request: Request, body: MfaVerifyRequest, response: Response,
                   services: Services = Depends(get_services)) -> dict[str, Any]:
        res = services.auth.verify_mfa_login(
            body.user_id, body.code,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        if not res.ok:
            return {"ok": False, "message": "Código inválido ou expirado."}
        _set_session_cookie(response, services, res.session_token or "")
        return {"ok": True, "user": res.user, "csrf_token": res.csrf_token}

    @r.post("/logout", response_model=OkModel, operation_id="auth_logout")
    def logout(request: Request, response: Response, services: Services = Depends(get_services),
               session=Depends(authenticated(csrf=True))) -> dict[str, Any]:
        name = session_cookie_name(services.config)
        token = request.cookies.get(name) or ""
        if token:
            services.auth.logout(token)   # revoga server-side (não só apaga o cookie)
        _clear_session_cookie(response, services)
        return {"ok": True}

    @r.get("/me", response_model=MeResponse, operation_id="auth_me")
    def me(services: Services = Depends(get_services),
           session=Depends(authenticated())) -> dict[str, Any]:
        csrf = services.auth.issue_csrf(session.session_id)
        return {"user": {"id": session.user_id, "email": session.email, "name": session.name,
                         "roles": session.roles, "permissions": sorted(session.permissions),
                         "is_mfa_enabled": session.is_mfa_enabled},
                "csrf_token": csrf}

    @r.get("/sessions", response_model=list[SessionModel], operation_id="auth_sessions")
    def sessions(services: Services = Depends(get_services),
                 session=Depends(authenticated())) -> list[dict[str, Any]]:
        return services.auth.list_sessions(session.user_id)

    @r.post("/sessions/revoke-others", response_model=OkModel, operation_id="auth_revoke_others")
    def revoke_others(services: Services = Depends(get_services),
                      session=Depends(authenticated(csrf=True))) -> dict[str, Any]:
        n = services.auth.revoke_other_sessions(session.user_id, session.session_id)
        return {"ok": True, "revoked": n}

    @r.delete("/sessions/{id}", response_model=OkModel, operation_id="auth_revoke_session")
    def revoke_session(id: int, services: Services = Depends(get_services),
                       session=Depends(authenticated(csrf=True))) -> dict[str, Any]:
        ok = services.auth.revoke_session(session.user_id, id)
        return {"ok": ok}

    @r.post("/forgot-password", response_model=OkModel, operation_id="auth_forgot")
    def forgot(body: ForgotPasswordRequest,
               services: Services = Depends(get_services)) -> dict[str, Any]:
        return services.auth.request_password_reset(body.email)

    @r.post("/reset-password", response_model=OkModel, operation_id="auth_reset")
    def reset(body: ResetPasswordRequest,
              services: Services = Depends(get_services)) -> dict[str, Any]:
        ok = services.auth.reset_password(body.token, body.new_password)
        return {"ok": ok, "message": "Senha redefinida." if ok else "Token inválido ou expirado."}

    return r


def read_routers() -> list[APIRouter]:
    out: list[APIRouter] = []

    dash = APIRouter(tags=["dashboard"])
    @dash.get("/dashboard/today", response_model=TodayEnvelope, operation_id="dashboard_today")
    def today(services: Services = Depends(get_services),
              session=Depends(authenticated("dashboard.read")),
              limit: int = Query(10, ge=1, le=200)) -> dict[str, Any]:
        return {"today": services.control.today(limit=limit)}
    out.append(dash)

    wi = APIRouter(prefix="/work-items", tags=["work-items"])
    @wi.get("", response_model=WorkItemsEnvelope, operation_id="work_items_list")
    def work_items(services: Services = Depends(get_services),
                   session=Depends(authenticated("opportunity.read")),
                   source: str | None = None, status: str | None = None,
                   limit: int = Query(200, ge=1, le=500)) -> dict[str, Any]:
        return {"work_items": services.control.work_items(source=source, status=status, limit=limit)}
    for action in ("approve", "reject", "snooze"):
        def _decision(action: str = action):
            def _d(item_id: str, body: WorkItemDecisionModel,
                   services: Services = Depends(get_services),
                   session=Depends(authenticated("opportunity.review", csrf=True))) -> OkModel:
                # action HTTP (approve/reject/snooze) -> status canônico (approved…)
                status = _WORK_ITEM_ACTION_STATUS[action]
                res = services.control.update_work_item_status(
                    item_id, status, actor=session.email, reason=body.reason)
                if res is None:
                    raise NotFound("Item não encontrado ou transição inválida.")
                return OkModel(ok=True)
            return _d
        wi.add_api_route(f"/{{item_id}}/{action}", _decision(action),
                         methods=["POST"], response_model=OkModel,
                         operation_id=f"work_items_{action}", tags=["work-items"])
    out.append(wi)

    ed = APIRouter(tags=["editorial"])
    @ed.get("/editorial", response_model=EditorialEnvelope, operation_id="editorial_list")
    def editorial(services: Services = Depends(get_services),
                  session=Depends(authenticated("editorial.read")),
                  status: str | None = None,
                  limit: int = Query(200, ge=1, le=500)) -> dict[str, Any]:
        # Projeção própria do backlog editorial (product board com
        # intent/evidência/escopo/publicação). NÃO usar work_items(): a Caixa de
        # trabalho exclui pautas editoriais (elas vivem neste menu).
        return {"items": services.control.editorial_items(status=status, limit=limit)}

    @ed.post("/editorial/{id}/{action}", response_model=OkModel, operation_id="editorial_transition")
    def editorial_transition(id: str, action: str, body: EditorialTransitionRequest,
                             services: Services = Depends(get_services),
                             session=Depends(authenticated("editorial.review", csrf=True))) -> dict[str, Any]:
        status = _EDITORIAL_ACTION_STATUS.get(action)
        if status is None:
            raise BadRequest(f"Ação editorial inválida: {action!r}")
        if action == "publish" and "editorial.publish_confirm" not in session.permissions:
            raise Forbidden("Publicação exige a permissão editorial.publish_confirm.")
        res = services.control.transition_editorial(
            id, status, actor=session.email, published_url=body.published_url or "")
        if res is None:
            raise PreconditionFailed("Transição editorial não permitida a partir do estado atual.")
        return {"ok": True}
    out.append(ed)

    pg = APIRouter(prefix="/pages", tags=["pages"])
    @pg.get("", response_model=PagesEnvelope, operation_id="pages_list")
    def pages(services: Services = Depends(get_services),
              session=Depends(authenticated("pages.read")),
              q: str = "", limit: int = Query(100, ge=1, le=500),
              offset: int = Query(0, ge=0),
              sort: str = "captured", health: str | None = None,
              index: str | None = None) -> dict[str, Any]:
        res = services.control.pages(query=q, limit=limit, offset=offset,
                                     sort=sort, health=health, index=index)
        return {"pages": res["items"], "total": res["total"]}
    @pg.get("/history", operation_id="pages_history")
    def page_history(url: str = Query(...), services: Services = Depends(get_services),
                     session=Depends(authenticated("pages.read"))) -> dict[str, Any]:
        from urllib.parse import unquote
        decoded = unquote(url)
        return {"url": decoded, "history": services.control.page_history(decoded)}
    out.append(pg)

    te = APIRouter(tags=["technical"])
    @te.get("/findings", response_model=FindingsEnvelope, operation_id="technical_findings")
    def findings(services: Services = Depends(get_services),
                 session=Depends(authenticated("technical.read")),
                 rule: str | None = None, limit: int = Query(200, ge=1, le=500),
                 sort: str = "potential") -> dict[str, Any]:
        return {"findings": services.control.technical_findings(rule=rule, limit=limit, sort=sort)}
    @te.get("/actions", response_model=ActionsEnvelope, operation_id="technical_actions")
    def actions(services: Services = Depends(get_services),
                session=Depends(authenticated("technical.read")),
                limit: int = Query(200, ge=1, le=500)) -> dict[str, Any]:
        return {"corrections": services.control.technical(limit=limit)["corrections"]}
    @te.post("/actions/{fingerprint}/execute", response_model=OkModel, operation_id="technical_execute")
    def execute(fingerprint: str, services: Services = Depends(get_services),
                session=Depends(authenticated("technical.safe_fix", csrf=True))) -> dict[str, Any]:
        preview = services.control.action_preview(fingerprint)
        if preview is None:
            raise NotFound("Correção não encontrada.")
        if not services.auth.verify_recent_strong_auth(session.session_id):
            from .errors import ReauthRequired
            raise ReauthRequired()
        services.storage.log_audit(session.email, "SAFE_FIX_APPROVED", fingerprint,
                                   {"url": preview["url"]},
                                   {"status": "approved", "dry_run": getattr(services.config, "dry_run", True)})
        return {"ok": True}
    @te.get("/actions/{fingerprint}/rollback", response_model=RollbackPreviewModel, operation_id="technical_rollback_preview")
    def rollback_preview(fingerprint: str, services: Services = Depends(get_services),
                         session=Depends(authenticated("technical.safe_fix"))) -> dict[str, Any]:
        plan = services.control.rollback_action(fingerprint)
        if plan is None:
            raise NotFound("Correção não encontrada.")
        return {"ok": True, "reversible": plan["reversible"], "strategy": "rollback_json"}
    @te.post("/actions/{fingerprint}/rollback", response_model=OkModel, operation_id="technical_rollback")
    def rollback(fingerprint: str, services: Services = Depends(get_services),
                 session=Depends(authenticated("technical.safe_fix", csrf=True))) -> dict[str, Any]:
        plan = services.control.rollback_action(fingerprint)
        if plan is None:
            raise NotFound("Correção não encontrada.")
        if not plan["reversible"]:
            from .errors import PreconditionFailed
            raise PreconditionFailed("Revert não disponível: correção não é reversível.")
        if not services.auth.verify_recent_strong_auth(session.session_id):
            from .errors import ReauthRequired
            raise ReauthRequired()
        if not services.control.mark_action_reverted(fingerprint, actor=session.email):
            from .errors import PreconditionFailed
            raise PreconditionFailed("Não é possível reverter: correção não está executada.")
        return {"ok": True}
    out.append(te)

    ag = APIRouter(prefix="/agents", tags=["agents"])
    @ag.get("", response_model=AgentsEnvelope, operation_id="agents_list")
    def agents(services: Services = Depends(get_services),
               session=Depends(authenticated("agent.read"))) -> dict[str, Any]:
        return {"agents": services.runs.list_agents()}
    out.append(ag)

    runs = APIRouter(prefix="/runs", tags=["agents"])
    @runs.get("", response_model=RunsEnvelope, operation_id="runs_list")
    def runs_list(services: Services = Depends(get_services),
                  session=Depends(authenticated("agent.read")),
                  agent: str | None = None, status: str | None = None,
                  limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
        return {"runs": services.runs.list_runs(agent=agent, status=status, limit=limit)}
    @runs.get("/{id}", response_model=RunDetailModel, operation_id="runs_detail")
    def run_detail(id: int, services: Services = Depends(get_services),
                   session=Depends(authenticated("agent.read"))) -> dict[str, Any]:
        run = services.runs.get_run(id)
        if run is None:
            raise NotFound("Execução não encontrada.")
        return run

    @runs.post("", response_model=AgentRunModel, operation_id="runs_create")
    def runs_create(body: RunCreateRequest, services: Services = Depends(get_services),
                    session=Depends(authenticated("agent.run", csrf=True))) -> dict[str, Any]:
        sources = _normalize_refresh_sources(body.intent, body.sources)
        if body.intent == "refresh_data":
            # R16: evitar execução duplicada — se já existe um refresh_data ativo,
            # devolve o run existente para a UI acompanhar o progresso.
            existing = services.runs.active_run(intent="refresh_data")
            if existing is not None:
                return services.runs.get_run(existing["id"]) or existing
            # Atualização de dados é uma solicitação ENFILEIRADA (R9-R12): o worker
            # (refresh-data/schedule) reivindica e executa; a UI faz polling.
            run_id = services.runs.queue_run("hermes-seo-agent", intent="refresh_data",
                                             mode=body.mode, started_by=session.email,
                                             sources=sources)
        else:
            run_id = services.runs.start_run("hermes-seo-agent", trigger="manual",
                                             intent=body.intent, mode=body.mode,
                                             started_by=session.email, target_url=body.target_url,
                                             sources=sources)
        return services.runs.get_run(run_id) or {}

    @runs.post("/{id}/cancel", response_model=AgentRunModel, operation_id="runs_cancel")
    def runs_cancel(id: int, services: Services = Depends(get_services),
                    session=Depends(authenticated("agent.cancel", csrf=True))) -> dict[str, Any]:
        return services.runs.cancel(id)
    out.append(runs)

    it = APIRouter(tags=["integrations"])
    @it.get("/integrations", response_model=IntegrationsEnvelope, operation_id="integrations_list")
    def integrations(services: Services = Depends(get_services),
                     session=Depends(authenticated("integration.read")),
                     live: bool = False, source: str | None = None) -> dict[str, Any]:
        # R15: visualizar fontes = integration.read; verificar conexões (live) = integration.manage.
        if live and "integration.manage" not in session.permissions:
            raise Forbidden("Verificar conexões exige a permissão integration.manage.")
        return {"integrations": services.control.integrations(live=live, source=source)}
    out.append(it)

    act = APIRouter(tags=["activity"])
    @act.get("/activity", response_model=ActivityEnvelope, operation_id="activity_list")
    def activity(services: Services = Depends(get_services),
                 session=Depends(authenticated("audit.read")),
                 limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
        return {"activity": services.control.activity(limit=limit)}
    out.append(act)

    ex = APIRouter(tags=["experiments"])
    @ex.get("/experiments", response_model=ExperimentsEnvelope, operation_id="experiments_list")
    def experiments(services: Services = Depends(get_services),
                    session=Depends(authenticated("experiment.read")),
                    limit: int = Query(100, ge=1, le=200)) -> dict[str, Any]:
        return {"experiments": services.control.experiments(limit=limit)}
    out.append(ex)

    rv = APIRouter(tags=["revalidations"])
    @rv.get("/revalidations", response_model=RevalidationsEnvelope, operation_id="revalidations_list")
    def revalidations_list(services: Services = Depends(get_services),
                           session=Depends(authenticated("opportunity.read")),
                           limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
        return {"revalidations": services.control.revalidations(limit=limit)}

    @rv.post("/revalidations/{id}/revalidate", response_model=RevalidationResultModel,
             operation_id="revalidations_revalidate")
    def revalidate(id: int, services: Services = Depends(get_services),
                   session=Depends(authenticated("agent.run", csrf=True))) -> dict[str, Any]:
        return services.control.revalidate_outcome(id)
    out.append(rv)

    return out


def _require_reauth(services: Services, session) -> None:
    if not services.auth.verify_recent_strong_auth(session.session_id):
        raise ReauthRequired()


def account_router() -> APIRouter:
    r = APIRouter(prefix="/account", tags=["account"])

    @r.get("", response_model=AccountModel, operation_id="account_get")
    def account_get(services: Services = Depends(get_services),
                    session=Depends(authenticated())) -> dict[str, Any]:
        return services.auth.get_account(session.user_id) or {}

    @r.patch("", response_model=OkModel, operation_id="account_update_profile")
    def account_update(body: UpdateProfileRequest, services: Services = Depends(get_services),
                       session=Depends(authenticated(csrf=True))) -> dict[str, Any]:
        services.auth.update_profile(session.user_id, body.name)
        return {"ok": True}

    @r.post("/change-email", response_model=OkModel, operation_id="account_change_email")
    def account_change_email(body: ChangeEmailRequest, services: Services = Depends(get_services),
                             session=Depends(authenticated(csrf=True))) -> dict[str, Any]:
        try:
            services.auth.change_email(session.user_id, body.new_email, body.password)
        except AuthError as exc:
            raise BadRequest(str(exc))
        return {"ok": True}

    @r.post("/change-password", response_model=OkModel, operation_id="account_change_password")
    def account_change_password(body: ChangePasswordRequest,
                                services: Services = Depends(get_services),
                                session=Depends(authenticated(csrf=True))) -> dict[str, Any]:
        ok = services.auth.change_password_auth(
            session.user_id, body.current_password, body.new_password,
            mfa_enabled=session.is_mfa_enabled)
        return {"ok": ok, "message": "" if ok else "Senha atual incorreta."}

    @r.post("/mfa/setup", response_model=MfaSetupResponse, operation_id="account_mfa_setup")
    def account_mfa_setup(services: Services = Depends(get_services),
                          session=Depends(authenticated())) -> dict[str, Any]:
        try:
            secret = services.auth.mfa_setup(session.user_id)
        except AuthError as exc:
            raise BadRequest(str(exc))
        return {"secret": secret, "issuer": getattr(services.config, "mfa_issuer", "SEO Agent")}

    @r.post("/mfa/confirm", response_model=OkModel, operation_id="account_mfa_confirm")
    def account_mfa_confirm(body: MfaConfirmRequest, services: Services = Depends(get_services),
                            session=Depends(authenticated(csrf=True))) -> dict[str, Any]:
        return {"ok": services.auth.mfa_confirm(session.user_id, body.code)}

    @r.post("/mfa/disable", response_model=OkModel, operation_id="account_mfa_disable")
    def account_mfa_disable(services: Services = Depends(get_services),
                            session=Depends(authenticated(csrf=True))) -> dict[str, Any]:
        _require_reauth(services, session)
        services.auth.mfa_disable(session.user_id)
        return {"ok": True}

    return r


def users_router() -> APIRouter:
    r = APIRouter(prefix="/users", tags=["users"])

    @r.get("", response_model=list[UserSummaryModel], operation_id="users_list")
    def users_list(services: Services = Depends(get_services),
                   session=Depends(authenticated("users.read"))) -> list[dict[str, Any]]:
        out = []
        for u in services.auth.store.list_users():
            u["roles"] = services.auth.store.get_user_roles(u["id"])
            out.append(u)
        return out

    @r.post("", response_model=UserDetailModel, operation_id="users_create")
    def users_create(body: CreateUserRequest, services: Services = Depends(get_services),
                     session=Depends(authenticated("users.manage", csrf=True))) -> dict[str, Any]:
        _require_reauth(services, session)
        try:
            uid = services.auth.create_user(
                body.email, body.name, body.password or "", body.roles,
                mfa_secret=generate_secret() if body.require_mfa else None)
        except AuthError as exc:
            raise BadRequest(str(exc))
        services.auth.store.set_password_must_change(
            uid, 1 if body.require_password_change else 0)
        u = services.auth.store.get_user(uid)
        u["roles"] = services.auth.store.get_user_roles(uid)
        u["permissions"] = sorted(services.auth.permissions_for(uid))
        return u

    @r.get("/{id}", response_model=UserDetailModel, operation_id="users_detail")
    def users_detail(id: int, services: Services = Depends(get_services),
                     session=Depends(authenticated("users.read"))) -> dict[str, Any]:
        u = services.auth.store.get_user(id)
        if not u:
            raise NotFound("Usuário não encontrado.")
        u["roles"] = services.auth.store.get_user_roles(id)
        u["permissions"] = sorted(services.auth.permissions_for(id))
        return u

    @r.patch("/{id}", response_model=OkModel, operation_id="users_update")
    def users_update(id: int, body: UpdateUserRequest, services: Services = Depends(get_services),
                     session=Depends(authenticated("users.manage", csrf=True))) -> dict[str, Any]:
        _require_reauth(services, session)
        if body.name is not None:
            services.auth.update_profile(id, body.name)
        if body.email is not None:
            services.auth.store.conn.execute(
                "UPDATE users SET email = ?, updated_at = ? WHERE id = ?",
                (body.email.lower().strip(), services.auth._now(), id))
            services.auth.store.conn.commit()
            services.auth._audit(now=services.auth._now(), user_id=id, event="PROFILE_EMAIL_CHANGED")
        return {"ok": True}

    @r.post("/{id}/enable", response_model=OkModel, operation_id="users_enable")
    def users_enable(id: int, services: Services = Depends(get_services),
                     session=Depends(authenticated("users.manage", csrf=True))) -> dict[str, Any]:
        services.auth.store.enable_user(id)
        services.auth._audit(now=services.auth._now(), user_id=id, event="USER_ENABLED")
        return {"ok": True}

    @r.post("/{id}/disable", response_model=OkModel, operation_id="users_disable")
    def users_disable(id: int, services: Services = Depends(get_services),
                      session=Depends(authenticated("users.manage", csrf=True))) -> dict[str, Any]:
        _require_reauth(services, session)
        if id == session.user_id:
            raise BadRequest("Não é possível desativar a própria conta.")
        if services.auth.is_last_admin(id) and "admin" in services.auth.store.get_user_roles(id):
            raise BadRequest("Não é possível desativar o último administrador.")
        services.auth.store.disable_user(id)
        services.auth.store.revoke_user_sessions(id, now=services.auth._now())
        services.auth._audit(now=services.auth._now(), user_id=id, event="USER_DISABLED")
        return {"ok": True}

    @r.put("/{id}/roles", response_model=UserDetailModel, operation_id="users_roles")
    def users_roles(id: int, body: RolesRequest, services: Services = Depends(get_services),
                    session=Depends(authenticated("users.manage", csrf=True))) -> dict[str, Any]:
        _require_reauth(services, session)
        if ("admin" not in body.roles and "admin" in services.auth.store.get_user_roles(id)
                and services.auth.is_last_admin(id)):
            raise BadRequest("Não é possível remover a role do último administrador.")
        services.auth.set_user_roles(id, body.roles)
        u = services.auth.store.get_user(id)
        u["roles"] = services.auth.store.get_user_roles(id)
        u["permissions"] = sorted(services.auth.permissions_for(id))
        return u

    @r.post("/{id}/force-password-reset", response_model=OkModel, operation_id="users_force_password_reset")
    def users_force_password_reset(id: int, services: Services = Depends(get_services),
                                   session=Depends(authenticated("users.manage", csrf=True))) -> dict[str, Any]:
        _require_reauth(services, session)
        services.auth.force_password_reset(id)
        return {"ok": True}

    @r.post("/{id}/reset-mfa", response_model=OkModel, operation_id="users_reset_mfa")
    def users_reset_mfa(id: int, services: Services = Depends(get_services),
                        session=Depends(authenticated("users.manage", csrf=True))) -> dict[str, Any]:
        _require_reauth(services, session)
        services.auth.mfa_disable(id)
        return {"ok": True}

    @r.get("/{id}/sessions", response_model=list[SessionModel], operation_id="users_sessions")
    def users_sessions(id: int, services: Services = Depends(get_services),
                       session=Depends(authenticated("users.read"))) -> list[dict[str, Any]]:
        return services.auth.list_sessions(id)

    @r.delete("/{id}/sessions", response_model=OkModel, operation_id="users_sessions_revoke")
    def users_sessions_revoke(id: int, services: Services = Depends(get_services),
                              session=Depends(authenticated("users.manage", csrf=True))) -> dict[str, Any]:
        services.auth.store.revoke_user_sessions(id, now=services.auth._now())
        return {"ok": True}

    @r.get("/{id}/activity", response_model=list[ActivityEntryModel], operation_id="users_activity")
    def users_activity(id: int, services: Services = Depends(get_services),
                       session=Depends(authenticated("users.read"))) -> list[dict[str, Any]]:
        return [e for e in services.auth.store.list_events(limit=200) if e.get("user_id") == id]

    return r


def roles_permissions_router() -> APIRouter:
    r = APIRouter(tags=["users"])

    @r.get("/roles", response_model=RolesEnvelope, operation_id="roles_list")
    def roles_list(session=Depends(authenticated("users.read"))) -> dict[str, Any]:
        from ..auth.permissions import ROLE_DESCRIPTIONS, ROLE_PERMISSIONS
        return {"roles": [{"name": n, "description": ROLE_DESCRIPTIONS.get(n, ""),
                           "permissions": sorted(p)}
                          for n, p in sorted(ROLE_PERMISSIONS.items())]}

    @r.get("/permissions", response_model=PermissionsEnvelope, operation_id="permissions_list")
    def permissions_list(session=Depends(authenticated("users.read"))) -> dict[str, Any]:
        from ..auth.permissions import all_permissions
        return {"permissions": [{"name": p} for p in sorted(all_permissions())]}

    return r


def settings_router() -> APIRouter:
    r = APIRouter(tags=["settings"])

    @r.get("/settings/auth", response_model=AuthSettingsModel, operation_id="settings_auth")
    def settings_auth(services: Services = Depends(get_services),
                      session=Depends(authenticated("settings.read"))) -> dict[str, Any]:
        # Política global de autenticação (chave MFA no login, padrão OFF).
        return {"mfa_login_required": services.auth.mfa_login_required()}

    @r.put("/settings/auth/mfa-login", response_model=AuthSettingsModel,
           operation_id="settings_auth_mfa_login")
    def settings_auth_mfa_login(body: MfaLoginRequest, services: Services = Depends(get_services),
                                session=Depends(authenticated("settings.manage", csrf=True))) -> dict[str, Any]:
        # Alteração sensível: reautenticação recente obrigatória.
        _require_reauth(services, session)
        services.auth.set_mfa_login_required(body.enabled, actor=session.email)
        return {"mfa_login_required": body.enabled}

    return r


_EDITORIAL_ACTION_STATUS = {
    "approve": "approved", "reject": "rejected", "snooze": "snoozed",
    "publish": "published", "measure": "measured",
}

# work-items HTTP action -> status canônico (update_work_item_status espera o status)
_WORK_ITEM_ACTION_STATUS = {
    "approve": "approved", "reject": "rejected", "snooze": "snoozed",
}


def campaigns_router() -> APIRouter:
    r = APIRouter(prefix="/campaigns", tags=["campaigns"])

    @r.get("", response_model=CampaignsEnvelope, operation_id="campaigns_list")
    def campaigns_list(services: Services = Depends(get_services),
                       session=Depends(authenticated("opportunity.read")),
                       status: str | None = None,
                       limit: int = Query(100, ge=1, le=200)) -> dict[str, Any]:
        svc = ImprovementCampaignService(services.storage)
        return {"campaigns": svc.list_campaigns(status=status, limit=limit)}

    @r.post("", response_model=CampaignDetailModel, operation_id="campaigns_create")
    def campaigns_create(body: CampaignCreateRequest, services: Services = Depends(get_services),
                         session=Depends(authenticated("opportunity.review", csrf=True))) -> dict[str, Any]:
        svc = ImprovementCampaignService(services.storage)
        res = svc.create(body.name, body.action_type, body.fingerprints,
                         created_by=session.email, max_actions_per_run=body.max_actions_per_run,
                         execution_mode=body.execution_mode, schedule_policy=body.schedule_policy,
                         work_item_ids=body.work_item_ids)
        if res is None:
            raise PreconditionFailed("Seleção inválida: campanha exige ações homogêneas com fix suportado.")
        return res

    @r.post("/preview", response_model=CampaignPreviewModel, operation_id="campaigns_preview")
    def campaigns_preview(body: CampaignPreviewRequest, services: Services = Depends(get_services),
                          session=Depends(authenticated("opportunity.review", csrf=True))) -> dict[str, Any]:
        svc = ImprovementCampaignService(services.storage)
        return svc.preview(body.fingerprints,
                           max_actions_per_run=getattr(services.config, "max_safe_fix_per_cycle", 10))

    @r.post("/resolve", response_model=CampaignResolveResponse, operation_id="campaigns_resolve")
    def campaigns_resolve(body: CampaignResolveRequest, services: Services = Depends(get_services),
                          session=Depends(authenticated("opportunity.review", csrf=True))) -> dict[str, Any]:
        svc = ImprovementCampaignService(services.storage)
        if body.items:
            res = svc.resolve_work_items([it.model_dump() for it in body.items])
        else:
            # compat: resolve por URL (legado)
            res = svc.resolve_work_items([{"work_item_id": "", "url": u} for u in body.urls])
        res.setdefault("fingerprints", [it["fingerprint"] for it in res["items"]
                                        if it.get("fingerprint")])
        return res

    @r.get("/{id}", response_model=CampaignDetailModel, operation_id="campaigns_detail")
    def campaigns_detail(id: int, services: Services = Depends(get_services),
                         session=Depends(authenticated("opportunity.read"))) -> dict[str, Any]:
        svc = ImprovementCampaignService(services.storage)
        res = svc.get(id)
        if res is None:
            raise NotFound("Campanha não encontrada.")
        return res

    @r.post("/{id}/approve", response_model=CampaignDetailModel, operation_id="campaigns_approve")
    def campaigns_approve(id: int, services: Services = Depends(get_services),
                          session=Depends(authenticated("technical.safe_fix", csrf=True))) -> dict[str, Any]:
        svc = ImprovementCampaignService(services.storage)
        if not svc.approve(id, approved_by=session.email):
            raise PreconditionFailed("Não foi possível aprovar a campanha.")
        return svc.get(id) or {}

    @r.post("/{id}/run", response_model=CampaignDetailModel, operation_id="campaigns_run")
    def campaigns_run(id: int, services: Services = Depends(get_services),
                      session=Depends(authenticated("agent.run", csrf=True))) -> dict[str, Any]:
        svc = ImprovementCampaignService(services.storage, config=services.config)
        res = svc.run(id, actor=session.email)
        if res is None:
            raise PreconditionFailed("Campanha não pode ser executada agora.")
        return res

    @r.post("/{id}/pause", response_model=CampaignDetailModel, operation_id="campaigns_pause")
    def campaigns_pause(id: int, services: Services = Depends(get_services),
                        session=Depends(authenticated("agent.run", csrf=True))) -> dict[str, Any]:
        svc = ImprovementCampaignService(services.storage)
        svc.pause(id, actor=session.email)
        return svc.get(id) or {}

    @r.post("/{id}/resume", response_model=CampaignDetailModel, operation_id="campaigns_resume")
    def campaigns_resume(id: int, services: Services = Depends(get_services),
                         session=Depends(authenticated("agent.run", csrf=True))) -> dict[str, Any]:
        svc = ImprovementCampaignService(services.storage)
        svc.resume(id, actor=session.email)
        return svc.get(id) or {}

    @r.post("/{id}/cancel", response_model=CampaignDetailModel, operation_id="campaigns_cancel")
    def campaigns_cancel(id: int, services: Services = Depends(get_services),
                         session=Depends(authenticated("agent.run", csrf=True))) -> dict[str, Any]:
        svc = ImprovementCampaignService(services.storage)
        svc.cancel(id, actor=session.email)
        return svc.get(id) or {}

    @r.post("/{id}/schedule", response_model=CampaignDetailModel, operation_id="campaigns_schedule")
    def campaigns_schedule(id: int, body: CampaignScheduleRequest,
                           services: Services = Depends(get_services),
                           session=Depends(authenticated("agent.run", csrf=True))) -> dict[str, Any]:
        svc = ImprovementCampaignService(services.storage)
        svc.schedule(id, policy=body.policy, next_run_at=body.next_run_at)
        return svc.get(id) or {}

    return r


def _normalize_refresh_sources(intent: str | None, sources: list[str] | None) -> list[str] | None:
    """Escopo de fontes para um run refresh_data.

    - Outros intents ignoram `sources` (retorna None).
    - refresh_data sem sources => todas as fontes; com sources => valida cada uma.
    """
    if intent != "refresh_data":
        return None
    if not sources:
        return list(REFRESH_SOURCES)
    for s in sources:
        if s not in REFRESH_SOURCES:
            raise BadRequest(f"fonte inválida para refresh: {s!r} (válidas: {', '.join(REFRESH_SOURCES)})")
    return list(dict.fromkeys(sources))


def _is_docs_path(path: str) -> bool:
    """Rotas de documentação HTML (Swagger UI / ReDoc) da API.

    A CSP estrita (`script-src 'self'`) bloquearia o JS/CSS que o FastAPI carrega
    de cdn.jsdelivr.net e o script inline de bootstrap; essas páginas recebem uma
    CSP relaxada só para si. O restante da API (JSON) permanece estrito.
    """
    return (path in ("/api/docs", "/api/docs/oauth2-redirect", "/redoc")
            or path.startswith(("/api/docs/", "/redoc/")))


def create_app(*, storage_path: str, config: Any) -> FastAPI:
    app = FastAPI(
        title="SEO Agent Control Center",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/v1/openapi.json",
    )
    app.state.storage_path = storage_path
    app.state.config = config
    register_error_handlers(app)

    @app.middleware("http")
    async def _request_id(request: Request, call_next):
        rid = "req_" + uuid.uuid4().hex[:12]
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        """Headers de segurança/observabilidade (CSP final no proxy TLS; aqui o
        mínimo defensivo). Nada de credenciais em resposta."""
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # JSON da API: CSP estrita (scripts 'self'). A documentação (Swagger/ReDoc)
        # é a única página HTML da API e carrega JS/CSS de cdn.jsdelivr.net + um
        # script inline de bootstrap — ali a CSP é relaxada só para essa rota,
        # mantendo frame-ancestors/base-uri defensivos. O dashboard (Next.js) é
        # servido separadamente e não herda estes headers.
        csp = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        if _is_docs_path(request.url.path):
            csp = (
                "default-src 'self'; img-src 'self' data:; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "frame-ancestors 'none'; base-uri 'self'"
            )
        response.headers["Content-Security-Policy"] = csp
        return response

    for r in read_routers():
        app.include_router(r, prefix="/api/v1")
    app.include_router(auth_router(), prefix="/api/v1")
    app.include_router(account_router(), prefix="/api/v1")
    app.include_router(users_router(), prefix="/api/v1")
    app.include_router(roles_permissions_router(), prefix="/api/v1")
    app.include_router(settings_router(), prefix="/api/v1")
    app.include_router(campaigns_router(), prefix="/api/v1")

    @app.get("/api/v1/health", tags=["health"], operation_id="health", response_model=None)
    def health():
        """Liveness público (healthcheck do Docker); espelha a stdlib."""
        from ..storage.db import Storage
        try:
            with Storage(app.state.storage_path) as storage:
                storage.conn.execute("SELECT 1").fetchone()
            return {"status": "ok"}
        except Exception:
            return JSONResponse(status_code=503, content={"status": "degraded"})

    return app


def app() -> FastAPI:
    from ..config import load_config
    return create_app(storage_path=load_config().sqlite_path, config=load_config())
