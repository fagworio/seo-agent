"""RBAC: permissões → roles → usuários.

O código de feature nunca deve depender de roles diretamente; deve checar
permissões (`user_has_permission`). A UI pode esconder botões, mas a autorização
é enforced server-side (`require_permission`), com deny-by-default.
"""

from __future__ import annotations

from typing import Any


class Perm:
    DASHBOARD_READ = "dashboard.read"

    OPPORTUNITY_READ = "opportunity.read"
    OPPORTUNITY_REVIEW = "opportunity.review"

    TECHNICAL_READ = "technical.read"
    TECHNICAL_SAFE_FIX = "technical.safe_fix"
    TECHNICAL_APPROVE_RISKY = "technical.approve_risky"

    EDITORIAL_READ = "editorial.read"
    EDITORIAL_REVIEW = "editorial.review"
    EDITORIAL_PUBLISH_CONFIRM = "editorial.publish_confirm"

    AGENT_READ = "agent.read"
    AGENT_RUN = "agent.run"
    AGENT_CANCEL = "agent.cancel"

    EXPERIMENT_READ = "experiment.read"
    INTEGRATION_READ = "integration.read"
    INTEGRATION_MANAGE = "integration.manage"

    USERS_READ = "users.read"
    USERS_MANAGE = "users.manage"

    SETTINGS_READ = "settings.read"
    SETTINGS_MANAGE = "settings.manage"

    AUDIT_READ = "audit.read"


_ALL_PERMISSIONS = {
    Perm.DASHBOARD_READ,
    Perm.OPPORTUNITY_READ,
    Perm.OPPORTUNITY_REVIEW,
    Perm.TECHNICAL_READ,
    Perm.TECHNICAL_SAFE_FIX,
    Perm.TECHNICAL_APPROVE_RISKY,
    Perm.EDITORIAL_READ,
    Perm.EDITORIAL_REVIEW,
    Perm.EDITORIAL_PUBLISH_CONFIRM,
    Perm.AGENT_READ,
    Perm.AGENT_RUN,
    Perm.AGENT_CANCEL,
    Perm.EXPERIMENT_READ,
    Perm.INTEGRATION_READ,
    Perm.INTEGRATION_MANAGE,
    Perm.USERS_READ,
    Perm.USERS_MANAGE,
    Perm.SETTINGS_READ,
    Perm.SETTINGS_MANAGE,
    Perm.AUDIT_READ,
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": set(_ALL_PERMISSIONS),
    "operator": {
        Perm.DASHBOARD_READ,
        Perm.OPPORTUNITY_READ,
        Perm.OPPORTUNITY_REVIEW,
        Perm.TECHNICAL_READ,
        Perm.TECHNICAL_SAFE_FIX,
        Perm.TECHNICAL_APPROVE_RISKY,
        Perm.EDITORIAL_READ,
        Perm.EDITORIAL_REVIEW,
        Perm.AGENT_READ,
        Perm.AGENT_RUN,
        Perm.AGENT_CANCEL,
        Perm.EXPERIMENT_READ,
        Perm.INTEGRATION_READ,
        Perm.SETTINGS_READ,
        Perm.AUDIT_READ,
    },
    "editor": {
        Perm.DASHBOARD_READ,
        Perm.OPPORTUNITY_READ,
        Perm.OPPORTUNITY_REVIEW,
        Perm.EDITORIAL_READ,
        Perm.EDITORIAL_REVIEW,
        Perm.EDITORIAL_PUBLISH_CONFIRM,
        Perm.EXPERIMENT_READ,
        Perm.INTEGRATION_READ,
        Perm.SETTINGS_READ,
        Perm.AUDIT_READ,
    },
    "viewer": {
        Perm.DASHBOARD_READ,
        Perm.OPPORTUNITY_READ,
        Perm.TECHNICAL_READ,
        Perm.EDITORIAL_READ,
        Perm.AGENT_READ,
        Perm.EXPERIMENT_READ,
        Perm.INTEGRATION_READ,
        Perm.SETTINGS_READ,
        Perm.AUDIT_READ,
    },
}

# Deny by default: um usuário sem nenhuma role não tem nenhuma permissão.
ROLE_DESCRIPTIONS = {
    "admin": "controle total",
    "operator": "operações SEO e agentes",
    "editor": "editorial e oportunidades",
    "viewer": "somente leitura",
}


def all_permissions() -> set[str]:
    return set(_ALL_PERMISSIONS)


def permissions_for_role(role: str) -> set[str]:
    return set(ROLE_PERMISSIONS.get(role, set()))


def seed_rbac(conn: Any) -> None:
    """Popula permissions/roles/role_permissions de forma idempotente."""
    for name in sorted(_ALL_PERMISSIONS):
        conn.execute(
            "INSERT OR IGNORE INTO permissions (name) VALUES (?)", (name,)
        )
    for role_name in sorted(ROLE_PERMISSIONS):
        conn.execute(
            "INSERT OR IGNORE INTO roles (name, description) VALUES (?, ?)",
            (role_name, ROLE_DESCRIPTIONS.get(role_name, "")),
        )
    # mapeia role->permissions
    perm_ids = {
        row[0]: row[1]
        for row in conn.execute("SELECT name, id FROM permissions").fetchall()
    }
    role_ids = {
        row[0]: row[1]
        for row in conn.execute("SELECT name, id FROM roles").fetchall()
    }
    for role_name, perms in ROLE_PERMISSIONS.items():
        role_id = role_ids.get(role_name)
        if role_id is None:
            continue
        for p in perms:
            perm_id = perm_ids.get(p)
            if perm_id is not None:
                conn.execute(
                    "INSERT OR IGNORE INTO role_permissions (role_id, permission_id) "
                    "VALUES (?, ?)",
                    (role_id, perm_id),
                )
