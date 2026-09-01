"""Tests for M5 — rankability profile (calibratable score, explained factors)."""

from hermes_seo_agent.report.rankability import rankability_profile


def _strong_cluster():
    return {
        "posts": 12, "impressions": 25_000, "clicks": 800,
        "top10_queries": 40, "total_queries": 50,
        "positions": [1.5, 2.0, 2.5, 3.0, 3.5],
        "internal_links": 35, "days_since_update": 10,
        "ga4_engagement_rate": 0.6, "ga4_status": "available",
    }


def _weak_cluster():
    return {
        "posts": 1, "impressions": 50, "clicks": 1,
        "top10_queries": 0, "total_queries": 10,
        "positions": [18.0, 22.0, 25.0],
        "internal_links": 0, "days_since_update": 400,
        "ga4_engagement_rate": None, "ga4_status": "missing",
    }


def test_strong_cluster_scores_high_with_explanation():
    p = rankability_profile(_strong_cluster())
    assert p["rankability_score"] >= 0.7
    assert p["label"].startswith("autoridade forte")
    assert "probabilidade" not in p["label"].lower().replace("não probabilidade", "")
    # cada fator tem explicação
    for name, f in p["factors"].items():
        if f["weight"]:
            assert f["explanation"]
    assert p["caveat"]  # nunca chama de probabilidade


def test_weak_cluster_scores_low_and_never_fabricates():
    p = rankability_profile(_weak_cluster())
    assert p["rankability_score"] < 0.4
    assert p["label"].startswith("autoridade fraca")
    # engajamento ausente -> fator zero com explicação, não "0% real"
    assert p["factors"]["engagement"]["score"] == 0.0
    assert "sem engajamento GA4" in p["factors"]["engagement"]["explanation"]


def test_growth_factor_positive_vs_negative():
    strong = rankability_profile(_strong_cluster(), growth_delta_pct=40.0)
    weak = rankability_profile(_strong_cluster(), growth_delta_pct=-50.0)
    assert strong["factors"]["growth"]["score"] > weak["factors"]["growth"]["score"]
    assert weak["factors"]["growth"]["score"] == 0.0


def test_external_difficulty_penalizes_with_note():
    base = rankability_profile(_strong_cluster())
    hard = rankability_profile(_strong_cluster(), external_difficulty=0.9)
    assert hard["rankability_score"] < base["rankability_score"]
    assert "dificuldade externa" in hard["external_note"]


def test_easy_keyword_outside_authority_is_explained():
    """Critério M5: 'keyword parece fácil, mas está fora da autoridade'."""
    cluster = {"posts": 0, "impressions": 0, "clicks": 0, "top10_queries": 0,
               "total_queries": 0, "positions": [], "internal_links": 0,
               "days_since_update": None, "ga4_engagement_rate": None,
               "ga4_status": "missing"}
    p = rankability_profile(cluster, external_difficulty=0.1)  # parece fácil
    assert p["factors"]["coverage"]["score"] == 0.0
    assert "sem posts no cluster" in p["factors"]["coverage"]["explanation"]
    assert p["rankability_score"] < 0.3
