"""Tests for title opportunities + impact measurement (pure logic)."""

from hermes_seo_agent.report.impact import aggregate_impact, impact_deltas, verdict
from hermes_seo_agent.tools.title_opportunities import candidate_title, pick_top_query


# -- title candidates -------------------------------------------------------

def test_pick_top_query_prefers_position_and_impressions():
    rows = [
        {"keys": ["jujutsu kaisen"], "impressions": 100, "position": 30},
        {"keys": ["quantos anos tem o gojo"], "impressions": 6, "position": 7},
        {"keys": ["choso idade"], "impressions": 1, "position": 32},
    ]
    assert pick_top_query(rows) == "quantos anos tem o gojo"  # melhor posição com >=2 impr


def test_candidate_title_capitalizes_and_truncates():
    assert candidate_title("quantos anos tem o gojo") == "Quantos Anos Tem o Gojo"
    assert candidate_title("the elder scrolls oblivion remaster vaza e impressiona") == \
        "The Elder Scrolls Oblivion Remaster Vaza e Impressiona"


def test_candidate_title_truncates_to_max():
    title = candidate_title("x" * 80, max_len=60)
    assert len(title) <= 60


# -- impact deltas ----------------------------------------------------------

def test_impact_deltas_improvement():
    d = impact_deltas(
        {"clicks": 1000, "impressions": 20000, "ctr": 0.05, "position": 31},
        {"clicks": 4000, "impressions": 60000, "ctr": 0.067, "position": 5},
    )
    assert d["clicks_delta"] == 3000.0
    assert d["clicks_pct"] == 300.0
    assert d["position_delta"] == -26.0
    assert d["verdict"] == "improved"


def test_impact_deltas_worsened():
    d = impact_deltas(
        {"clicks": 4000, "impressions": 60000, "ctr": 0.067, "position": 5},
        {"clicks": 1000, "impressions": 20000, "ctr": 0.05, "position": 31},
    )
    assert d["verdict"] == "worsened"


def test_impact_deltas_missing_data():
    d = impact_deltas({"clicks": 100}, {"position": 5})
    assert d["clicks_delta"] is None
    assert d["position_delta"] is None  # before has no position
    assert d["verdict"] == "neutral"


def test_verdict_position_improves():
    assert verdict({"position_delta": -5}) == "improved"
    assert verdict({"position_delta": 5}) == "worsened"


def test_aggregate_impact():
    items = [
        {"verdict": "improved", "clicks_delta": 3000, "impressions_delta": 40000},
        {"verdict": "worsened", "clicks_delta": -500, "impressions_delta": -1000},
    ]
    agg = aggregate_impact(items)
    assert agg["pages_measured"] == 2
    assert agg["verdict_counts"]["improved"] == 1
    assert agg["total_clicks_delta"] == 2500.0
