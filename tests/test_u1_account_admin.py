"""Fase U1 — Account self-service + administração de usuários (guards + audit)."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from hermes_seo_agent.api.app import create_app
from hermes_seo_agent.auth.passwords import PasswordHasher
from hermes_seo_agent.auth.service import AuthService
from hermes_seo_agent.auth.totp import TOTP
from hermes_seo_agent.storage.db import Storage

PWD = "senha-bem-longa-12345"


def _cfg():
    return SimpleNamespace(
        session_idle_seconds=8 * 3600, session_absolute_seconds=7 * 24 * 3600,
        auth_max_attempts=5, auth_attempt_window_seconds=900,
        reauth_window_seconds=900, reset_token_seconds=3600, mfa_issuer="SEO Agent",
        session_cookie_name="__Host-seo_session", session_cookie_secure=False,
        csrf_header="X-CSRF-Token", static_site_url="https://www.unicorniohater.com.br",
        wordpress_public_url="https://prod.unicorniohater.com.br",
        wordpress_url="http://wordpress.dvl.to:8080", sitemap_url="",
        google_credentials="", ga4_property_id="", crux_api_key="", pagespeed_api_key="",
        trends_mode="scrape", trends_api_key="", dry_run=True,
    )


def _prepare(db):
    storage = Storage(str(db))
    svc = AuthService(storage, config=_cfg(), hasher=PasswordHasher(n=2 ** 12))
    admin = svc.create_admin("admin@x.com", "Admin", "senha123")
    svc.create_user("op@x.com", "Operador", PWD, ["operator"])
    svc.create_user("viewer@x.com", "Leitor", PWD, ["viewer"])
    storage.close()
    return admin


def _login(client, email, password, db, use_csrf=True):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200 and r.json()["ok"] is True
    if r.json().get("requires_mfa"):
        with Storage(str(db)) as s:
            factor = AuthService(s, config=_cfg(), hasher=PasswordHasher(n=2 ** 12)).store.get_mfa_factor(r.json()["mfa_user_id"])
        code = TOTP(factor["secret"]).now()
        r = client.post("/api/v1/auth/mfa/verify",
                        json={"user_id": r.json()["mfa_user_id"], "code": code})
        assert r.status_code == 200 and r.json()["ok"] is True
    if use_csrf:
        return client.get("/api/v1/auth/me").json()["csrf_token"]
    return None


def test_account_profile_and_update(tmp_path):
    db = tmp_path / "u1a.db"
    _prepare(db)
    app = create_app(storage_path=str(db), config=_cfg())
    client = TestClient(app)
    csrf = _login(client, "admin@x.com", "senha123", db)

    acc = client.get("/api/v1/account").json()
    assert acc["email"] == "admin@x.com" and "admin" in acc["roles"]

    r = client.patch("/api/v1/account", json={"name": "Admin Novo"}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    assert client.get("/api/v1/account").json()["name"] == "Admin Novo"


def test_change_password_wrong_current_fails(tmp_path):
    db = tmp_path / "u1b.db"
    _prepare(db)
    client = TestClient(create_app(storage_path=str(db), config=_cfg()))
    csrf = _login(client, "op@x.com", PWD, db)
    r = client.post("/api/v1/account/change-password",
                    json={"current_password": "errada", "new_password": "nova-senha-longa-123"},
                    headers={"X-CSRF-Token": csrf})
    assert r.json()["ok"] is False
    r = client.post("/api/v1/account/change-password",
                    json={"current_password": PWD, "new_password": "nova-senha-longa-123"},
                    headers={"X-CSRF-Token": csrf})
    assert r.json()["ok"] is True


def test_mfa_setup_confirm_disable(tmp_path):
    db = tmp_path / "u1c.db"
    _prepare(db)
    client = TestClient(create_app(storage_path=str(db), config=_cfg()))
    csrf = _login(client, "op@x.com", PWD, db)
    secret = client.post("/api/v1/account/mfa/setup").json()["secret"]
    code = TOTP(secret).now()
    assert client.post("/api/v1/account/mfa/confirm", json={"code": code},
                       headers={"X-CSRF-Token": csrf}).json()["ok"] is True
    assert client.get("/api/v1/account").json()["is_mfa_enabled"] is True
    # disable exige reautenticação forte (recém-logado -> passa nesta janela)
    r = client.post("/api/v1/account/mfa/disable", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    assert client.get("/api/v1/account").json()["is_mfa_enabled"] is False


def test_admin_users_permissions_and_guards(tmp_path):
    db = tmp_path / "u1d.db"
    _prepare(db)
    client = TestClient(create_app(storage_path=str(db), config=_cfg()))

    # viewer NÃO pode listar usuários -> 403
    _login(client, "viewer@x.com", PWD, db)
    assert client.get("/api/v1/users").status_code == 403

    # admin lista e cria
    csrf = _login(client, "admin@x.com", "senha123", db)
    users = client.get("/api/v1/users").json()
    assert len(users) >= 3
    created = client.post("/api/v1/users", json={"email": "maria@x.com", "name": "Maria",
                                                 "password": "senha-bem-longa-12345",
                                                 "roles": ["editor"], "require_password_change": True},
                          headers={"X-CSRF-Token": csrf})
    assert created.status_code == 200 and created.json()["email"] == "maria@x.com"
    maria_id = created.json()["id"]

    roles = client.get("/api/v1/roles").json()["roles"]
    assert any(r["name"] == "editor" for r in roles)
    perms = client.get("/api/v1/permissions").json()["permissions"]
    assert any(p["name"] == "users.manage" for p in perms)

    # Atividade do usuário
    act = client.get(f"/api/v1/users/{maria_id}/activity").json()
    assert any(e["event"] == "USER_CREATED" for e in act)


def test_admin_cannot_disable_self_or_last_admin(tmp_path):
    db = tmp_path / "u1e.db"
    _prepare(db)
    client = TestClient(create_app(storage_path=str(db), config=_cfg()))
    _login(client, "admin@x.com", "senha123", db)
    csrf = client.get("/api/v1/auth/me").json()["csrf_token"]
    admin_id = client.get("/api/v1/account").json()["id"]
    # desativar a própria conta -> 400
    r = client.post(f"/api/v1/users/{admin_id}/disable", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 400
    # remover a própria admin (único admin) -> 400
    r = client.put(f"/api/v1/users/{admin_id}/roles", json={"roles": ["editor"]},
                   headers={"X-CSRF-Token": csrf})
    assert r.status_code == 400
