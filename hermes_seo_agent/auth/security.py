"""Security primitives: opaque session token, CSRF token, hashing helpers.

O token de sessão é aleatório, opaco e sem significado (OWASP Session
Management). O backend guarda apenas SHA-256(session_token); o navegador nunca
recebe user_id/roles/credenciais.
"""

from __future__ import annotations

import hashlib
import secrets


def generate_session_token() -> str:
    """Token de sessão aleatório e opaco (não carrega dados)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 hex do token; é o que persistimos (nunca o token puro)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def hash_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]


def hash_user_agent(ua: str | None) -> str | None:
    if not ua:
        return None
    return hashlib.sha256(ua.encode("utf-8")).hexdigest()[:16]


def constant_time_eq(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
