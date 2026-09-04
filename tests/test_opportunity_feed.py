"""Tests for P1 — OpportunityFeedService + OpportunityDTO read model."""

from types import SimpleNamespace

from hermes_seo_agent.services.opportunity import OpportunityDTO, OpportunityFeedService
from hermes_seo_agent.storage.db import Storage


def _seed(storage: Storage) -> None:
    # checklist (com score)
    storage.save_checklist_item(url="https://x.com/a/", item="title_meta",
                                reason="ctr baixo", action="reescrever título",
                                gain_clicks=10.0, explainable_score=0.8,
                                score_breakdown={"impacto": 0.8, "confianca": 0.7})
    # content_brief
    storage.conn.execute(
        "INSERT INTO content_briefs (url, title, intent, action, priority, status, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("https://x.com/b/", "Brief B", "informational", "cobrir query", 6.0,
         "proposed", "2026-01-01T00:00:00+00:00"),
    )
    # backlog
    storage.conn.execute(
        "INSERT INTO editorial_backlog (pauta_type, title, evidence, scope, score, "
        "status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("expand_existing", "Expandir B", "lacuna", "adicionar seção", 7.5,
         "proposed", "2026-01-01T00:00:00+00:00"),
    )
    # interlink
    storage.conn.execute(
        "INSERT INTO interlink_suggestions (source_url, target_url, reason, status, "
        "created_at) VALUES (?, ?, ?, ?, ?)",
        ("https://x.com/a/", "https://x.com/c/", "termo em comum", "proposed",
         "2026-01-01T00:00:00+00:00"),
    )
    # GA4 (para enriquecimento do feed)
    storage.save_ga4_page_metrics(
        [{"url": "https://x.com/a/", "sessions": 100.0, "engaged_sessions": 50.0,
          "engagement_rate": 0.5, "measurement_status": "available"}],
        window_start="2026-02-01", window_end="2026-02-28",
        source_scope="organic_landing",
    )
    storage.conn.commit()


def test_feed_union_all_sources_sorted_by_score(tmp_path):
    with Storage(tmp_path / "feed.db") as storage:
        _seed(storage)
        service = OpportunityFeedService(storage)
        items = service.feed(limit=100)
    sources = {it["source"] for it in items}
    assert sources == {"checklist", "content_brief", "backlog", "interlink"}
    # ordenado por score desc (desconhecido no fim)
    scores = [it["score"] for it in items if it["score"] is not None]
    assert scores == sorted(scores, reverse=True)


def test_feed_dto_contract_shape(tmp_path):
    with Storage(tmp_path / "feed2.db") as storage:
        _seed(storage)
        storage.save_editorial_inventory([
            SimpleNamespace(url="https://x.com/a/", title="Título atual da página",
                            h1=["H1 atual"], h2s=[], body_text="", canonical="",
                            meta_robots="", status_code=200),
        ], crawled_at="2026-02-28T00:00:00+00:00")
        service = OpportunityFeedService(storage)
        items = service.feed(source="checklist", limit=10)
    assert len(items) == 1
    dto = items[0]
    for key in ("id", "source", "type", "status", "url", "title", "score",
                "score_breakdown", "evidence", "recommendation",
                "acceptance_criteria", "gsc_metrics", "ga4_metrics",
                "measurement_state", "created_at", "updated_at"):
        assert key in dto, f"campo ausente: {key}"
    assert dto["id"] == "checklist:1"
    assert dto["source"] == "checklist"
    assert dto["title"] == "Título atual da página"
    assert dto["recommendation"] == "reescrever título"
    # GA4 enriquecido no DTO (não depende de Markdown/shell)
    assert dto["ga4_metrics"]["sessions"] == 100.0
    assert dto["ga4_metrics"]["measurement_status"] == "available"


def test_feed_source_filter_and_unknown_source(tmp_path):
    with Storage(tmp_path / "feed3.db") as storage:
        _seed(storage)
        service = OpportunityFeedService(storage)
        assert len(service.feed(source="interlink", limit=10)) == 1
        assert len(service.feed(source="backlog", limit=10)) == 1
        try:
            service.feed(source="nope")
            assert False, "fonte desconhecida deveria levantar ValueError"
        except ValueError:
            pass


def test_opportunity_dto_to_dict_roundtrip():
    dto = OpportunityDTO(
        id="checklist:1", source="checklist", type="title_meta",
        status="pending", url="https://x.com/a/", title="t",
        score=0.8, score_breakdown={"impacto": 0.8},
        evidence="e", recommendation="r", acceptance_criteria="a",
        gsc_metrics={"impressions": 10}, ga4_metrics={"sessions": 5},
        measurement_state="pending", created_at="c", updated_at="u",
    )
    d = dto.to_dict()
    assert d["id"] == "checklist:1"
    assert d["ga4_metrics"]["sessions"] == 5


def test_feed_exposes_decision_evidence_projection_and_link_context(tmp_path):
    with Storage(tmp_path / "decision-evidence.db") as storage:
        _seed(storage)
        storage.save_query_pages(
            [{"query": "guia c", "url": "https://x.com/c/", "clicks": 5,
              "impressions": 100, "ctr": 0.05, "position": 8.0,
              "intent": "informational"}],
            window_start="2026-02-01", window_end="2026-02-28",
        )
        storage.save_expectation(
            url="https://x.com/c/", computed_at="2026-03-01T00:00:00+00:00",
            source="test", changed_at="",
            expectation={"position": 8.0, "impressions": 100, "clicks": 5,
                         "ctr": 0.05, "expected_ctr": 0.08,
                         "expected_clicks": 8, "gap_clicks": 3,
                         "conservative_clicks": 6, "realistic_clicks": 8,
                         "optimistic_clicks": 10},
        )
        item = OpportunityFeedService(storage).feed(source="interlink", limit=1)[0]

    assert item["decision_type"] == "internal_link"
    assert item["gsc_metrics"]["has_queries"] is True
    assert item["top_queries"][0]["query"] == "guia c"
    assert item["projection"]["realistic_clicks"] == 8
    assert item["link_context"]["source_url"] == "https://x.com/a/"
    assert item["link_context"]["target_url"] == "https://x.com/c/"
    assert "suggested_anchor" in item["link_context"]
    assert "verification_steps" in item["link_context"]
