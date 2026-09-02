"""Binding HTTP stdlib: ponte socket <-> HttpRequest/HttpResponse.

Usado enquanto o ambiente não tem FastAPI (ADR-0009). A lógica de negócio e
segurança vivem nos services/router; este módulo só traduz a fronteira de
transporte. Em produção com FastAPI, o `Router.handle` é ligado como roteador
fino com a mesma semântica.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .http import HttpResponse, HttpRequest


def build_request(handler: BaseHTTPRequestHandler) -> HttpRequest:
    raw = handler.rfile.read(int(handler.headers.get("Content-Length", 0) or 0))
    method = handler.command or "GET"
    # path + query
    from urllib.parse import urlsplit

    split = urlsplit(handler.path)
    query = _parse_qs(split.query)
    ip = (handler.client_address[0] if handler.client_address else "")
    # headers normalizados (lower)
    headers = {k.lower(): v for k, v in handler.headers.items()}
    return HttpRequest(method=method, path=split.path, query=query,
                       headers=headers, body=raw, client_ip=ip)


def _parse_qs(qs: str) -> dict[str, str]:
    from urllib.parse import parse_qsl

    return dict(parse_qsl(qs))


class _Handler(BaseHTTPRequestHandler):
    server_version = "seo-agent-api/0.1"

    def _route(self) -> None:
        # uma Storage+Router por request (conexão SQLite no próprio thread).
        router = self.server.router_factory()  # type: ignore[attr-defined]
        req = build_request(self)
        resp = router.handle(req)
        self._write_response(resp)

    def _write_response(self, resp: HttpResponse) -> None:
        payload = json.dumps(resp.body, ensure_ascii=False).encode("utf-8")
        self.send_response(resp.status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        if resp.set_cookie and "header" in resp.set_cookie:
            self.send_header("Set-Cookie", resp.set_cookie["header"])
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        self._route()

    def do_POST(self) -> None:  # noqa: N802
        self._route()

    def do_PUT(self) -> None:  # noqa: N802
        self._route()

    def do_PATCH(self) -> None:  # noqa: N802
        self._route()

    def do_DELETE(self) -> None:  # noqa: N802
        self._route()

    def log_message(self, fmt: str, *args: Any) -> None:  # silencioso
        return


def make_server(router_factory, host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), _Handler)
    server.router_factory = router_factory  # type: ignore[attr-defined]
    return server


def serve(router_factory, host: str = "127.0.0.1", port: int = 8000) -> None:
    server = make_server(router_factory, host=host, port=port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
