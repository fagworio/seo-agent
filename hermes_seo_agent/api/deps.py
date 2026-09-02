"""Dependências FastAPI: serviços por request, sessão, RBAC, CSRF, request_id.

Cada request abre a própria Storage (a conexão SQLite é usada no mesmo thread do
endpoint — o FastAPI roda os endpoints sync no threadpool). Backend é a fonte de
autorização: deny-by-default, CSRF em mutações.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from ..auth.service import AuthService, SessionInfo
from ..services.agent_runs import AgentRunService
from ..services.control_plane import ControlPlaneService
from ..storage.db import Storage
from .errors import ApiError, InvalidCsrf, Unauthenticated
from .http import session_cookie_name


@dataclass
class Services:
    storage: Storage
    config: Any
    auth: AuthService
    control: ControlPlaneService
    runs: AgentRunService


def get_services(request: Request) -> Services:
    storage_path = request.app.state.storage_path
    config = request.app.state.config
    storage = Storage(storage_path)
    try:
        yield Services(
            storage=storage,
            config=config,
            auth=AuthService(storage, config=config),
            control=ControlPlaneService(storage, config),
            runs=AgentRunService(storage),
        )
    finally:
        storage.close()


def _session_from_request(request: Request, services: Services) -> SessionInfo:
    name = session_cookie_name(services.config)
    token = request.cookies.get(name) or ""
    if not token:
        raise Unauthenticated()
    session = services.auth.validate_session(token)
    if session is None:
        raise Unauthenticated()
    return session


def authenticated(perm: str | None = None, *, csrf: bool = False) -> Callable[..., SessionInfo]:
    """Dependência fábrica: sessão válida + (opcional) permissão + (opcional) CSRF."""

    def dep(request: Request, services: Services = Depends(get_services)) -> SessionInfo:
        session = _session_from_request(request, services)
        if perm and perm not in session.permissions:
            from .errors import Forbidden
            raise Forbidden()
        if csrf:
            token = request.headers.get(getattr(services.config, "csrf_header", "X-CSRF-Token"))
            if not services.auth.verify_csrf(session.session_id, token):
                raise InvalidCsrf()
        return session

    return dep


# -- erro consistente ---------------------------------------------------------
def register_error_handlers(app) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        rid = getattr(getattr(request, "state", None), "request_id", "")
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"code": exc.code, "message": exc.message, "request_id": rid}},
        )

    @app.exception_handler(Exception)
    async def _any_error(request: Request, exc: Exception):
        rid = getattr(getattr(request, "state", None), "request_id", "")
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL", "message": "Erro interno do servidor.",
                               "request_id": rid}},
        )
