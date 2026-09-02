"""Control plane router: roteia /api/v1/* para os services (framework-agnóstico).

Reutiliza AuthService (sessão cookie, RBAC por permissão, MFA), ControlPlaneService
(read models) e AgentRunService. Aplica: autenticação por cookie de sessão,
autorização por permissão (deny-by-default), CSRF em mutações autenticadas e
rate limiting em endpoints sensíveis. Frame de erro nunca vaza traceback.
"""

from __future__ import annotations

from typing import Any

from ..auth.rate_limit import SlidingWindowLimiter
from ..auth.service import AuthService
from ..services.agent_runs import AgentRunService
from ..services.control_plane import ControlPlaneService
from .errors import (
    ApiError, BadRequest, Forbidden, InvalidCsrf, NotFound, TooManyRequests,
    Unauthenticated,
)
from .http import (
    HttpResponse, HttpRequest, new_request_id, parse_json_body, parse_query_string,
    session_cookie_name, set_session_cookie,
)


class Router:
    def __init__(self, storage: Any, config: Any, *, hasher: Any | None = None,
                 clock: Any | None = None) -> None:
        self.storage = storage
        self.config = config
        self.auth = AuthService(storage, config=config, hasher=hasher, clock=clock)
        self.control = ControlPlaneService(storage, config)
        self.runs = AgentRunService(storage)
        self.limiter = SlidingWindowLimiter(
            max_events=getattr(config, "auth_max_attempts", 5),
            window_seconds=getattr(config, "auth_attempt_window_seconds", 900),
        )
        self._routes: list[dict[str, Any]] = []
        self._register()

    # -- registro de rotas ---------------------------------------------------
    def _add(self, method: str, path: str, handler, *, public: bool = False,
             perm: str | None = None, csrf: bool = False, rate_limit: bool = False) -> None:
        segments = tuple(s for s in path.strip("/").split("/") if s)
        self._routes.append({
            "method": method, "segments": segments, "handler": handler,
            "public": public, "perm": perm, "csrf": csrf, "rate_limit": rate_limit,
        })

    def _register(self) -> None:
        a = self._add
        # público (sem sessão)
        a("POST", "/api/v1/auth/login", self._login, public=True, rate_limit=True)
        a("POST", "/api/v1/auth/mfa/verify", self._mfa_verify, public=True, rate_limit=True)
        a("POST", "/api/v1/auth/forgot-password", self._forgot, public=True, rate_limit=True)
        a("POST", "/api/v1/auth/reset-password", self._reset, public=True, rate_limit=True)
        # autenticado (perm default: nenhuma leitura/escrita básica)
        a("POST", "/api/v1/auth/logout", self._logout, csrf=True)
        a("GET", "/api/v1/auth/me", self._me)
        a("GET", "/api/v1/auth/sessions", self._sessions)
        a("POST", "/api/v1/auth/sessions/revoke-others", self._revoke_others, csrf=True)
        a("DELETE", "/api/v1/auth/sessions/{id}", self._revoke_session, csrf=True)
        # produto
        a("GET", "/api/v1/dashboard/today", self._today, perm="dashboard.read")
        a("GET", "/api/v1/work-items", self._work_items, perm="opportunity.read")
        a("GET", "/api/v1/integrations", self._integrations, perm="integration.read")
        a("GET", "/api/v1/activity", self._activity, perm="audit.read")
        a("GET", "/api/v1/agents", self._agents, perm="agent.read")
        a("GET", "/api/v1/runs", self._runs_list, perm="agent.read")
        a("GET", "/api/v1/runs/{id}", self._run_detail, perm="agent.read")

    # -- roteamento ----------------------------------------------------------
    def handle(self, request: HttpRequest, request_id: str | None = None) -> HttpResponse:
        request_id = request_id or new_request_id()
        try:
            route = self._match(request.method, request.path)
            return self._dispatch(route, request, request_id)
        except ApiError as exc:
            return HttpResponse.error(exc.status, exc.code, exc.message, request_id)
        except Exception:
            return HttpResponse.error(500, "INTERNAL", "Erro interno do servidor.", request_id)

    def _match(self, method: str, path: str) -> dict[str, Any]:
        segs = tuple(s for s in path.strip("/").split("/") if s)
        best: dict[str, Any] | None = None
        for route in self._routes:
            if route["method"] != method:
                continue
            params: dict[str, str] = {}
            if len(route["segments"]) != len(segs):
                continue
            ok = True
            for tpl, actual in zip(route["segments"], segs):
                if tpl.startswith("{") and tpl.endswith("}"):
                    params[tpl[1:-1]] = actual
                elif tpl != actual:
                    ok = False
                    break
            if ok:
                best = dict(route)
                best["params"] = params
        if best is None:
            raise NotFound(f"Método/rota não encontrado: {method} {path}")
        return best

    def _dispatch(self, route: dict[str, Any], request: HttpRequest, request_id: str) -> HttpResponse:
        if route.get("rate_limit") and not self.limiter.allow(request.client_ip or "?"):
            raise TooManyRequests()
        session = None
        if not route.get("public"):
            session = self._current_session(request)
            if session is None:
                raise Unauthenticated()
            # autorização: deny-by-default (perm ausente => só autenticado)
            perm = route.get("perm")
            if perm and perm not in session.permissions:
                raise Forbidden()
            if route.get("csrf") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                token = request.header("x-csrf-token")
                if not self.auth.verify_csrf(session.session_id, token):
                    raise InvalidCsrf()
        body = parse_json_body(request.body)
        # handlers podem sobrescrever session se precisarem (ex.: me)
        request._json_body = body
        request._session = session
        request._request_id = request_id
        result = route["handler"](request, route.get("params", {}))
        return result

    # -- auth por cookie -----------------------------------------------------
    def _current_session(self, request: HttpRequest):
        name = session_cookie_name(self.config)
        token = request.cookie_value(name)
        if not token:
            return None
        return self.auth.validate_session(token)

    # -- handlers ------------------------------------------------------------
    def _login(self, request: HttpRequest, params: dict[str, str]) -> HttpResponse:
        body = request._json_body or {}
        email = body.get("email", "")
        password = body.get("password", "")
        res = self.auth.login(email, password, ip=request.client_ip,
                              user_agent=request.header("user-agent"))
        if not res.ok:
            return HttpResponse.json(200, {"ok": False, "message": "Email ou senha inválidos."})
        payload: dict[str, Any] = {"ok": True, "user": res.user,
                                   "requires_mfa": res.requires_mfa}
        if res.requires_mfa:
            payload["mfa_user_id"] = res.mfa_user_id
            return HttpResponse.json(200, payload)
        payload.update({"csrf_token": res.csrf_token})
        return self._session_response(payload, res.session_token)

    def _mfa_verify(self, request: HttpRequest, params: dict[str, str]) -> HttpResponse:
        body = request._json_body or {}
        res = self.auth.verify_mfa_login(int(body.get("user_id", 0)), body.get("code", ""),
                                         ip=request.client_ip,
                                         user_agent=request.header("user-agent"))
        if not res.ok:
            return HttpResponse.json(200, {"ok": False, "message": "Código inválido ou expirado."})
        payload = {"ok": True, "user": res.user, "csrf_token": res.csrf_token}
        return self._session_response(payload, res.session_token)

    def _logout(self, request: HttpRequest, params: dict[str, str]) -> HttpResponse:
        token = request.cookie_value(session_cookie_name(self.config))
        if token:
            self.auth.logout(token)
        resp = HttpResponse.json(200, {"ok": True, "message": "Sessão encerrada."})
        resp.delete_cookie = session_cookie_name(self.config)
        return resp

    def _forgot(self, request: HttpRequest, params: dict[str, str]) -> HttpResponse:
        body = request._json_body or {}
        res = self.auth.request_password_reset(body.get("email", ""))
        return HttpResponse.json(200, res)

    def _reset(self, request: HttpRequest, params: dict[str, str]) -> HttpResponse:
        body = request._json_body or {}
        ok = self.auth.reset_password(body.get("token", ""), body.get("new_password", ""))
        msg = "Senha redefinida." if ok else "Token inválido ou expirado."
        return HttpResponse.json(200, {"ok": ok, "message": msg})

    def _me(self, request: HttpRequest, params: dict[str, str]) -> HttpResponse:
        session = request._session
        csrf = self.auth.issue_csrf(session.session_id)
        return HttpResponse.json(200, {
            "user": {"id": session.user_id, "email": session.email, "name": session.name,
                     "roles": session.roles, "permissions": sorted(session.permissions),
                     "is_mfa_enabled": session.is_mfa_enabled},
            "csrf_token": csrf,
        })

    def _sessions(self, request: HttpRequest, params: dict[str, str]) -> HttpResponse:
        session = request._session
        return HttpResponse.json(200, {"sessions": self.auth.list_sessions(session.user_id)})

    def _revoke_others(self, request: HttpRequest, params: dict[str, str]) -> HttpResponse:
        session = request._session
        n = self.auth.revoke_other_sessions(session.user_id, session.session_id)
        return HttpResponse.json(200, {"ok": True, "revoked": n})

    def _revoke_session(self, request: HttpRequest, params: dict[str, str]) -> HttpResponse:
        session = request._session
        ok = self.auth.revoke_session(session.user_id, int(params["id"]))
        return HttpResponse.json(200, {"ok": ok})

    def _today(self, request: HttpRequest, params: dict[str, str]) -> HttpResponse:
        limit = int(request.query.get("limit", "10"))
        return HttpResponse.json(200, {"today": self.control.today(limit=limit)})

    def _work_items(self, request: HttpRequest, params: dict[str, str]) -> HttpResponse:
        return HttpResponse.json(200, {"work_items": self.control.work_items(
            source=request.query.get("source") or None,
            status=request.query.get("status") or None,
            limit=int(request.query.get("limit", "200")),
        )})

    def _integrations(self, request: HttpRequest, params: dict[str, str]) -> HttpResponse:
        live = request.query.get("live", "") in {"1", "true", "yes"}
        return HttpResponse.json(200, {"integrations": self.control.integrations(live=live)})

    def _activity(self, request: HttpRequest, params: dict[str, str]) -> HttpResponse:
        return HttpResponse.json(200, {"activity": self.control.activity(
            limit=int(request.query.get("limit", "50")))})

    def _agents(self, request: HttpRequest, params: dict[str, str]) -> HttpResponse:
        return HttpResponse.json(200, {"agents": self.runs.list_agents()})

    def _runs_list(self, request: HttpRequest, params: dict[str, str]) -> HttpResponse:
        return HttpResponse.json(200, {"runs": self.runs.list_runs(
            agent=request.query.get("agent") or None,
            status=request.query.get("status") or None,
            limit=int(request.query.get("limit", "50")),
        )})

    def _run_detail(self, request: HttpRequest, params: dict[str, str]) -> HttpResponse:
        run = self.runs.get_run(int(params["id"]))
        if run is None:
            raise NotFound("Execução não encontrada.")
        return HttpResponse.json(200, {"run": run})

    def _session_response(self, payload: dict[str, Any], token: str | None):
        resp = HttpResponse.json(200, payload)
        if token:
            name = session_cookie_name(self.config)
            resp.set_cookie = {"header": set_session_cookie(
                name, token,
                secure=getattr(self.config, "session_cookie_secure", True),
                max_age=getattr(self.config, "session_idle_seconds", 8 * 3600),
            )["header"]}
        return resp
