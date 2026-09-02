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


def test_pages_and_history(tmp_path):
    storage, cp = _seed(tmp_path / "pg.db")
    # dois snapshots de uma página (história)
    storage.conn.execute(
        "INSERT INTO page_snapshots (url, captured_at, source, status_code, title, meta_robots, "
        "canonical, word_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("https://x.com/a/", "2026-01-01T00:00:00+00:00", "audit", 200, "A", "", "https://x.com/a/", 900))
    storage.conn.execute(
        "INSERT INTO page_snapshots (url, captured_at, source, status_code, title, meta_robots, "
        "canonical, word_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("https://x.com/a/", "2026-01-02T00:00:00+00:00", "executor", 200, "A (novo)", "", "https://x.com/a/", 1200))
    storage.conn.commit()

    pages = cp.pages()
    assert any(p["url"] == "https://x.com/a/" for p in pages)
    page = next(p for p in pages if p["url"] == "https://x.com/a/")
    assert page["title"] == "A (novo)"           # snapshot mais recente
    hist = cp.page_history("https://x.com/a/")
    assert len(hist) == 2
    assert hist[0]["title"] == "A"
    assert hist[1]["source"] == "executor"
    storage.close()


def test_experiments_measurement_state(tmp_path):
    import json as _json
    storage, cp = _seed(tmp_path / "exp.db")
    # intervenção implementada, aguardando dados (sem verdict, sem janela medida)
    storage.conn.execute(
        "INSERT INTO opportunity_outcomes (keyword, opportunity_type, decision, "
        "human_decision, implemented_action, url, implemented_at, baseline_json, "
        "verdict, measured_28d, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?)",
        ("gojo idade", "expand_existing", "expand_existing", "approved",
         "expandir seção", "https://x.com/a/", "2026-01-01T00:00:00+00:00",
         _json.dumps({"gsc": {"clicks": 0, "position": 6.7}}), "2026-01-01T00:00:00+00:00"),
    )
    # intervenção já medida
    storage.conn.execute(
        "INSERT INTO opportunity_outcomes (keyword, opportunity_type, decision, "
        "human_decision, implemented_action, url, implemented_at, verdict, "
        "measured_28d, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
        ("one piece", "expand_existing", "expand_existing", "approved",
         "expandir", "https://x.com/b/", "2026-01-01T00:00:00+00:00", "improved",
         "2026-01-01T00:00:00+00:00"),
    )
    storage.conn.commit()
    exps = cp.experiments()
    by_keyword = {e["keyword"]: e for e in exps}
    assert by_keyword["gojo idade"]["measurement_state"] == "waiting_data"
    assert by_keyword["one piece"]["measurement_state"] == "measured"
    assert by_keyword["one piece"]["verdict"] == "improved"
    assert by_keyword["gojo idade"]["baseline"]["gsc"]["position"] == 6.7
    storage.close()


def test_technical_findings_enriched(tmp_path):
    import json as _json
    from types import SimpleNamespace
    config = SimpleNamespace(static_site_url="https://www.unicorniohater.com.br",
                             wordpress_public_url="https://prod.unicorniohater.com.br")
    storage = Storage(str(tmp_path / "tf.db"))
    cp = ControlPlaneService(storage, config)
    public_url = "https://www.unicorniohater.com.br/post/"
    # finding em URL LOCAL (deve normalizar por path p/ a URL pública)
    storage.conn.execute(
        "INSERT INTO findings (cycle_id, rule_id, url, severity, detail_json, created_at) "
        "VALUES ('c1','title_too_long','http://wordpress.dvl.to:8080/post/','low',?,"
        "'2026-01-01T00:00:00+00:00')", (_json.dumps({"length": 80}),))
    storage.conn.execute(
        "INSERT INTO page_snapshots (url, captured_at, source, title, status_code) "
        "VALUES (?, '2026-01-02T00:00:00+00:00', 'audit', 'Meu título real', 200)", (public_url,))
    # dados Google (query_pages + seo_expectations) para a URL pública
    storage.conn.executemany(
        "INSERT INTO query_pages (query, url, window_start, window_end, clicks, impressions, "
        "ctr, position, intent) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [("xbox disc to digital", public_url, "2026-01-01", "2026-01-28", 10, 2110, 0.0047, 7.9, "info"),
         ("xbox digital", public_url, "2026-01-01", "2026-01-28", 11, 3180, 0.0035, 8.7, "commercial")])
    storage.conn.execute(
        "INSERT INTO seo_expectations (url, computed_at, position, impressions, clicks, ctr, "
        "expected_ctr, expected_clicks, gap_clicks, conservative_clicks, realistic_clicks, "
        "optimistic_clicks) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (public_url, "2026-01-02T00:00:00+00:00", 8.3, 5290, 21, 0.004, 0.02, 127, 106,
         65, 106, 140))
    storage.conn.commit()

    res = cp.technical_findings()
    assert len(res) == 1
    f = res[0]
    assert f["rule"]["label"] == "Título longo"          # label amigável
    assert f["rule_id"] == "title_too_long"               # rule_id preservado
    assert f["page"]["public_url"] == public_url          # normalizado p/ pública
    assert f["page"]["wordpress_url"] == "https://prod.unicorniohater.com.br/post/"
    assert f["page"]["wordpress_edit_url"] == ""           # sem post_id -> não inventa
    assert f["title"] == "Meu título real"
    assert f["google"]["data_status"] == "available"
    assert f["google"]["impressions"] == 5290
    assert f["google"]["clicks"] == 21
    assert f["google"]["ctr"] == 21 / 5290
    assert len(f["google"]["top_queries"]) == 2           # queries da URL correta
    assert f["potential"]["realistic"] == 106
    assert f["potential"]["conservative"] == 65
    assert f["potential"]["optimistic"] == 140
    storage.close()


def test_technical_findings_missing_gsc_not_zero(tmp_path):
    from types import SimpleNamespace
    config = SimpleNamespace(static_site_url="https://www.unicorniohater.com.br",
                             wordpress_public_url="https://prod.unicorniohater.com.br")
    storage = Storage(str(tmp_path / "tm.db"))
    cp = ControlPlaneService(storage, config)
    storage.conn.execute(
        "INSERT INTO findings (cycle_id, rule_id, url, severity, detail_json, created_at) "
        "VALUES ('c1','title_too_long','https://www.unicorniohater.com.br/other/','low','{}',"
        "'2026-01-01T00:00:00+00:00')")
    storage.conn.commit()
    f = cp.technical_findings()[0]
    assert f["google"]["data_status"] == "missing"
    assert f["google"]["impressions"] is None    # missing ≠ zero
    assert f["google"]["clicks"] is None
    assert f["google"]["top_queries"] == []
    assert f["potential"]["data_status"] == "missing"
    storage.close()


def test_technical_splits_problems_and_corrections(tmp_path):
    import json as _json
    storage, cp = _seed(tmp_path / "te.db")
    # um finding (problema) e uma ação safe_fix (correção com before/after/rollback)
    storage.conn.execute(
        "INSERT INTO findings (cycle_id, rule_id, url, severity, detail_json, created_at) "
        "VALUES ('c1', 'title', 'https://x.com/a/', 'high', ?, '2026-01-01T00:00:00+00:00')",
        (_json.dumps({"missing": "title"}),),
    )
    storage.conn.execute(
        "INSERT INTO actions (cycle_id, rule_id, url, level, status, fingerprint, before_json, "
        "after_json, rollback_json, executed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("c1", "title", "https://x.com/a/", "safe_fix", "executed", "fp-tech",
         _json.dumps({"title": "velho"}), _json.dumps({"title": "novo"}),
         _json.dumps({"type": "wp_post_meta", "post_id": 1, "meta": {"title": "velho"}}),
         "2026-01-01T00:00:00+00:00"),
    )
    storage.conn.commit()

    t = cp.technical()
    assert any(p["rule_id"] == "title" for p in t["problems"])
    corr = next(c for c in t["corrections"] if c["fingerprint"] == "fp-tech")
    assert corr["before"] == {"title": "velho"}
    assert corr["after"] == {"title": "novo"}
    preview = cp.action_preview("fp-tech")
    assert preview["rollback"]["type"] == "wp_post_meta"
    assert cp.action_preview("desconhecido") is None
    storage.close()
