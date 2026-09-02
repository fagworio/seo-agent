"""ControlPlaneService: read models Today / Work / Integrations / Activity."""
import datetime
from types import SimpleNamespace

from hermes_seo_agent.services.agent_runs import AgentRunService
from hermes_seo_agent.services.control_plane import ControlPlaneService
from hermes_seo_agent.storage.db import Storage


class FakeClock:
    def __init__(self, ts: int = 1_700_000_000):
        self.ts = ts

    def __call__(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(self.ts, tz=datetime.timezone.utc)


def _config():
    return SimpleNamespace(
        wordpress_url="", sitemap_url="", google_credentials="",
        ga4_property_id="", crux_api_key="", pagespeed_api_key="",
        static_site_url="https://example.com", trends_mode="scrape", trends_api_key="",
    )


def _seed(db):
    storage = Storage(str(db))
    cp = ControlPlaneService(storage, _config())
    # uma oportunidade de checklist (score alto)
    storage.conn.execute(
        "INSERT INTO improvement_checklist (url, item, action, reason, status, "
        "created_at, explainable_score) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("https://x.com/a/", "title", "melhorar title", "CTR baixo", "pending",
         "2026-01-01T00:00:00+00:00", 0.8),
    )
    # run de agente concluído
    runs = AgentRunService(storage, clock=FakeClock())
    rid = runs.start_run("hermes-seo-agent", trigger="manual", intent="technical",
                         mode="analyze", started_by="admin@x.com")
    runs.complete(rid, status="success", urls=120, findings=9, opportunities=4,
                  safe_fixes=2, executed=1)
    # janela orgânica (2 páginas)
    storage.conn.executemany(
        "INSERT INTO query_pages (query, url, window_start, window_end, clicks, "
        "impressions, ctr, position, intent) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("q1", "https://x.com/a/", "2026-01-01", "2026-01-28", 50, 1000, 0.05, 4.2, "informational"),
            ("q2", "https://x.com/b/", "2026-01-01", "2026-01-28", 30, 800, 0.0375, 6.1, "commercial"),
        ],
    )
    # finding crítico + ação safe_fix pendente
    storage.conn.execute(
        "INSERT INTO findings (cycle_id, rule_id, url, severity, detail_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("c1", "title", "https://x.com/a/", "high", "{}", "2026-01-01T00:00:00+00:00"),
    )
    storage.conn.execute(
        "INSERT INTO actions (cycle_id, rule_id, url, level, status, fingerprint, executed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("c1", "meta_robots", "https://x.com/a/", "safe_fix", "pending", "fp1", None),
    )
    storage.conn.commit()
    return storage, cp


def test_today_aggregates_attention_and_runs(tmp_path):
    storage, cp = _seed(tmp_path / "t.db")
    today = cp.today()
    assert today["needs_attention"] >= 1
    assert today["critical_findings"] == 1
    assert today["safe_fixes"] == 1
    assert today["recent_runs"][0]["agent"] == "hermes-seo-agent"
    assert today["recent_runs"][0]["status"] == "success"
    # top oportunidades ordenam por score
    assert today["top_opportunities"][0]["source"] == "checklist"
    # orgânico agregado da janela
    org = today["organic_summary"]
    assert org["clicks"] == 80 and org["impressions"] == 1800
    # integrações: fontes sem credencial aparecem como missing (não zero)
    src = {s["source"]: s["data_status"] for s in today["integration_warnings"]}
    storage.close()


def test_work_items_returns_unified_feed(tmp_path):
    storage, cp = _seed(tmp_path / "w.db")
    items = cp.work_items()
    assert any(i["source"] == "checklist" and i["score"] == 0.8 for i in items)
    storage.close()


def test_integrations_missing_not_zero(tmp_path):
    storage, cp = _seed(tmp_path / "i.db")
    out = {s["source"]: s["data_status"] for s in cp.integrations()}
    # sem credenciais -> todas as fontes device estar missing (não available)
    assert out.get("gsc") == "missing"
    assert out.get("ga4") == "missing"
    storage.close()


def test_activity_mixes_runs_and_events(tmp_path):
    storage, cp = _seed(tmp_path / "a.db")
    act = cp.activity()
    assert act, "activity deve ter ao menos a entrada do run"
    assert any(a["type"] == "agent_run" for a in act)
    assert act == sorted(act, key=lambda a: a["ts"], reverse=True)
    storage.close()


def test_update_work_item_status_approve(tmp_path):
    storage, cp = _seed(tmp_path / "w.db")
    # aprovar checklist (pending -> done)
    res = cp.update_work_item_status("checklist:1", "approved", actor="admin@x.com")
    assert res == {"id": "checklist:1", "source": "checklist", "status": "approved"}
    row = storage.conn.execute(
        "SELECT status FROM improvement_checklist WHERE id = 1").fetchone()
    assert row[0] == "done"
    # auditoria registrada
    audit = storage.conn.execute(
        "SELECT action_type FROM audit_log WHERE entity = 'checklist:1'").fetchone()
    assert audit and audit[0] == "OPPORTUNITY_APPROVED"
    storage.close()


def test_update_work_item_status_backlog_and_errors(tmp_path):
    storage, cp = _seed(tmp_path / "b.db")
    # semear um backlog proposto
    storage.conn.execute(
        "INSERT INTO editorial_backlog (pauta_type, title, status, created_at) "
        "VALUES ('expand', 'Titulo', 'proposed', '2026-01-01T00:00:00+00:00')")
    storage.conn.commit()
    assert cp.update_work_item_status("backlog:1", "approved", actor="op@x.com")["status"] == "approved"
    assert cp.update_work_item_status("backlog:1", "snoozed", actor="op@x.com")["status"] == "snoozed"
    # id inválido / fonte desconhecida -> None
    assert cp.update_work_item_status("nope:1", "approved") is None
    assert cp.update_work_item_status("backlog:999", "approved") is None
    # status inválido -> ValueError
    import pytest as _pytest
    with _pytest.raises(ValueError):
        cp.update_work_item_status("backlog:1", "foo")
    storage.close()
