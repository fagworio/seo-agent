"""RBAC: seed idempotente + resolução role→permissões."""
from hermes_seo_agent.auth.permissions import (
    ROLE_PERMISSIONS,
    all_permissions,
    permissions_for_role,
    seed_rbac,
)
from hermes_seo_agent.storage.db import Storage


def test_all_roles_are_subset_of_all_permissions():
    allp = all_permissions()
    for role, perms in ROLE_PERMISSIONS.items():
        assert perms <= allp


def test_viewer_cannot_write():
    perms = permissions_for_role("viewer")
    assert "technical.safe_fix" not in perms
    assert "opportunity.review" not in perms
    assert "dashboard.read" in perms


def test_admin_has_everything():
    assert permissions_for_role("admin") == all_permissions()


def test_seed_rbac_is_idempotent(tmp_path):
    db = tmp_path / "rbac.db"
    with Storage(str(db)) as storage:
        # roda duas vezes não deve quebrar nem duplicar
        seed_rbac(storage.conn)
        seed_rbac(storage.conn)
        storage.conn.commit()

        roles = {r[0] for r in storage.conn.execute("SELECT name FROM roles")}
        perms = {r[0] for r in storage.conn.execute("SELECT name FROM permissions")}
        role_perms = storage.conn.execute(
            "SELECT COUNT(*) FROM role_permissions"
        ).fetchone()[0]

        assert roles == set(ROLE_PERMISSIONS)
        assert perms == all_permissions()
        expected_mapping = sum(len(v) for v in ROLE_PERMISSIONS.values())
        assert role_perms == expected_mapping
