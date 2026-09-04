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


def test_fastapi_action_rollback(tmp_path):
    import json as _json

    db = tmp_path / "rb.db"
    _prepare(db)
    storage = Storage(str(db))
    storage.conn.execute(
        "INSERT INTO actions (cycle_id, rule_id, url, level, status, fingerprint, before_json, "
        "after_json, rollback_json, executed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("c1", "title_manual", "https://x.com/b/", "safe_fix", "executed", "fp-rb",
         _json.dumps({"rank_math_title": "título antigo"}),
         _json.dumps({"rank_math_title": "título novo"}),
         _json.dumps({"type": "wp_post_meta", "post_id": 9,
                      "meta": {"rank_math_title": "título antigo"}}),
         "2026-01-01T00:00:00+00:00"))
    storage.conn.commit()
    storage.close()

    app = create_app(storage_path=str(db), config=_cfg())
    client = TestClient(app)
    client.post("/api/v1/auth/login", json={"email": "op@x.com", "password": PWD})
    csrf = client.get("/api/v1/auth/me").json()["csrf_token"]

    # preview GET exige a permissão safe_fix; com CSRF (o GET carrega CSRF pela factory)
    r = client.get("/api/v1/actions/fp-rb/rollback")
    assert r.status_code == 200 and r.json()["reversible"] is True

    # mutação rollback sem CSRF -> 403
    r = client.post("/api/v1/actions/fp-rb/rollback")
    assert r.status_code == 403 and r.json()["error"]["code"] == "CSRF_INVALID"

    # com CSRF -> 200, reverte e audita
    r = client.post("/api/v1/actions/fp-rb/rollback", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and r.json()["ok"] is True

    s = Storage(str(db))
    row = s.conn.execute(
        "SELECT status FROM actions WHERE fingerprint = 'fp-rb'").fetchone()
    assert row[0] == "reverted"
    audit = s.conn.execute(
        "SELECT action_type FROM audit_log WHERE entity = 'fp-rb' ORDER BY id DESC").fetchone()
    assert audit[0] == "SAFE_FIX_ROLLED_BACK"
    s.close()

    # reverter de novo -> 412 (não está mais executada)
    r = client.post("/api/v1/actions/fp-rb/rollback", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 412 and r.json()["error"]["code"] == "PRECONDITION_FAILED"

    # viewer sem safe_fix -> 403
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    client.post("/api/v1/auth/login", json={"email": "v@x.com", "password": PWD})
    vcsrf = client.get("/api/v1/auth/me").json()["csrf_token"]
    r = client.post("/api/v1/actions/fp-rb/rollback", headers={"X-CSRF-Token": vcsrf})
    assert r.status_code == 403 and r.json()["error"]["code"] == "PERMISSION_DENIED"


def test_fastapi_settings_mfa_login_toggle(tmp_path):
    from hermes_seo_agent.auth.passwords import PasswordHasher
    from hermes_seo_agent.auth.service import AuthService

    db = tmp_path / "set.db"
    storage = Storage(str(db))
    svc = AuthService(storage, config=_cfg(), hasher=PasswordHasher(n=2 ** 12))
    # admin (settings.manage) sem MFA + operador COM MFA + operador sem MFA
    svc.create_user("admin@x.com", "Admin", PWD, ["admin"])
    svc.create_user("opmfa@x.com", "O", PWD, ["operator"],
                    mfa_secret="5DGXU53YEWVAENWS53HV53APWPGGHMAW")
    svc.create_user("op@x.com", "Op", PWD, ["operator"])
    storage.close()

    app = create_app(storage_path=str(db), config=_cfg())

    # admin lê o gate: default OFF
    admin = TestClient(app)
    admin.post("/api/v1/auth/login", json={"email": "admin@x.com", "password": PWD})
    csrf = admin.get("/api/v1/auth/me").json()["csrf_token"]
    assert admin.get("/api/v1/settings/auth").json()["mfa_login_required"] is False

    # mutação sem CSRF -> 403
    r = admin.put("/api/v1/settings/auth/mfa-login", json={"enabled": True})
    assert r.status_code == 403 and r.json()["error"]["code"] == "CSRF_INVALID"
    # com CSRF -> liga
    r = admin.put("/api/v1/settings/auth/mfa-login", json={"enabled": True},
                  headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and r.json()["mfa_login_required"] is True

    # operador COM MFA, com gate ligado, passa a exigir o 2º fator
    opmfa = TestClient(app)
    r = opmfa.post("/api/v1/auth/login", json={"email": "opmfa@x.com", "password": PWD})
    assert r.status_code == 200 and r.json()["requires_mfa"] is True

    # operador SEM MFA não tem settings.manage -> 403 no PUT
    op = TestClient(app)
    op.post("/api/v1/auth/login", json={"email": "op@x.com", "password": PWD})
    ocsrf = op.get("/api/v1/auth/me").json()["csrf_token"]
    r = op.put("/api/v1/settings/auth/mfa-login", json={"enabled": False},
               headers={"X-CSRF-Token": ocsrf})
    assert r.status_code == 403 and r.json()["error"]["code"] == "PERMISSION_DENIED"

    # leitura reflete o estado persistido
    assert admin.get("/api/v1/settings/auth").json()["mfa_login_required"] is True


def test_findings_response_model_accepts_float_potential(tmp_path):
    """Regressão: seo_expectations usa colunas REAL (floats). O response_model de
    /findings deve aceitar floats (antes dava 500 por int_from_float)."""
    import datetime as _dt

    db = tmp_path / "find.db"
    _prepare(db)
    storage = Storage(str(db))
    storage.conn.execute(
        "INSERT INTO findings (cycle_id, rule_id, url, severity, detail_json, created_at) "
        "VALUES ('c1', 'title_manual', 'https://x.com/a/', 'medium', '{}', "
        "'2026-01-01T00:00:00+00:00')")
    storage.conn.execute(
        "INSERT INTO seo_expectations (url, computed_at, position, impressions, clicks, ctr, "
        "expected_ctr, expected_clicks, gap_clicks, conservative_clicks, realistic_clicks, "
        "optimistic_clicks) VALUES "
        "('https://www.unicorniohater.com.br/a/', '2026-01-01T00:00:00+00:00', 1.5, 100, 3, "
        "0.03, 0.05, 0.3, 0.3, 0.1, 0.2, 0.3)")
    storage.conn.commit()
    storage.close()

    app = create_app(storage_path=str(db), config=_cfg())
    client = TestClient(app)
    client.post("/api/v1/auth/login", json={"email": "op@x.com", "password": PWD})
    r = client.get("/api/v1/findings?limit=200&sort=potential")
    assert r.status_code == 200, r.text
    findings = r.json()["findings"]
    assert findings
    pot = findings[0]["potential"]
    for k in ("conservative", "realistic", "optimistic", "expected_clicks", "gap_clicks"):
        assert pot[k] is not None, f"{k} deveria vir do seo_expectations"


def test_activity_ref_is_string(tmp_path):
    """Regressão: /activity expõe ref como string (antes mandava int p/ run/event)."""
    import datetime as _dt

    class FakeClock:
        def __call__(self) -> _dt.datetime:
            return _dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc)

    from hermes_seo_agent.services.agent_runs import AgentRunService

    db = tmp_path / "act.db"
    _prepare(db)
    storage = Storage(str(db))
    runs = AgentRunService(storage, clock=FakeClock())
    rid = runs.start_run("hermes-seo-agent", trigger="manual", intent="technical",
                         mode="analyze", started_by="op@x.com")
    runs.complete(rid, status="success", urls=10, findings=1, opportunities=0,
                  safe_fixes=0, executed=0)
    storage.close()

    app = create_app(storage_path=str(db), config=_cfg())
    client = TestClient(app)
    client.post("/api/v1/auth/login", json={"email": "op@x.com", "password": PWD})
    r = client.get("/api/v1/activity?limit=200")
    assert r.status_code == 200, r.text
    runs_entries = [e for e in r.json()["activity"] if e["type"] == "agent_run"]
    assert runs_entries, "esperava ao menos um agent_run no activity"
    assert all(isinstance(e["ref"], str) for e in runs_entries)


def test_pages_history_uses_query_param_and_returns_200(tmp_path):
    """Regressão: /pages/history recebe a URL via query (a URL tem barras e não
    cabe num path param de segmento único — Starlette decodifica %2F)."""
    from urllib.parse import quote

    db = tmp_path / "pages.db"
    _prepare(db)
    storage = Storage(str(db))
    storage.conn.execute(
        "INSERT INTO page_snapshots (url, captured_at, source, status_code, title, meta_robots, "
        "canonical, word_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("https://www.unicorniohater.com.br/a/", "2026-01-01T00:00:00+00:00", "audit", 200,
         "A", "", "https://www.unicorniohater.com.br/a/", 900))
    storage.conn.commit()
    storage.close()

    app = create_app(storage_path=str(db), config=_cfg())
    client = TestClient(app)
    client.post("/api/v1/auth/login", json={"email": "op@x.com", "password": PWD})
    url = "https://www.unicorniohater.com.br/a/"
    r = client.get(f"/api/v1/pages/history?url={quote(url, safe='')}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"] == url
    assert body["history"] and body["history"][0]["title"] == "A"


def test_editorial_transition_migrated(tmp_path):
    """Regressão: a transição editorial (aprovar/rejeitar/publicar) foi migrada
    para o backend tipado como POST /editorial/{id}/{action}."""
    db = tmp_path / "ed.db"
    _prepare(db)
    storage = Storage(str(db))
    storage.conn.execute(
        "INSERT INTO editorial_backlog (pauta_type, title, status, created_at) "
        "VALUES ('post', 'Guia', 'proposed', '2026-01-01T00:00:00+00:00')")
    storage.conn.commit()
    storage.close()

    app = create_app(storage_path=str(db), config=_cfg())
    client = TestClient(app)
    client.post("/api/v1/auth/login", json={"email": "op@x.com", "password": PWD})
    csrf = client.get("/api/v1/auth/me").json()["csrf_token"]
    # aprovar
    r = client.post("/api/v1/editorial/backlog:1/approve", json={}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    s = Storage(str(db))
    row = s.conn.execute("SELECT status FROM editorial_backlog WHERE id=1").fetchone()
    assert row[0] == "approved"
    s.close()
    # ação inválida -> 400
    r = client.post("/api/v1/editorial/backlog:1/inexistente", json={}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 400


def test_run_refresh_data_sources_scope(tmp_path):
    """R2: POST /runs com intent refresh_data aceita escopo de fontes (ADR-0010)."""
    db = tmp_path / "rf.db"
    _prepare(db)
    app = create_app(storage_path=str(db), config=_cfg())
    client = TestClient(app)
    client.post("/api/v1/auth/login", json={"email": "op@x.com", "password": PWD})
    csrf = client.get("/api/v1/auth/me").json()["csrf_token"]

    # parcial
    r = client.post("/api/v1/runs", json={"intent": "refresh_data", "mode": "analyze",
                                          "sources": ["gsc", "ga4"]},
                    headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and r.json()["sources"] == ["gsc", "ga4"]
    # fonte inválida -> 400
    r = client.post("/api/v1/runs", json={"intent": "refresh_data", "sources": ["x"]},
                    headers={"X-CSRF-Token": csrf})
    assert r.status_code == 400

    # "todas as fontes" (sem sources) — DB separado para não colidir com o dedupe (R16)
    db2 = tmp_path / "rf2.db"
    _prepare(db2)
    app2 = create_app(storage_path=str(db2), config=_cfg())
    client2 = TestClient(app2)
    client2.post("/api/v1/auth/login", json={"email": "op@x.com", "password": PWD})
    csrf2 = client2.get("/api/v1/auth/me").json()["csrf_token"]
    r = client2.post("/api/v1/runs", json={"intent": "refresh_data"},
                     headers={"X-CSRF-Token": csrf2})
    assert r.status_code == 200
    assert r.json()["sources"] == ["wordpress", "sitemap", "gsc", "ga4", "crux", "corpus"]


def test_refresh_data_dedupe_returns_active_run(tmp_path):
    """R16: um segundo refresh_data enquanto há um ativo devolve o run existente."""
    db = tmp_path / "dedupe.db"
    _prepare(db)
    app = create_app(storage_path=str(db), config=_cfg())
    client = TestClient(app)
    client.post("/api/v1/auth/login", json={"email": "op@x.com", "password": PWD})
    csrf = client.get("/api/v1/auth/me").json()["csrf_token"]

    r1 = client.post("/api/v1/runs", json={"intent": "refresh_data", "sources": ["gsc"]},
                     headers={"X-CSRF-Token": csrf})
    assert r1.status_code == 200 and r1.json()["status"] == "queued"
    first_id = r1.json()["id"]
    r2 = client.post("/api/v1/runs", json={"intent": "refresh_data", "sources": ["ga4"]},
                     headers={"X-CSRF-Token": csrf})
    assert r2.status_code == 200
    assert r2.json()["id"] == first_id          # devolve o run ativo, não duplica


def test_integrations_live_requires_manage_permission(tmp_path):
    """R15: visualizar fontes = integration.read; verificar (live) = integration.manage."""
    db = tmp_path / "int.db"
    _prepare(db)
    app = create_app(storage_path=str(db), config=_cfg())
    client = TestClient(app)
    client.post("/api/v1/auth/login", json={"email": "op@x.com", "password": PWD})
    # operator tem integration.read mas NÃO integration.manage
    assert client.get("/api/v1/integrations").status_code == 200
    r = client.get("/api/v1/integrations?live=true")
    assert r.status_code == 403 and r.json()["error"]["code"] == "PERMISSION_DENIED"
