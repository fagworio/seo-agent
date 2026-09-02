"""ASGI adapter: FastAPI must preserve Router security semantics."""
from types import SimpleNamespace

import httpx
import pytest

from hermes_seo_agent.api.fastapi_app import create_app
from hermes_seo_agent.auth.passwords import PasswordHasher
from hermes_seo_agent.auth.service import AuthService
from hermes_seo_agent.storage.db import Storage


def _config(path):
    return SimpleNamespace(
        sqlite_path=str(path), session_idle_seconds=8 * 3600,
        session_absolute_seconds=7 * 24 * 3600, auth_max_attempts=5,
        auth_attempt_window_seconds=900, reauth_window_seconds=900,
        reset_token_seconds=3600, mfa_issuer="SEO Agent",
        session_cookie_name="__Host-seo_session", session_cookie_secure=False,
        csrf_header="X-CSRF-Token", wordpress_url="", sitemap_url="",
        google_credentials="", ga4_property_id="", crux_api_key="",
        pagespeed_api_key="", static_site_url="https://example.com",
        trends_mode="scrape", trends_api_key="", dry_run=True,
    )


@pytest.mark.asyncio
async def test_fastapi_openapi_and_authenticated_router_flow(tmp_path):
    cfg = _config(tmp_path / "api.db")
    with Storage(cfg.sqlite_path) as storage:
        AuthService(storage, config=cfg, hasher=PasswordHasher(n=2 ** 12)).create_user(
            "viewer@example.com", "Viewer", "senha-bem-longa-12345", ["viewer"])
    app = create_app(cfg.sqlite_path, cfg)
    assert app.openapi()["info"]["title"] == "SEO Agent Control Plane"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/docs")).status_code == 200
        assert (await client.get("/api/v1/openapi.json")).status_code == 200
        assert (await client.get("/api/v1/health")).json() == {"status": "ok"}
        login = await client.post("/api/v1/auth/login", json={"email": "viewer@example.com", "password": "senha-bem-longa-12345"})
        assert login.status_code == 200 and login.json()["ok"] is True
        me = await client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert (await client.get("/api/v1/dashboard/today")).status_code == 200
        assert (await client.post("/api/v1/auth/logout")).status_code == 403
        csrf = me.json()["csrf_token"]
        assert (await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})).status_code == 200
