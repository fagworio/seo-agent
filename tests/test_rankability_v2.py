"""Rankability V2 (roadmap R1–R5): Topic Authority, Query Rankability,
Headroom, Confidence e Opportunity Engine V2 (pesos + gates). Determinístico."""
import pytest

from hermes_seo_agent.report import rankability_v2 as rv


def test_query_distribution_counts_and_shares():
    dist = rv.query_distribution([1, 2, 5, 12, 30, 45, 60])
    assert dist["total"] == 7
    assert dist["counts"]["top3"] == 2
    assert dist["counts"]["top10"] == 3
    assert dist["counts"]["top20"] == 4
    assert dist["counts"]["top50"] == 6
    assert dist["shares"]["top10"] == round(3 / 7, 4)
    assert dist["median_position"] == 12
    assert dist["avg_position"] == round(sum([1, 2, 5, 12, 30, 45, 60]) / 7, 2)


def test_ranking_strength_strong_beats_weak():
    strong = rv.ranking_strength(rv.query_distribution([1, 1, 2, 3, 5, 8]))
    weak = rv.ranking_strength(rv.query_distribution([25, 30, 40, 55, 60, 70]))
    assert strong[0] > weak[0]


def test_topic_authority_splits_and_explains():
    cluster = {
        "posts": 40, "entities": 20, "sections": 120, "questions": 12,
        "positions": [1, 2, 5, 8, 11, 15, 22, 40],
        "impressions": 25000, "clicks": 1500,
        "internal_page_edges": [("a", "b"), ("a", "c"), ("b", "c"), ("c", "a")],
        "urls": ["a", "b", "c"],
        "ga4_engagement_rate": 0.6, "site_engagement_rate": 0.5,
        "momentum_delta_pct": 40,
        "indexable": True, "http_ok": True, "canonical_ok": True,
        "in_sitemap": True, "google_indexed": True, "cwv_ok": True,
    }
    res = rv.topic_authority(cluster, as_percent=True)
    assert "score" in res and 0 <= res["score"] <= 100
    assert "ranking_strength" in res["factors"]
    assert res["factors"]["technical_health"]["score"] == 1.0
    assert "distribution" in res
    assert res["label"] in ("forte", "média", "fraca")


def test_topic_authority_technical_blocker_zeroes():
    cluster = {
        "posts": 30, "entities": 10, "sections": 60, "questions": 5,
        "positions": [1, 2, 3], "impressions": 20000, "clicks": 1000,
        "internal_authority": 0.5, "indexable": False, "http_ok": True,
        "canonical_ok": True, "in_sitemap": True, "google_indexed": False,
    }
    res = rv.topic_authority(cluster)
    assert res["score"] == 0.0
    assert res["factors"].get("_blocked")


def test_internal_page_authority_hub_wins():
    urls = ["hub", "a", "b", "c"]
    edges = [("hub", "a"), ("hub", "b"), ("hub", "c"),
             ("a", "hub"), ("b", "hub"), ("c", "hub")]
    per_url, aggregate = rv.internal_page_authority(urls, edges)
    assert per_url["hub"] >= per_url["a"]
    assert 0 < aggregate <= 1


def test_semantic_fit_uses_all_components():
    sig = {"entity_fit": 1.0, "title_fit": 0.8, "h1_fit": 0.7,
           "heading_fit": 0.6, "body_fit": 0.7, "question_fit": 0.4,
           "related_entity_fit": 0.5}
    score, why = rv.semantic_fit(sig)
    assert 0 < score < 1
    # peso do corpo (0.15) somado ao peso da entidade (0.25) domina
    assert score > 0.5


def test_query_rankability_gate_on_no_semantic_fit():
    query = {"keyword": "dragon ball daima temporada 2", "impressions": 18000,
             "clicks": 800, "position": 11,
             "semantic": {"entity_fit": 0.0, "title_fit": 0.0, "body_fit": 0.0}}
    cluster = {"related_top10_queries": 30, "related_queries": 40,
               "positions": [1, 3, 9, 15, 40]}
    dist = rv.query_distribution(cluster["positions"])
    res = rv.query_rankability(query, cluster, dist)
    assert res["score"] == 0.0  # gate: sem fit semântico


def test_query_rankability_competitive_semantic():
    query = {"keyword": "dragon ball daima temporada 2", "impressions": 30000,
             "clicks": 1800, "position": 6, "semantic": {
                 "entity_fit": 1.0, "title_fit": 0.9, "h1_fit": 0.8,
                 "heading_fit": 0.8, "body_fit": 0.9, "question_fit": 0.6,
                 "related_entity_fit": 0.7}}
    cluster = {"related_top10_queries": 40, "related_queries": 50,
               "positions": [1, 2, 4, 6, 9, 12]}
    dist = rv.query_distribution(cluster["positions"])
    res = rv.query_rankability(query, cluster, dist, as_percent=True)
    assert res["score"] > 50


def test_headroom_position_12_higher_than_position_1():
    low_room = rv.headroom(1, 0.38, 0.40)
    high_room = rv.headroom(12, 0.012, 0.05)
    assert high_room[0] > low_room[0]


def test_confidence_v2_labels():
    assert rv.confidence_v2({}).get("label") == "insufficient_data"
    good = rv.confidence_v2({"gsc_sample": 0.95, "windows": 1.0,
                             "ga4_available": 1.0, "corpus_available": 1.0,
                             "semantic_evidence": 0.9, "query_stability": 0.7,
                             "technical_known": 1.0})
    assert good["label"] == "high" and good["score"] > 0.75


def test_opportunity_engine_gate_and_weighted():
    # gate de relevância zera
    blocked = rv.opportunity_engine({"relevant": False, "indexable": True})
    assert blocked["score"] == 0.0
    assert blocked["reason"]

    good = rv.opportunity_engine({
        "query_rankability": 0.8, "demand": 0.9, "headroom": 0.9,
        "momentum": 0.7, "strategic_fit": 0.8,
        "confidence": {"gsc_sample": 0.9, "windows": 1.0, "ga4_available": 1.0,
                       "corpus_available": 1.0, "semantic_evidence": 0.8,
                       "query_stability": 0.8, "technical_known": 1.0},
    }, as_percent=True)
    assert good["score"] > 50


def test_opportunity_engine_insufficient_confidence_halves():
    base = {"query_rankability": 0.8, "demand": 0.9, "headroom": 0.9,
            "momentum": 0.7, "strategic_fit": 0.8}
    low = rv.opportunity_engine({**base, "confidence": {}})
    high = rv.opportunity_engine({**base, "confidence": {
        "gsc_sample": 0.9, "windows": 1.0, "ga4_available": 1.0,
        "corpus_available": 1.0, "semantic_evidence": 0.8,
        "query_stability": 0.8, "technical_known": 1.0}})
    # dados insuficientes atenuam (não zeram) — low fica abaixo de high
    assert low["score"] < high["score"]
