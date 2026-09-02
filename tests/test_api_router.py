"""Router /api/v1: auth por cookie, CSRF, RBAC, rate limiting (sem socket)."""
import json
from types import SimpleNamespace

from hermes_seo_agent.api.http import HttpRequest
from hermes_seo_agent.api.router import Router
from hermes_seo_agent.auth.passwords import PasswordHasher
from hermes_seo_agent.storage.db import Storage

PWD = "senha-bem-longa-12345"


def _cfg():
    return SimpleNamespace(
        session_idle_seconds=8 * 3600, session_absolute_seconds=7 * 24 * 3600,
        auth_max_attempts=5, auth_attempt_window_seconds=900,
        reauth_window_seconds=900, reset_token_seconds=3600, mfa_issuer="SEO Agent",
        session_cookie_name="__Host-seo_session", session_cookie_secure=True,
        csrf_header="X-CSRF-Token", wordpress_url="", sitemap_url="",
        google_credentials="", ga4_property_id="", crux_api_key="",
        pagespeed_api_key="", static_site_url="https://example.com",
        trends_mode="scrape", trends_api_key="",
    )


def _router(db, **kw):
    storage = Storage(str(db))
    r = Router(storage, _cfg(), hasher=PasswordHasher(n=2 ** 12), **kw)
    return storage, r


def _req(method, path, *, body=None, cookie=None, csrf=None, ip="1.1.1.1", query=""):
    if "?" in path and not query:
        path, query = path.split("?", 1)
    headers = {"content-type": "application/json"}
    if cookie:
        headers["cookie"] = cookie
    if csrf:
        headers["x-csrf-token"] = csrf
    raw = json.dumps(body).encode() if body is not None else None
    return HttpRequest(method, path, query=_parse_query(query), headers=headers,
                       body=raw, client_ip=ip)


def _parse_query(qs):
    from urllib.parse import parse_qsl
    return dict(parse_qsl(qs))


def _login(router, email, password, ip="1.1.1.1"):
    resp = router.handle(_req("POST", "/api/v1/auth/login",
                              body={"email": email, "password": password}, ip=ip))
    token = None
    if resp.set_cookie:
        token = resp.set_cookie["header"].split(";")[0].partition("=")[2]
    return resp, token


def test_login_sets_cookie_and_returns_csrf(tmp_path):
    storage, r = _router(tmp_path / "l.db")
    r.auth.create_user("v@x.com", "V", PWD, ["viewer"])
    resp, token = _login(r, "v@x.com", PWD)
    assert resp.status == 200 and resp.body["ok"] is True
    assert token
    assert "HttpOnly" in resp.set_cookie["header"]
    assert "__Host-seo_session" in resp.set_cookie["header"]
    assert resp.body["csrf_token"]
    storage.close()


def test_login_invalid_is_generic(tmp_path):
    storage, r = _router(tmp_path / "i.db")
    r.auth.create_user("v@x.com", "V", PWD, ["viewer"])
    resp, _ = _login(r, "v@x.com", "senha-errada")
    assert resp.status == 200 and resp.body["ok"] is False
    assert resp.body["message"] == "Email ou senha inválidos."
    storage.close()


def test_me_requires_session(tmp_path):
    storage, r = _router(tmp_path / "m.db")
    r.auth.create_user("v@x.com", "V", PWD, ["viewer"])
    # sem cookie -> 401
    anon = r.handle(_req("GET", "/api/v1/auth/me"))
    assert anon.status == 401 and anon.body["error"]["code"] == "UNAUTHENTICATED"
    # com cookie -> user + csrf
    _, token = _login(r, "v@x.com", PWD)
    me = r.handle(_req("GET", "/api/v1/auth/me", cookie=f"__Host-seo_session={token}"))
    assert me.status == 200
    assert me.body["user"]["email"] == "v@x.com"
    assert me.body["csrf_token"]
    storage.close()


def test_permission_denied_deny_by_default(tmp_path):
    storage, r = _router(tmp_path / "p.db")
    # usuário sem nenhuma role -> deny-by-default -> sem permissão
    r.auth.create_user("norole@x.com", "N", PWD, [])
    _, token = _login(r, "norole@x.com", PWD)
    cookie = f"__Host-seo_session={token}"
    today = r.handle(_req("GET", "/api/v1/dashboard/today?limit=1", cookie=cookie))
    assert today.status == 403 and today.body["error"]["code"] == "PERMISSION_DENIED"
    # viewer tem dashboard.read -> 200
    r.auth.create_user("v@x.com", "V", PWD, ["viewer"])
    _, vtok = _login(r, "v@x.com", PWD)
    vok = r.handle(_req("GET", "/api/v1/dashboard/today?limit=1",
                        cookie=f"__Host-seo_session={vtok}"))
    assert vok.status == 200
    storage.close()


def test_csrf_required_for_mutation(tmp_path):
    storage, r = _router(tmp_path / "c.db")
    r.auth.create_user("v@x.com", "V", PWD, ["viewer"])
    _, token = _login(r, "v@x.com", PWD)
    cookie = f"__Host-seo_session={token}"
    # sem CSRF -> 403
    no_csrf = r.handle(_req("POST", "/api/v1/auth/logout", body={}, cookie=cookie))
    assert no_csrf.status == 403 and no_csrf.body["error"]["code"] == "CSRF_INVALID"
    # com CSRF (obtido em /me) -> 200
    me = r.handle(_req("GET", "/api/v1/auth/me", cookie=cookie))
    csrf = me.body["csrf_token"]
    ok = r.handle(_req("POST", "/api/v1/auth/logout", body={}, cookie=cookie, csrf=csrf))
    assert ok.status == 200
    storage.close()


def test_rate_limit_login(tmp_path):
    storage, r = _router(tmp_path / "r.db")
    r.auth.create_user("v@x.com", "V", PWD, ["viewer"])
    resp = None
    for i in range(5):
        resp = _login(r, "v@x.com", "senha-errada", ip="9.9.9.9")[0]
    # 6ª tentativa -> limite por IP
    resp = _login(r, "v@x.com", "senha-errada", ip="9.9.9.9")[0]
    assert resp.status == 429 and resp.body["error"]["code"] == "RATE_LIMITED"
    storage.close()


def test_unknown_route_404(tmp_path):
    storage, r = _router(tmp_path / "u.db")
    assert r.handle(_req("GET", "/api/v1/nao-existe")).status == 404
    storage.close()


def test_cookie_name_respects_security_mode():
    from hermes_seo_agent.api.http import session_cookie_name
    prod = SimpleNamespace(session_cookie_name="__Host-seo_session", session_cookie_secure=True)
    dev = SimpleNamespace(session_cookie_name="__Host-seo_session", session_cookie_secure=False)
    assert session_cookie_name(prod) == "__Host-seo_session"
    assert session_cookie_name(dev) == "seo_session"


def test_logout_delete_header_consistent_with_security_mode(tmp_path):
    # secure=False -> nome sem prefixo E header de deleção SEM Secure
    cfg = _cfg()
    cfg.session_cookie_secure = False
    storage = Storage(str(tmp_path / "lo.db"))
    r = Router(storage, cfg, hasher=PasswordHasher(n=2 ** 12))
    r.auth.create_user("v@x.com", "V", PWD, ["viewer"])
    _, tok = _login(r, "v@x.com", PWD)
    cookie = f"seo_session={tok}"   # dev: nome sem __Host-
    csrf = r.handle(_req("GET", "/api/v1/auth/me", cookie=cookie)).body["csrf_token"]
    resp = r.handle(_req("POST", "/api/v1/auth/logout", body={}, cookie=cookie, csrf=csrf))
    assert resp.status == 200
    header = resp.set_cookie["header"]
    assert header.startswith("seo_session=")
    assert "Max-Age=0" in header
    assert "Secure" not in header        # dev HTTP não deve exigir Secure

    # secure=True -> header de deleção INCLUI Secure
    storage2 = Storage(str(tmp_path / "lo2.db"))
    r2 = Router(storage2, _cfg(), hasher=PasswordHasher(n=2 ** 12))
    r2.auth.create_user("v@x.com", "V", PWD, ["viewer"])
    _, tok2 = _login(r2, "v@x.com", PWD)
    c2 = f"__Host-seo_session={tok2}"
    csrf2 = r2.handle(_req("GET", "/api/v1/auth/me", cookie=c2)).body["csrf_token"]
    resp2 = r2.handle(_req("POST", "/api/v1/auth/logout", body={}, cookie=c2, csrf=csrf2))
    assert "Secure" in resp2.set_cookie["header"]
    storage.close()
    storage2.close()


def test_work_item_decision_requires_review_perm_and_csrf(tmp_path):
    storage, r = _router(tmp_path / "w.db")
    storage.conn.execute(
        "INSERT INTO improvement_checklist (url, item, action, status, created_at) "
        "VALUES ('https://x.com', 'title', 'melhorar', 'pending', '2026-01-01T00:00:00+00:00')")
    storage.conn.commit()

    # editor tem opportunity.review -> aprova (com CSRF)
    r.auth.create_user("edit@x.com", "E", PWD, ["editor"])
    _, tok = _login(r, "edit@x.com", PWD)
    cookie = f"__Host-seo_session={tok}"
    csrf = r.handle(_req("GET", "/api/v1/auth/me", cookie=cookie)).body["csrf_token"]
    ok = r.handle(_req("POST", "/api/v1/work-items/checklist:1/approve", body={},
                       cookie=cookie, csrf=csrf))
    assert ok.status == 200 and ok.body["ok"] is True

    # viewer não tem opportunity.review -> 403 (deny-by-default, antes do CSRF)
    r.auth.create_user("v@x.com", "V", PWD, ["viewer"])
    _, vtok = _login(r, "v@x.com", PWD)
    forbidden = r.handle(_req("POST", "/api/v1/work-items/checklist:1/approve",
                              body={}, cookie=f"__Host-seo_session={vtok}"))
    assert forbidden.status == 403 and forbidden.body["error"]["code"] == "PERMISSION_DENIED"
    storage.close()


def test_action_execute_requires_safe_fix_perm_and_reauth(tmp_path):
    import json as _json
    from datetime import datetime, timezone

    class FakeClock:
        def __init__(self): self.ts = 1_700_000_000
        def __call__(self): return datetime.fromtimestamp(self.ts, tz=timezone.utc)
        def advance(self, s): self.ts += s

    clock = FakeClock()
    storage, r = _router(tmp_path / "act.db", clock=clock)
    storage.conn.execute(
        "INSERT INTO actions (cycle_id, rule_id, url, level, status, fingerprint, before_json, "
        "after_json, rollback_json, executed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("c1", "title", "https://x.com/a/", "safe_fix", "pending", "fp1",
         _json.dumps({"title": "velho"}), _json.dumps({"title": "novo"}),
         _json.dumps({"type": "wp_post_meta"}), None))
    storage.conn.commit()

    # operator tem technical.safe_fix
    r.auth.create_user("op@x.com", "O", PWD, ["operator"])
    _, tok = _login(r, "op@x.com", PWD)
    cookie = f"__Host-seo_session={tok}"
    csrf = r.handle(_req("GET", "/api/v1/auth/me", cookie=cookie)).body["csrf_token"]
    # reauth recente (login recém-feito) -> 200
    ok = r.handle(_req("POST", "/api/v1/actions/fp1/execute", body={}, cookie=cookie, csrf=csrf))
    assert ok.status == 200 and ok.body["approved"] is True
    # reauth expirada -> 403 REAUTH_REQUIRED
    clock.advance(901)
    stale = r.handle(_req("POST", "/api/v1/actions/fp1/execute", body={}, cookie=cookie, csrf=csrf))
    assert stale.status == 403 and stale.body["error"]["code"] == "REAUTH_REQUIRED"
    storage.close()
