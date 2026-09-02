"""Control plane: transporte HTTP puro (sem framework) e contratos de request/response.

O Router opera sobre :class:`HttpRequest`/:class:`HttpResponse` (sem socket),
o que torna a lógica de roteamento/auth/CSRF/RBAC determinística e testável. O
`server.py` apenas faz a ponte socket <-> estes objetos. Quando o ambiente tiver
FastAPI, os mesmos handlers são ligados como roteadores finos (ADR-0009).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HttpRequest:
    method: str
    path: str
    query: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] | None = None
    client_ip: str = ""

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())

    def cookie_value(self, name: str) -> str | None:
        raw = self.header("cookie") or ""
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == name and v:
                return v
        return None


@dataclass
class HttpResponse:
    status: int = 200
    body: dict[str, Any] = field(default_factory=dict)
    set_cookie: dict[str, str] | None = None   # {name: value, ...attrs}
    delete_cookie: str | None = None

    @classmethod
    def json(cls, status: int, body: dict[str, Any]) -> "HttpResponse":
        return cls(status=status, body=body)

    @classmethod
    def error(cls, status: int, code: str, message: str, request_id: str) -> "HttpResponse":
        return cls.json(status, {"error": {"code": code, "message": message,
                                            "request_id": request_id}})


def parse_query_string(qs: str) -> dict[str, str]:
    from urllib.parse import parse_qsl

    return {k: v for k, v in parse_qsl(qs)}


def parse_json_body(data: bytes | None) -> dict[str, Any] | None:
    if not data:
        return None
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def set_session_cookie(cookie_name: str, token: str, *, secure: bool,
                       max_age: int) -> dict[str, str]:
    parts = [
        f"{cookie_name}={token}",
        "HttpOnly",
        f"SameSite=Strict",
        "Path=/",
        f"Max-Age={max_age}",
    ]
    if secure:
        parts.append("Secure")
    # __Host- exige Secure, Path=/, sem Domain
    return {"header": "; ".join(parts)}


def session_cookie_name(config: Any) -> str:
    return getattr(config, "session_cookie_name", "__Host-seo_session")


def new_request_id() -> str:
    import uuid
    return "req_" + uuid.uuid4().hex[:12]
