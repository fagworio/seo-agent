"""AuthService: autenticação server-side + sessão + RBAC + MFA.

Princípios:
- Mensagens genéricas (anti-enumeração): "Email ou senha inválidos".
- Sessão server-side em cookie HttpOnly; só SHA-256(token) persiste.
- Sessão pré-login nunca vira a sessão autenticada (mitiga fixation).
- Expiração dupla: idle + absolute.
- Autorização por permissão, deny-by-default.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

from ..storage.auth_store import AuthStore
from .passwords import PasswordHasher
from .permissions import permissions_for_role
from .security import (
    generate_csrf_token,
    generate_session_token,
    hash_ip,
    hash_token,
    hash_user_agent,
)
from .totp import TOTP, generate_secret


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class AuthError(Exception):
    pass


@dataclass
class LoginResult:
    ok: bool
    reason: str | None = None              # None | invalid | disabled | requires_mfa
    user: dict[str, Any] | None = None
    session_token: str | None = None
    session_id: int | None = None
    mfa_user_id: int | None = None         # para o fluxo /verify-mfa
    requires_mfa: bool = False


@dataclass
class SessionInfo:
    user_id: int
    session_id: int
    expires_at: str
    idle_expires_at: str
    email: str
    name: str
    roles: list[str] = field(default_factory=list)
    permissions: set[str] = field(default_factory=set)
    is_mfa_enabled: bool = False


class AuthService:
    def __init__(
        self,
        storage: Any,
        *,
        config: Any | None = None,
        hasher: PasswordHasher | None = None,
        clock: Any | None = None,
    ) -> None:
        self.store = AuthStore(storage)
        self.store.seed_rbac()
        self.hasher = hasher or PasswordHasher()
        self.config = config
        self._clock = clock  # injectável para testes (callable -> iso string)

        self._idle = getattr(config, "session_idle_seconds", 8 * 3600)
        self._absolute = getattr(config, "session_absolute_seconds", 7 * 24 * 3600)
        self._max_attempts = getattr(config, "auth_max_attempts", 5)
        self._attempt_window = getattr(config, "auth_attempt_window_seconds", 900)
        self._mfa_issuer = getattr(config, "mfa_issuer", "SEO Agent")

    # -- time helpers --------------------------------------------------------
    def _base_dt(self) -> datetime.datetime:
        if self._clock:
            value = self._clock()
            if isinstance(value, datetime.datetime):
                return value
            return datetime.datetime.fromisoformat(value)
        return datetime.datetime.now(datetime.timezone.utc)

    def _now(self) -> str:
        return self._base_dt().isoformat()

    def _after(self, seconds: int) -> str:
        return (self._base_dt() + datetime.timedelta(seconds=seconds)).isoformat()

    # -- bootstrap / user management ----------------------------------------
    def create_admin(
        self,
        email: str,
        name: str,
        password: str,
        *,
        mfa_secret: str | None = None,
        now: str | None = None,
    ) -> int:
        """Cria o primeiro admin (bootstrap via CLI). MFA admin é obrigatório."""
        now = now or self._now()
        # admin sempre tem MFA (obrigatória) -> política com 2º fator (min 8)
        self.hasher.validate(password, mfa_enabled=True)
        user_id = self.store.create_user(
            email=email, name=name, password_hash=self.hasher.hash(password),
            is_active=1, now=now,
        )
        self.store.assign_role(user_id, "admin")
        if mfa_secret is None:
            mfa_secret = generate_secret()
        self.store.save_mfa_factor(user_id, mfa_secret, now=now)
        self.store.set_mfa_enabled(user_id, 1)
        self.store.record_event(now=now, actor="cli", user_id=user_id, event="USER_CREATED")
        return user_id

    def create_user(
        self,
        email: str,
        name: str,
        password: str,
        roles: list[str],
        *,
        mfa_secret: str | None = None,
        now: str | None = None,
    ) -> int:
        now = now or self._now()
        mfa_enabled = mfa_secret is not None
        self.hasher.validate(password, mfa_enabled=mfa_enabled)
        user_id = self.store.create_user(
            email=email, name=name, password_hash=self.hasher.hash(password),
            is_active=1, is_mfa_enabled=1 if mfa_enabled else 0, now=now,
        )
        for role in roles:
            self.store.assign_role(user_id, role)
        if mfa_secret is not None:
            self.store.save_mfa_factor(user_id, mfa_secret, now=now)
        self.store.record_event(now=now, actor="admin", user_id=user_id, event="USER_CREATED")
        return user_id

    def enable_mfa(self, user_id: int, *, now: str | None = None, secret: str | None = None) -> str:
        """Habilita TOTP para um usuário (admin), devolvendo o segredo."""
        now = now or self._now()
        if secret is None:
            secret = generate_secret()
        self.store.save_mfa_factor(user_id, secret, now=now)
        self.store.set_mfa_enabled(user_id, 1)
        return secret

    def set_user_roles(self, user_id: int, roles: list[str], *, now: str | None = None) -> bool:
        """Substitui roles (rotação: revoga sessões para aplicar novo RBAC)."""
        now = now or self._now()
        current = set(self.store.get_user_roles(user_id))
        new = set(roles)
        for role in current - new:
            self.store.remove_role(user_id, role)
        for role in new - current:
            self.store.assign_role(user_id, role)
        if current != new:
            # rotação de sessão em mudança de privilégio
            self.store.revoke_user_sessions(user_id, now=now)
            self.store.record_event(now=now, actor="admin", user_id=user_id, event="ROLE_CHANGED")
        return True

    # -- login ---------------------------------------------------------------
    def login(
        self,
        email: str,
        password: str,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
        now: str | None = None,
    ) -> LoginResult:
        now = now or self._now()
        ip_h = hash_ip(ip)
        email = (email or "").lower().strip()

        if self._throttled(email, ip_h, now):
            self._audit(now=now, actor=email, event="LOGIN_FAILURE")
            return LoginResult(ok=False, reason="invalid")

        user = self.store.get_user_by_email(email)
        if user is None or not user["password_hash"]:
            # mesmo tempo de resposta para contas inexistentes
            self.store.record_login_attempt(email, ip_h, "failure", now)
            self._audit(now=now, actor=email, event="LOGIN_FAILURE")
            return LoginResult(ok=False, reason="invalid")

        if not user["is_active"]:
            # não confirma desabilitado: mensagem genérica
            self._audit(now=now, actor=email, event="LOGIN_FAILURE")
            return LoginResult(ok=False, reason="invalid")

        if not self.hasher.verify(password, user["password_hash"]):
            self.store.record_login_attempt(email, ip_h, "failure", now)
            self._audit(now=now, actor=email, event="LOGIN_FAILURE")
            return LoginResult(ok=False, reason="invalid")

        # senha correta: se MFA habilitado, pedir 2º fator (não criar sessão ainda)
        if user["is_mfa_enabled"] and self.store.get_mfa_factor(user["id"]) is not None:
            self.store.record_login_attempt(email, ip_h, "success_password", now)
            return LoginResult(
                ok=True, reason=None, requires_mfa=True,
                mfa_user_id=user["id"], user=self._public_user(user),
            )

        session = self._start_session(user["id"], ip=ip, user_agent=user_agent, now=now)
        self._audit(now=now, actor=email, user_id=user["id"], event="LOGIN_SUCCESS")
        return LoginResult(
            ok=True, session_token=session["token"], session_id=session["session_id"],
            user=self._public_user(user),
        )

    def verify_mfa_login(
        self,
        user_id: int,
        code: str,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
        now: str | None = None,
    ) -> LoginResult:
        """Completa o login com o 2º fator e cria a sessão (rotacionada)."""
        now = now or self._now()
        user = self.store.get_user(user_id)
        if user is None or not user["is_active"]:
            self._audit(now=now, actor=str(user_id), event="MFA_FAILURE")
            return LoginResult(ok=False, reason="invalid")
        factor = self.store.get_mfa_factor(user_id)
        if factor is None or not factor["enabled"]:
            return LoginResult(ok=False, reason="invalid")
        totp = TOTP(factor["secret"])
        if not totp.verify(code):
            self.store.record_login_attempt(user["email"], hash_ip(ip), "failure", now)
            self._audit(now=now, actor=user["email"], user_id=user_id, event="MFA_FAILURE")
            return LoginResult(ok=False, reason="invalid")
        self.store.mark_mfa_used(user_id, now)
        session = self._start_session(user_id, ip=ip, user_agent=user_agent, now=now)
        self._audit(now=now, actor=user["email"], user_id=user_id, event="MFA_SUCCESS")
        return LoginResult(
            ok=True, session_token=session["token"], session_id=session["session_id"],
            user=self._public_user(user),
        )

    # -- session -------------------------------------------------------------
    def _start_session(self, user_id: int, *, ip: str | None, user_agent: str | None, now: str) -> dict[str, Any]:
        token = generate_session_token()
        token_hash = hash_token(token)
        expires_at = self._after(self._absolute)
        idle_expires_at = self._after(self._idle)
        session_id = self.store.create_session(
            user_id=user_id, token_hash=token_hash, now=now,
            expires_at=expires_at, idle_expires_at=idle_expires_at,
            ip_hash=hash_ip(ip), user_agent=hash_user_agent(user_agent),
        )
        return {"token": token, "session_id": session_id}

    def validate_session(self, token: str, *, now: str | None = None) -> SessionInfo | None:
        """Valida e renova o idle. Retorna None se revogada/expirada."""
        now = now or self._now()
        if not token:
            return None
        sess = self.store.get_session_by_token_hash(hash_token(token))
        if sess is None or sess["revoked_at"] is not None:
            return None
        if now > sess["expires_at"]:
            return None
        if now > sess["idle_expires_at"]:
            return None
        user = self.store.get_user(sess["user_id"])
        if user is None or not user["is_active"]:
            return None
        # renova idle
        self.store.touch_session(sess["id"], now, self._after(self._idle))
        roles = self.store.get_user_roles(sess["user_id"])
        perms = self._permissions_for_roles(roles)
        return SessionInfo(
            user_id=sess["user_id"], session_id=sess["id"],
            expires_at=sess["expires_at"], idle_expires_at=sess["idle_expires_at"],
            email=user["email"], name=user["name"], roles=roles,
            permissions=perms, is_mfa_enabled=user["is_mfa_enabled"],
        )

    def logout(self, token: str, *, now: str | None = None) -> None:
        now = now or self._now()
        sess = self.store.get_session_by_token_hash(hash_token(token))
        if sess is not None and sess["revoked_at"] is None:
            self.store.revoke_session(sess["id"], now)
            self._audit(now=now, user_id=sess["user_id"], event="LOGOUT")

    def list_sessions(self, user_id: int) -> list[dict[str, Any]]:
        return self.store.list_user_sessions(user_id)

    def revoke_session(self, user_id: int, session_id: int, *, now: str | None = None) -> bool:
        sess = self.store.list_user_sessions(user_id)
        target = next((s for s in sess if s["id"] == session_id and s["revoked_at"] is None), None)
        if target is None:
            return False
        now = now or self._now()
        self.store.revoke_session(session_id, now)
        return True

    def revoke_other_sessions(self, user_id: int, current_session_id: int, *, now: str | None = None) -> int:
        now = now or self._now()
        return self.store.revoke_user_sessions(
            user_id, now=now, exclude_session_id=current_session_id
        )

    # -- password change / reset --------------------------------------------
    def change_password(
        self, user_id: int, new_password: str, *, mfa_enabled: bool = False, now: str | None = None
    ) -> None:
        now = now or self._now()
        self.hasher.validate(new_password, mfa_enabled=mfa_enabled)
        self.store.set_password_hash(user_id, self.hasher.hash(new_password), now)
        # revoga sessões antigas (exceto a atual é opcional; fará nova sessão)
        self.store.revoke_user_sessions(user_id, now=now)
        self._audit(now=now, user_id=user_id, event="PASSWORD_CHANGED")

    # -- RBAC ----------------------------------------------------------------
    def _permissions_for_roles(self, roles: list[str]) -> set[str]:
        perms: set[str] = set()
        for role in roles:
            perms |= permissions_for_role(role)
        return perms

    def permissions_for(self, user_id: int) -> set[str]:
        return self._permissions_for_roles(self.store.get_user_roles(user_id))

    def require_permission(self, user_id: int, permission: str) -> bool:
        return permission in self.permissions_for(user_id)

    # -- csrf (decorative helper; enforcement real no FastAPI) ---------------
    @staticmethod
    def csrf() -> str:
        return generate_csrf_token()

    # -- helpers -------------------------------------------------------------
    def _throttled(self, email: str, ip_hash: str | None, now: str) -> bool:
        since = self._after(-self._attempt_window)
        c = self.store.count_recent_failures(email, ip_hash, since)
        return c >= self._max_attempts

    def _audit(self, *, now: str, actor: str | None = None, event: str, user_id: int | None = None) -> None:
        self.store.record_event(now=now, actor=actor, user_id=user_id, event=event)

    def _public_user(self, user: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "is_mfa_enabled": user["is_mfa_enabled"],
            "roles": self.store.get_user_roles(user["id"]),
            "permissions": sorted(self.permissions_for(user["id"])),
        }
