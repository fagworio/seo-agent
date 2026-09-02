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
from .errors import NotFound
from .http import session_cookie_name
from .schemas import (
    ActionsEnvelope,
    ActivityEnvelope,
    AgentRunModel,
    AgentsEnvelope,
    EditorialEnvelope,
    ExperimentsEnvelope,
    FindingsEnvelope,
    ForgotPasswordRequest,
    IntegrationsEnvelope,
    LoginRequest,
    LoginResponse,
    MeResponse,
    MfaVerifyRequest,
    OkModel,
    PagesEnvelope,
    ResetPasswordRequest,
    RunCreateRequest,
    RunDetailModel,
    RunsEnvelope,
    SessionModel,
    TodayEnvelope,
    UserModel,
    WorkItemDecisionModel,
    WorkItemsEnvelope,
)


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
                res = services.control.update_work_item_status(
                    item_id, action, actor=session.email, reason=body.reason)
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
                  session=Depends(authenticated("editorial.review")),
                  limit: int = Query(200, ge=1, le=500)) -> dict[str, Any]:
        return {"editorial": services.control.work_items(source="backlog", limit=limit)}
    out.append(ed)

    pg = APIRouter(prefix="/pages", tags=["pages"])
    @pg.get("", response_model=PagesEnvelope, operation_id="pages_list")
    def pages(services: Services = Depends(get_services),
              session=Depends(authenticated("pages.read")),
              q: str = "", limit: int = Query(100, ge=1, le=500),
              offset: int = Query(0, ge=0)) -> dict[str, Any]:
        return {"pages": services.control.pages(query=q, limit=limit, offset=offset)}
    @pg.get("/{url}/history", operation_id="pages_history")
    def page_history(url: str, services: Services = Depends(get_services),
                     session=Depends(authenticated("pages.read"))) -> dict[str, Any]:
        from urllib.parse import unquote
        return {"url": unquote(url), "history": services.control.page_history(unquote(url))}
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
        run_id = services.runs.start_run("hermes-seo-agent", trigger="manual",
                                         intent=body.intent, mode=body.mode,
                                         started_by=session.email, target_url=body.target_url)
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
                     live: bool = False) -> dict[str, Any]:
        return {"integrations": services.control.integrations(live=live)}
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

    return out


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

    for r in read_routers():
        app.include_router(r, prefix="/api/v1")
    app.include_router(auth_router(), prefix="/api/v1")
    return app


def app() -> FastAPI:
    from ..config import load_config
    return create_app(storage_path=load_config().sqlite_path, config=load_config())
