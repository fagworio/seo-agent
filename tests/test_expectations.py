"""Tests for deterministic SEO expectations (benchmark + estimate)."""

from hermes_seo_agent.report.expectations import (
    SCENARIOS,
    build_expectation,
    estimate,
    expected_ctr,
)


def test_expected_ctr_by_position():
    assert expected_ctr(1) == 0.35
    assert expected_ctr(2) == 0.16
    assert expected_ctr(3) == 0.11
    assert expected_ctr(6.7) == 0.04     # bucket <= 7
    assert expected_ctr(15) == 0.01      # page 2+
    assert expected_ctr(None) is None


def test_estimate_computes_expected_and_gap():
    est = estimate(position=2.0, impressions=3245, clicks=0)
    assert est["expected_ctr"] == 0.16
    assert est["expected_clicks"] == 519.2   # 3245 * 0.16
    assert est["gap_clicks"] == 519.2
    assert est["conservative_clicks"] == 129.8
    assert est["realistic_clicks"] == 259.6
    assert est["optimistic_clicks"] == 389.4


def test_estimate_none_when_missing():
    est = estimate(position=None, impressions=None, clicks=None)
    assert est["expected_ctr"] is None
    assert est["expected_clicks"] is None
    assert est["gap_clicks"] is None


def test_build_expectation_merges_metrics():
    exp = build_expectation({"position": 5.0, "impressions": 2280, "clicks": 0, "ctr": 0.0})
    assert exp["position"] == 5.0
    assert exp["expected_ctr"] == 0.055
    assert exp["expected_clicks"] == 125.4


def test_scenarios_cover_all():
    assert set(SCENARIOS) == {"conservative", "realistic", "optimistic"}
