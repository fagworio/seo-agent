"""Tests for GA4 A4 — brief blocks, editorial suggestions, confidence delta."""

from hermes_seo_agent.report.ga4_evidence import (
    confidence_delta_for_ga4,
    editorial_suggestions,
    ga4_brief_blocks,
)
from hermes_seo_agent.report.ga4_rules import evaluate_url


def _gsc(impressions=2000.0, clicks=1000.0):
    return {"impressions": impressions, "clicks": clicks}


def _ga4(sessions=300.0, rate=0.20, status="available", ws="2026-02-01"):
    return {"sessions": sessions, "engaged_sessions": 100.0,
            "engagement_rate": rate, "key_events": 2.0,
            "measurement_status": status, "window_start": ws,
            "window_end": "2026-02-28"}


def _prev(sessions=600.0, rate=0.5):
    return {"sessions": sessions, "engagement_rate": rate,
            "window_start": "2026-01-01", "window_end": "2026-01-28"}


def test_brief_blocks_shape():
    findings = evaluate_url(gsc=_gsc(), ga4=_ga4(), ga4_prev=_prev())
    blocks = ga4_brief_blocks(gsc=_gsc(), ga4=_ga4(), ga4_prev=_prev(),
                              findings=findings)
    assert set(blocks) == {"organic_landing", "engagement", "trend", "data_quality"}
    assert blocks["organic_landing"]["sessions"] == 300.0
    assert blocks["engagement"]["measurement_status"] == "available"
    assert blocks["trend"]["sessions_a"] == 600.0
    assert blocks["data_quality"]["evidence_source"] == "combined"
    assert blocks["data_quality"]["findings"]


def test_brief_blocks_without_ga4():
    blocks = ga4_brief_blocks(gsc=_gsc(), ga4=None)
    assert "organic_landing" not in blocks
    assert blocks["data_quality"]["evidence_source"] == "gsc"
    assert blocks["data_quality"]["measurement_status"] == "missing"


def test_editorial_suggestions_from_findings():
    findings = evaluate_url(gsc=_gsc(), ga4=_ga4(), ga4_prev=_prev())
    suggestions = editorial_suggestions(gsc=_gsc(), ga4=_ga4(), findings=findings)
    items = {s["item"] for s in suggestions}
    assert "title_snippet_mismatch" in items
    assert "main_answer_missing_at_top" in items
    assert "content_stale_update" in items
    for s in suggestions:
        assert s["evidence_source"] == "combined"
        assert s["suggested_section"]
        assert s["acceptance_criteria"]
        # ação é consultiva — nunca remoção/noindex/redirect
        assert "remover" not in s["action"].lower()
        assert "noindex" not in s["action"].lower()


def test_no_suggestions_without_available_data():
    ga4_missing = {"sessions": 300.0, "measurement_status": "missing",
                   "window_start": "2026-02-01"}
    assert editorial_suggestions(gsc=_gsc(), ga4=ga4_missing,
                                 findings=evaluate_url(gsc=_gsc(), ga4=ga4_missing)) == []


def test_confidence_delta_explained():
    delta = confidence_delta_for_ga4(ga4=_ga4(), ga4_prev=_prev(),
                                     findings=[{"rule": "organic_low_engagement"}])
    assert delta["delta"] == 0.1
    assert "evidência pós-clique GA4 disponível" in delta["reason"]
    assert "tendência entre duas janelas" in delta["reason"]
    assert "organic_low_engagement" in delta["reason"]

    # sem GA4 disponível -> delta 0, motivo claro (sem aumento silencioso)
    none_delta = confidence_delta_for_ga4(
        ga4={"measurement_status": "missing"})
    assert none_delta["delta"] == 0.0
    assert "sem evidência GA4" in none_delta["reason"]
