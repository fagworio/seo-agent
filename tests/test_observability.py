"""Observabilidade/confiabilidade: security headers, backup/restore e migração SQLite."""
import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient

from hermes_seo_agent.api.app import create_app
from hermes_seo_agent.storage.db import Storage


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


def test_security_headers_on_response(tmp_path):
    app = create_app(storage_path=str(tmp_path / "h.db"), config=_cfg())
    client = TestClient(app)
    r = client.get("/api/v1/auth/me")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert "frame-ancestors 'none'" in r.headers.get("content-security-policy", "")
    assert "x-request-id" in r.headers


def test_backup_restore_sqlite(tmp_path):
    db = tmp_path / "a.db"
    with Storage(str(db)) as s:
        s.conn.execute("INSERT INTO users (email, name, created_at, updated_at) "
                       "VALUES ('b@x.com', 'B', '2026-01-01', '2026-01-01')")
        s.conn.commit()
    # backup online (API do SQLite) para um arquivo novo
    dest = tmp_path / "backup.db"
    src = sqlite3.connect(str(db))
    dst = sqlite3.connect(str(dest))
    src.backup(dst)
    src.close(); dst.close()
    # restauração: abrir o backup e verificar os dados
    with Storage(str(dest)) as s2:
        row = s2.conn.execute("SELECT email FROM users WHERE email = 'b@x.com'").fetchone()
        assert row is not None and row[0] == "b@x.com"


def test_migration_adds_target_url_to_agent_runs(tmp_path):
    db = tmp_path / "old.db"
    # cria um banco "antigo": agent_runs SEM a coluna target_url
    c = sqlite3.connect(str(db))
    c.executescript(
        "CREATE TABLE agent_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id INTEGER, status TEXT);"
    )
    c.commit(); c.close()
    with Storage(str(db)) as s:
        cols = [r[1] for r in s.conn.execute("PRAGMA table_info(agent_runs)").fetchall()]
        assert "target_url" in cols   # migração adicionou a coluna
