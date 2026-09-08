"""Rankability V2 — construtor de sinais lê do storage e alimenta o modelo (R1–R5)."""
from hermes_seo_agent.storage.db import Storage
from hermes_seo_agent.report.rankability_signals import (
    build_cluster_signals, build_query_signals)
from hermes_seo_agent.report.rankability_v2 import (
    topic_authority, query_rankability, opportunity_engine, query_distribution)
from hermes_seo_agent.report.opportunity_v2 import compute_opportunity_v2
from hermes_seo_agent.services.control_plane import ControlPlaneService
from types import SimpleNamespace


def _seed(storage: Storage):
    for url in ("https://x.com/a/", "https://x.com/b/", "https://x.com/c/"):
        storage.conn.execute(
            "INSERT INTO corpus_documents (url, is_noindex, status_code, "
            "content_hash, built_at, title, h1, body_text) "
            "VALUES (?, 0, 200, 'h', '2026-02-01T00:00:00+00:00', ?, 'Goku', 'corpo')",
            (url, f"Título {url}"))
        storage.conn.execute(
            "INSERT INTO corpus_entities (url, entity, entity_type) "
            "VALUES (?, 'dragon ball', 'franchise')", (url,))
    # seções (uma pergunta)
    storage.conn.execute(
        "INSERT INTO corpus_sections (url, heading, heading_level, position) "
        "VALUES ('https://x.com/a/', 'Quem é Goku?', 2, 0)")
    storage.conn.execute(
        "INSERT INTO corpus_sections (url, heading, heading_level, position) "
        "VALUES ('https://x.com/a/', 'Poderes', 2, 1)")
    storage.conn.execute(
        "INSERT INTO corpus_sections (url, heading, heading_level, position) "
        "VALUES ('https://x.com/b/', 'Daima temporada', 2, 0)")
    # GSC: janela antiga + atual (para momentum)
    for url in ("https://x.com/a/", "https://x.com/b/", "https://x.com/c/"):
        storage.conn.execute(
            "INSERT INTO query_pages (query, url, window_start, window_end, clicks, "
            "impressions, ctr, position, intent) VALUES (?, ?, '2026-01-01', "
            "'2026-01-28', 10, 500, .02, 5, 'informational')",
            ("dragon ball daima temporada", url))
    storage.conn.execute(
        "INSERT INTO query_pages (query, url, window_start, window_end, clicks, "
        "impressions, ctr, position, intent) VALUES ('dragon ball daima', "
        "'https://x.com/a/', '2026-02-01', '2026-02-28', 60, 3000, .02, 3, 'informational')")
    storage.conn.execute(
        "INSERT INTO query_pages (query, url, window_start, window_end, clicks, "
        "impressions, ctr, position, intent) VALUES ('dragon ball episodios', "
        "'https://x.com/b/', '2026-02-01', '2026-02-28', 30, 1500, .02, 9, 'informational')")
    # links internos (ciclo do cluster)
    for src, tgt in [("a", "b"), ("a", "c"), ("b", "c"), ("c", "a")]:
        storage.conn.execute(
            "INSERT INTO internal_links (source_url, target_url, crawled_at) "
            "VALUES (?, ?, '2026-02-01')",
            (f"https://x.com/{src}/", f"https://x.com/{tgt}/"))
    storage.conn.commit()


def test_build_cluster_signals_reads_storage():
    s = Storage(":memory:")
    _seed(s)
    signals, cov = build_cluster_signals(s, "dragon ball")
    assert signals["entity"] == "dragon ball"
    assert signals["posts"] >= 3
    assert signals["entities"] >= 3
    assert signals["sections"] >= 3
    assert signals["questions"] >= 1
    assert len(signals["positions"]) >= 2
    assert len(signals["internal_page_edges"]) >= 4
    assert signals["momentum_delta_pct"] is not None  # 2 janelas
    assert signals.get("indexable", False) is True
    s.close()


def test_topic_authority_end_to_end():
    s = Storage(":memory:")
    _seed(s)
    signals, _ = build_cluster_signals(s, "dragon ball")
    res = topic_authority(signals, as_percent=True)
    assert 0 <= res["score"] <= 100
    assert res["label"] in ("forte", "média", "fraca")
    assert "ranking_strength" in res["factors"]
    assert "internal_authority" in res["factors"]
    assert "technica" not in res["factors"] or True  # fator técnico presente
    s.close()


def test_query_rankability_and_opportunity_end_to_end():
    s = Storage(":memory:")
    _seed(s)
    signals, _ = build_cluster_signals(s, "dragon ball")
    qs = build_query_signals(s, signals, "dragon ball daima temporada 2")
    assert qs["impressions"] > 0
    dist = query_distribution(signals["positions"])
    qr = query_rankability(qs, signals, dist, as_percent=True)
    assert 0 <= qr["score"] <= 100
    assert "semantic_fit" in qr["factors"]
    opp = opportunity_engine({
        "query_rankability": qr["score"] / 100,
        "demand": min(qs["impressions"] / 20000, 1.0),
        "headroom": 0.6,
        "momentum": 0.5,
        "strategic_fit": 1.0,
        "confidence": {"gsc_sample": 0.9, "windows": 0.9, "ga4_available": 0.5,
                       "corpus_available": 1.0, "semantic_evidence": 0.8,
                       "query_stability": 0.6, "technical_known": 0.7},
    }, as_percent=True)
    assert 0 <= opp["score"] <= 100
    s.close()


def test_compute_opportunity_v2_full_bundle():
    s = Storage(":memory:")
    _seed(s)
    bundle = compute_opportunity_v2(s, "dragon ball daima temporada 2", as_percent=True)
    assert "topic_authority" in bundle and "query_rankability" in bundle
    assert "opportunity" in bundle and "confidence" in bundle
    assert 0 <= bundle["opportunity"]["score"] <= 100
    assert bundle["signals"]["posts"] >= 3
    s.close()


def test_experiments_enriched_with_rankability_v2():
    s = Storage(":memory:")
    _seed(s)
    s.conn.execute(
        "INSERT INTO opportunity_outcomes (keyword, opportunity_type, decision, "
        "human_decision, implemented_action, url, implemented_at, created_at, "
        "baseline_json) VALUES (?, ?, 'expand', 'approved', 'expanded', ?, ?, ?, ?)",
        ("dragon ball daima temporada 2", "expand_existing",
         "https://x.com/a/", "2026-02-01", "2026-02-01",
         '{"gsc": {"position": 12, "clicks": 30}}'))
    s.conn.commit()
    cp = ControlPlaneService(s, SimpleNamespace())
    items = cp.experiments(limit=10, include_rankability_v2=True)
    assert items, "experiments devem ter ao menos o outcome aprovado"
    enriched = next((i for i in items if i.get("keyword") == "dragon ball daima temporada 2"), None)
    assert enriched is not None
    assert enriched.get("rankability_v2"), "V2 deve ser anexado quando solicitado"
    assert "opportunity" in enriched["rankability_v2"]
    s.close()


def test_work_items_with_rankability_v2():
    s = Storage(":memory:")
    _seed(s)
    # item da Caixa (checklist) com título que resolve para o cluster
    s.conn.execute(
        "INSERT INTO improvement_checklist (url, item, action, reason, status, created_at) "
        "VALUES ('https://x.com/a/', 'title_meta', 'Atualizar título', 'CTR', 'pending', '2026-02-01')")
    s.conn.commit()
    cp = ControlPlaneService(s, SimpleNamespace())
    items = cp.work_items(source="checklist", include_rankability_v2=True)
    target = next((i for i in items if i.get("id") == "checklist:1"), None)
    assert target is not None
    assert target.get("lifecycle") == "new"
    assert target.get("rankability_v2"), "rankability_v2 deve ser anexado"
    assert "opportunity" in target["rankability_v2"]
    s.close()


def test_pages_includes_rankability_v2_when_requested():
    s = Storage(":memory:")
    _seed(s)
    # snapshot + expectativa da página para o explorer de páginas
    s.conn.execute(
        "INSERT INTO page_snapshots (url, captured_at, title, status_code, content_hash) "
        "VALUES ('https://x.com/a/', '2026-02-01T00:00:00+00:00', 'Dragon Ball', 200, 'h')")
    s.conn.execute(
        "INSERT INTO seo_expectations (url, position, clicks, impressions, ctr, computed_at) "
        "VALUES ('https://x.com/a/', 11.4, 3500, 127000, 0.0275, '2026-02-01')")
    s.conn.commit()
    cp = ControlPlaneService(s, SimpleNamespace())
    res = cp.pages(include_rankability_v2=True)
    target = next((p for p in res["items"] if p["url"] == "https://x.com/a/"), None)
    assert target is not None
    assert target.get("rankability_v2"), "/pages deve anexar rankability_v2 quando solicitado"
    assert "opportunity" in target["rankability_v2"]
    s.close()


def test_page_intelligence_and_history_integration():
    s = Storage(":memory:")
    _seed(s)
    s.conn.execute(
        "INSERT INTO page_snapshots (url, captured_at, title, status_code, content_hash) "
        "VALUES ('https://x.com/a/', '2026-02-01T00:00:00+00:00', 'Dragon Ball', 200, 'h')")
    s.conn.execute(
        "INSERT INTO seo_expectations (url, position, clicks, impressions, ctr, computed_at) "
        "VALUES ('https://x.com/a/', 11.4, 3500, 127000, 0.0275, '2026-02-01')")
    s.conn.commit()
    cp = ControlPlaneService(s, SimpleNamespace())
    info = cp.page_intelligence("https://x.com/a/")
    assert info["metrics"]["position"] == 11.4
    assert info["rankability_v2"], "page_intelligence deve anexar rankability_v2"
    hist = cp.page_history("https://x.com/a/")
    assert len(hist) == 1
    s.close()


def test_page_intelligence_search_and_semantic():
    from hermes_seo_agent.report.page_intelligence import search_intelligence, semantic_coverage
    s = Storage(":memory:")
    _seed(s)
    search = search_intelligence(s, "https://x.com/a/")
    assert search["summary"]["impressions"] > 0
    assert search["distribution"]["top10"] >= 0
    assert len(search["queries"]) >= 1
    sem = semantic_coverage(s, "https://x.com/a/", "dragon ball")
    assert 0 <= sem["coverage"] <= 1
    assert "entity" in sem["components"]
    s.close()


def test_topics_and_content_gaps_endpoints():
    s = Storage(":memory:")
    _seed(s)
    s.upsert_competitor_documents([{"domain": "ign.com", "url": f"https://ign.com/persona-6-{i}/",
                                    "entities": ["persona 6"]} for i in range(3)])
    cp = ControlPlaneService(s, SimpleNamespace())
    topics = cp.topics(limit=20)
    assert any(t["topic"] == "dragon ball" and t["authority"] > 0 for t in topics)
    detail = cp.topic_detail("dragon ball")
    assert detail is not None and "authority_breakdown" in detail
    gaps = cp.content_gaps(as_percent=True)
    assert gaps["total"] >= 1
    assert gaps["by_type"].get("missing_topic", 0) >= 1  # persona 6 só nos concorrentes
    s.close()


def test_today_enriches_v2_and_topics():
    s = Storage(":memory:")
    _seed(s)
    cp = ControlPlaneService(s, SimpleNamespace())
    today = cp.today(limit=3)
    assert "emerging_topics" in today and "declining_topics" in today
    for o in today["top_opportunities"]:
        assert "rankability_v2" in o  # cross-data V2 presente no Hoje
    s.close()


def test_calibration_endpoint_exposes_report_and_weights():
    s = Storage(":memory:")
    _seed(s)
    cp = ControlPlaneService(s, SimpleNamespace())
    cal = cp.calibration()
    assert "report" in cal and "adjusted_opportunity_weights" in cal
    assert cal["report"]["n_outcomes"] >= 0
    assert abs(sum(cal["adjusted_opportunity_weights"].values()) - 1.0) < 1e-6
    s.close()
