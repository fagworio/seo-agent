"""Testes da aplicação FastAPI (/api/v1) via TestClient."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from hermes_seo_agent.api.app import create_app
from hermes_seo_agent.auth.passwords import PasswordHasher
from hermes_seo_agent.auth.service import AuthService
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
    svc.create_user("v@x.com", "V", PWD, ["viewer"])
    svc.create_user("op@x.com", "O", PWD, ["operator"])
    svc.create_user("norole@x.com", "N", PWD, [])
    storage.close()


def test_fastapi_login_me_and_openapi(tmp_path):
    db = tmp_path / "api.db"
    _prepare(db)
    app = create_app(storage_path=str(db), config=_cfg())
    client = TestClient(app)

    # login (viewer, sem MFA) -> cookie + csrf
    r = client.post("/api/v1/auth/login", json={"email": "v@x.com", "password": PWD})
    assert r.status_code == 200 and r.json()["ok"] is True
    csrf = r.json()["csrf_token"]
    assert "seo_session" in r.headers.get("set-cookie", "")   # dev: sem __Host-

    # /me com a sessão (cookie já presente no TestClient)
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "v@x.com"

    # /dashboard/today (viewer tem dashboard.read) — read model tipado (envelope)
    r = client.get("/api/v1/dashboard/today?limit=1")
    assert r.status_code == 200
    assert "today" in r.json() and "needs_attention" in r.json()["today"]

    # /agents (sem roles -> deny-by-default -> 403)
    client.get("/api/v1/auth/logout")   # encerra a sessão do viewer
    r = client.post("/api/v1/auth/login", json={"email": "norole@x.com", "password": PWD})
    assert r.status_code == 200 and r.json()["ok"] is True
    r = client.get("/api/v1/agents")
    assert r.status_code == 403 and r.json()["error"]["code"] == "PERMISSION_DENIED"

    # OpenAPI: operationIds únicos presentes (em /api/v1/openapi.json)
    openapi = client.get("/api/v1/openapi.json").json()
    paths = openapi["paths"]
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/dashboard/today" in paths
    ops = [op for p in paths.values() for op in p.values() if "operationId" in op]
    ids = [op["operationId"] for op in ops]
    assert len(ids) == len(set(ids))          # operation IDs únicos
    assert "auth_login" in ids and "dashboard_today" in ids


def test_fastapi_csrf_and_permission_on_mutation(tmp_path):
    db = tmp_path / "api2.db"
    _prepare(db)
    app = create_app(storage_path=str(db), config=_cfg())
    client = TestClient(app)

    r = client.post("/api/v1/auth/login", json={"email": "op@x.com", "password": PWD})
    csrf = r.json()["csrf_token"]

    # mutação sem CSRF -> 403 CSRF_INVALID
    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 403 and r.json()["error"]["code"] == "CSRF_INVALID"
    # com CSRF -> 200
    r = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200

    # sem sessão (logout apagou o cookie) -> /me 401
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_fastapi_editorial_and_run_mutations(tmp_path):
    db = tmp_path / "api3.db"
    _prepare(db)
    app = create_app(storage_path=str(db), config=_cfg())
    client = TestClient(app)
    client.post("/api/v1/auth/login", json={"email": "op@x.com", "password": PWD})
    csrf = client.get("/api/v1/auth/me").json()["csrf_token"]

    # /editorial (operator tem editorial.review)
    r = client.get("/api/v1/editorial")
    assert r.status_code == 200 and "editorial" in r.json()

    # POST /runs com target_url (escopo por URL) — exige CSRF
    r = client.post("/api/v1/runs", json={"intent": "url", "target_url": "https://www.unicorniohater.com.br/xbox-disc-to-digital/"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "CSRF_INVALID"
    r = client.post("/api/v1/runs", json={"intent": "url", "target_url": "https://www.unicorniohater.com.br/xbox-disc-to-digital/"},
                    headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and r.json()["target_url"] == "https://www.unicorniohater.com.br/xbox-disc-to-digital/"
    run_id = r.json()["id"]

    # POST /runs/{id}/cancel
    r = client.post(f"/api/v1/runs/{run_id}/cancel", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
