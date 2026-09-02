"""Camada de persistência de auth (users, roles, sessions, mfa, reset, eventos).

Opera sobre a conexão do :class:`~hermes_seo_agent.storage.db.Storage` para
compartilhar a transação do SQLite do projeto. Guarda apenas hashes de tokens
(SHA-256), nunca tokens puros / senhas.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..auth.permissions import seed_rbac


class AuthStore:
    def __init__(self, storage: Any) -> None:
        self.storage = storage
        self.conn: sqlite3.Connection = storage.conn

    def seed_rbac(self) -> None:
        seed_rbac(self.conn)
        self.conn.commit()

    # -- users ---------------------------------------------------------------
    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, email, name, password_hash, is_active, is_mfa_enabled, "
            "must_change_password, created_at, updated_at, last_login_at "
            "FROM users WHERE email = ?",
            (email.lower().strip(),),
        ).fetchone()
        return self._user_row(row)

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, email, name, password_hash, is_active, is_mfa_enabled, "
            "must_change_password, created_at, updated_at, last_login_at "
            "FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return self._user_row(row)

    def create_user(
        self,
        *,
        email: str,
        name: str,
        password_hash: str,
        is_active: int = 1,
        is_mfa_enabled: int = 0,
        must_change_password: int = 0,
        now: str,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO users (email, name, password_hash, is_active, "
            "is_mfa_enabled, must_change_password, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (email.lower().strip(), name, password_hash, is_active, is_mfa_enabled,
             must_change_password, now, now),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def set_password_hash(self, user_id: int, password_hash: str, now: str) -> None:
        self.conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (password_hash, now, user_id),
        )
        self.conn.commit()

    def set_password_must_change(self, user_id: int, value: int) -> None:
        self.conn.execute(
            "UPDATE users SET must_change_password = ? WHERE id = ?", (value, user_id)
        )
        self.conn.commit()

    def set_mfa_enabled(self, user_id: int, enabled: int) -> None:
        self.conn.execute(
            "UPDATE users SET is_mfa_enabled = ?, updated_at = "
            "COALESCE(updated_at, datetime('now')) WHERE id = ?",
            (enabled, user_id),
        )
        self.conn.commit()

    def set_last_login(self, user_id: int, now: str) -> None:
        self.conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, user_id))
        self.conn.commit()

    def disable_user(self, user_id: int) -> None:
        self.conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
        self.conn.commit()

    def enable_user(self, user_id: int) -> None:
        self.conn.execute("UPDATE users SET is_active = 1 WHERE id = ?", (user_id,))
        self.conn.commit()

    def list_users(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, email, name, is_active, is_mfa_enabled, last_login_at, "
            "created_at FROM users ORDER BY id"
        ).fetchall()
        out = []
        for row in rows:
            out.append(
                {
                    "id": row[0],
                    "email": row[1],
                    "name": row[2],
                    "is_active": bool(row[3]),
                    "is_mfa_enabled": bool(row[4]),
                    "last_login_at": row[5],
                    "created_at": row[6],
                }
            )
        return out

    # -- roles ---------------------------------------------------------------
    def assign_role(self, user_id: int, role_name: str) -> bool:
        row = self.conn.execute("SELECT id FROM roles WHERE name = ?", (role_name,)).fetchone()
        if not row:
            return False
        self.conn.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)",
            (user_id, row[0]),
        )
        self.conn.commit()
        return True

    def remove_role(self, user_id: int, role_name: str) -> bool:
        row = self.conn.execute("SELECT id FROM roles WHERE name = ?", (role_name,)).fetchone()
        if not row:
            return False
        self.conn.execute(
            "DELETE FROM user_roles WHERE user_id = ? AND role_id = ?", (user_id, row[0])
        )
        self.conn.commit()
        return True

    def get_user_roles(self, user_id: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT r.name FROM roles r JOIN user_roles ur ON ur.role_id = r.id "
            "WHERE ur.user_id = ? ORDER BY r.name",
            (user_id,),
        ).fetchall()
        return [r[0] for r in rows]

    # -- sessions ------------------------------------------------------------
    def create_session(
        self,
        *,
        user_id: int,
        token_hash: str,
        now: str,
        expires_at: str,
        idle_expires_at: str,
        ip_hash: str | None,
        user_agent: str | None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO sessions (user_id, token_hash, created_at, last_seen_at, "
            "expires_at, idle_expires_at, ip_hash, user_agent) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, token_hash, now, now, expires_at, idle_expires_at, ip_hash, user_agent),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_session_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, user_id, token_hash, created_at, last_seen_at, expires_at, "
            "idle_expires_at, ip_hash, user_agent, revoked_at, csrf_token_hash, "
            "strong_auth_at FROM sessions WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        return self._session_row(row)

    def touch_session(self, session_id: int, now: str, idle_expires_at: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET last_seen_at = ?, idle_expires_at = ? WHERE id = ?",
            (now, idle_expires_at, session_id),
        )
        self.conn.commit()

    def revoke_session(self, session_id: int, now: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (now, session_id),
        )
        self.conn.commit()

    def revoke_user_sessions(self, user_id: int, *, now: str, exclude_session_id: int | None = None) -> int:
        if exclude_session_id is not None:
            cur = self.conn.execute(
                "UPDATE sessions SET revoked_at = ? WHERE user_id = ? "
                "AND revoked_at IS NULL AND id != ?",
                (now, user_id, exclude_session_id),
            )
        else:
            cur = self.conn.execute(
                "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (now, user_id),
            )
        self.conn.commit()
        return cur.rowcount

    def list_user_sessions(self, user_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, created_at, last_seen_at, expires_at, idle_expires_at, "
            "ip_hash, user_agent, revoked_at, csrf_token_hash, strong_auth_at "
            "FROM sessions WHERE user_id = ? ORDER BY COALESCE(last_seen_at, created_at) DESC",
            (user_id,),
        ).fetchall()
        return [
            {
                "id": r[0],
                "created_at": r[1],
                "last_seen_at": r[2],
                "expires_at": r[3],
                "idle_expires_at": r[4],
                "ip_hash": r[5],
                "user_agent": r[6],
                "revoked_at": r[7],
                "csrf_token_hash": r[8],
                "strong_auth_at": r[9],
            }
            for r in rows
        ]

    def get_session_by_id(self, session_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, user_id, token_hash, created_at, last_seen_at, expires_at, "
            "idle_expires_at, ip_hash, user_agent, revoked_at, csrf_token_hash, "
            "strong_auth_at FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        return self._session_row(row)

    def set_session_csrf(self, session_id: int, csrf_token_hash: str | None) -> None:
        self.conn.execute(
            "UPDATE sessions SET csrf_token_hash = ? WHERE id = ?",
            (csrf_token_hash, session_id),
        )
        self.conn.commit()

    def get_session_csrf_hash(self, session_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT csrf_token_hash FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return row[0] if row else None

    def set_session_strong_auth(self, session_id: int, now: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET strong_auth_at = ? WHERE id = ?", (now, session_id)
        )
        self.conn.commit()

    # -- mfa -----------------------------------------------------------------
    def save_mfa_factor(self, user_id: int, secret: str, *, kind: str = "totp", now: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO mfa_factors (user_id, kind, secret, enabled, created_at) "
            "VALUES (?, ?, ?, 1, ?)",
            (user_id, kind, secret, now),
        )
        self.conn.commit()

    def get_mfa_factor(self, user_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, user_id, kind, secret, enabled, created_at, last_used_at "
            "FROM mfa_factors WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "user_id": row[1],
            "kind": row[2],
            "secret": row[3],
            "enabled": bool(row[4]),
            "created_at": row[5],
            "last_used_at": row[6],
        }

    def mark_mfa_used(self, user_id: int, now: str) -> None:
        self.conn.execute(
            "UPDATE mfa_factors SET last_used_at = ? WHERE user_id = ?", (now, user_id)
        )
        self.conn.commit()

    # -- password reset ------------------------------------------------------
    def create_reset_token(self, user_id: int, token_hash: str, now: str, expires_at: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO password_reset_tokens (user_id, token_hash, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, token_hash, now, expires_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_reset_token(self, token_hash: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, user_id, token_hash, created_at, expires_at, used_at, revoked_at "
            "FROM password_reset_tokens WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "user_id": row[1],
            "token_hash": row[2],
            "created_at": row[3],
            "expires_at": row[4],
            "used_at": row[5],
            "revoked_at": row[6],
        }

    def consume_reset_token(self, token_id: int, now: str) -> None:
        self.conn.execute(
            "UPDATE password_reset_tokens SET used_at = ? WHERE id = ?", (now, token_id)
        )
        self.conn.commit()

    # -- login attempts / throttle ------------------------------------------
    def record_login_attempt(self, email: str | None, ip_hash: str | None, outcome: str, now: str) -> None:
        self.conn.execute(
            "INSERT INTO login_attempts (email, ip_hash, outcome, at) VALUES (?, ?, ?, ?)",
            (email.lower().strip() if email else None, ip_hash, outcome, now),
        )
        self.conn.commit()

    def count_recent_failures(self, email: str | None, ip_hash: str | None, since: str) -> int:
        sql = "SELECT COUNT(*) FROM login_attempts WHERE outcome = 'failure' AND at >= ?"
        params: list[Any] = [since]
        if email or ip_hash:
            clauses = []
            if email:
                clauses.append("email = ?")
                params.append(email.lower().strip())
            if ip_hash:
                clauses.append("ip_hash = ?")
                params.append(ip_hash)
            sql += " AND (" + " OR ".join(clauses) + ")"
        row = self.conn.execute(sql, params).fetchone()
        return row[0] if row else 0

    # -- auth events / audit -------------------------------------------------
    def record_event(self, *, now: str, actor: str | None, user_id: int | None, event: str, detail: dict | None = None) -> None:
        self.conn.execute(
            "INSERT INTO auth_events (ts, actor, user_id, event, detail_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (now, actor, user_id, event, json.dumps(detail, ensure_ascii=False) if detail else None),
        )
        self.conn.commit()

    def list_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, ts, actor, user_id, event, detail_json FROM auth_events "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for r in rows:
            detail = None
            if r[5]:
                try:
                    detail = json.loads(r[5])
                except Exception:
                    detail = None
            out.append(
                {
                    "id": r[0],
                    "ts": r[1],
                    "actor": r[2],
                    "user_id": r[3],
                    "event": r[4],
                    "detail": detail,
                }
            )
        return out

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _user_row(row: tuple | None) -> dict[str, Any] | None:
        if not row:
            return None
        return {
            "id": row[0],
            "email": row[1],
            "name": row[2],
            "password_hash": row[3],
            "is_active": bool(row[4]),
            "is_mfa_enabled": bool(row[5]),
            "must_change_password": bool(row[6]),
            "created_at": row[7],
            "updated_at": row[8],
            "last_login_at": row[9],
        }

    @staticmethod
    def _session_row(row: tuple | None) -> dict[str, Any] | None:
        if not row:
            return None
        return {
            "id": row[0],
            "user_id": row[1],
            "token_hash": row[2],
            "created_at": row[3],
            "last_seen_at": row[4],
            "expires_at": row[5],
            "idle_expires_at": row[6],
            "ip_hash": row[7],
            "user_agent": row[8],
            "revoked_at": row[9],
            "csrf_token_hash": row[10],
            "strong_auth_at": row[11],
        }
