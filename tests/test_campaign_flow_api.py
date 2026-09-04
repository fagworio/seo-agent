"""Fluxo completo de campanha via contrato HTTP real (FastAPI + auth + CSRF).

Cobre: Caixa exibe decisão pendente -> resolve por work_item_id -> criar campanha
(persiste work_item_id + lifecycle delegated) -> item sai da Caixa -> aprovar
checklist -> approved (não done). Verificação ponta a ponta do lifecycle.
"""
import json
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
    svc.create_user("op@x.com", "Op", PWD, ["operator"])
    # semear um item de decisão pendente + ação safe_fix pendente vinculada
    storage.conn.execute(
        "INSERT INTO improvement_checklist (url, item, action, reason, status, created_at) "
        "VALUES ('https://x.com/titulo/', 'title_meta', 'Reescrever título (set-title)', "
        "'CTR baixo', 'pending', '2026-02-01')")
    cid = storage.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    storage.conn.execute(
        "INSERT INTO actions (cycle_id, rule_id, url, level, status, fingerprint, "
        "before_json, after_json, rollback_json, fix_json, work_item_id) "
        "VALUES ('c1', 'title_manual', 'https://x.com/titulo/', 'safe_fix', 'pending', "
        "'fp-1', ?, ?, ?, ?, ?)",
        (json.dumps({"rank_math_title": "velho"}),
         json.dumps({"rank_math_title": "novo"}),
         json.dumps({"type": "wp_post_meta", "post_id": 7, "meta": {"rank_math_title": "velho"}}),
         json.dumps({"type": "wp_post_meta", "post_id": 7, "meta": {"rank_math_title": "novo"}}),
         f"checklist:{cid}"))
    storage.conn.commit()
    return storage, cid


def test_full_campaign_flow_end_to_end(tmp_path):
    storage, cid = _prepare(tmp_path / "flow.db")
    app = create_app(storage_path=str(tmp_path / "flow.db"), config=_cfg())
    client = TestClient(app)

    r = client.post("/api/v1/auth/login", json={"email": "op@x.com", "password": PWD})
    assert r.status_code == 200 and r.json()["ok"] is True
    csrf = r.json()["csrf_token"]

    # 1) Caixa mostra a decisão pendente (lifecycle new)
    r = client.get("/api/v1/work-items?source=checklist")
    assert r.status_code == 200
    payload = r.json()["work_items"]
    item = next((i for i in payload if i["id"] == f"checklist:{cid}"), None)
    assert item is not None, "item pendente deve aparecer na Caixa"
    assert item["lifecycle"] == "new"

    # 2) resolve por work_item_id
    r = client.post("/api/v1/campaigns/resolve", json={
        "items": [{"work_item_id": f"checklist:{cid}", "url": "https://x.com/titulo/"}],
    }, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    resolved = r.json()["items"][0]
    assert resolved["state"] == "eligible" and resolved["fingerprint"] == "fp-1"

    # 3) criar campanha (persiste work_item_id + lifecycle delegated)
    r = client.post("/api/v1/campaigns", json={
        "name": "Títulos", "action_type": "title_manual",
        "fingerprints": ["fp-1"], "work_item_ids": {"fp-1": f"checklist:{cid}"},
        "execution_mode": "delegated", "max_actions_per_run": 10,
    }, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    camp = r.json()
    assert camp["items"][0]["work_item_id"] == f"checklist:{cid}"
    lc = storage.get_work_item_lifecycle(f"checklist:{cid}")
    assert lc is not None and lc["status"] == "delegated"
    assert lc["campaign_id"] == camp["id"]

    # 4) item SAIU da Caixa (lifecycle delegated é excluído da fila de decisão)
    r = client.get("/api/v1/work-items?source=checklist")
    assert all(i["id"] != f"checklist:{cid}" for i in r.json()["work_items"])

    storage.close()


def test_approve_checklist_sets_approved_not_done_via_http(tmp_path):
    storage, cid = _prepare(tmp_path / "flow2.db")
    app = create_app(storage_path=str(tmp_path / "flow2.db"), config=_cfg())
    client = TestClient(app)
    r = client.post("/api/v1/auth/login", json={"email": "op@x.com", "password": PWD})
    csrf = r.json()["csrf_token"]

    r = client.post(f"/api/v1/work-items/checklist:{cid}/approve", json={},
                    headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    row = storage.conn.execute(
        "SELECT status FROM improvement_checklist WHERE id = ?", (cid,)).fetchone()
    assert row[0] == "approved", f"esperava approved, veio {row[0]}"
    lc = storage.get_work_item_lifecycle(f"checklist:{cid}")
    assert lc is not None and lc["status"] == "approved"
    # saiu da Caixa
    r = client.get("/api/v1/work-items?source=checklist")
    assert all(i["id"] != f"checklist:{cid}" for i in r.json()["work_items"])
    storage.close()
