"""Tests for GA4 A3 — deterministic opportunity rules (high-confidence only)."""

from hermes_seo_agent.report.ga4_rules import (
    engagement_declining,
    evaluate_url,
    organic_low_engagement,
    search_click_engagement_gap,
)


def test_low_engagement_fires_with_full_evidence():
    f = organic_low_engagement(
        gsc_impressions=1200.0, ga4_sessions=200.0, engagement_rate=0.18,
        measurement_status="available",
    )
    assert f is not None
    assert f["rule"] == "organic_low_engagement"
    assert f["evidence"]["gsc_impressions"] == 1200.0
    assert f["thresholds"]["low_engagement_rate"] == 0.40
    assert "revisar intenção" in f["suggested_action"]
    assert f["limitations"]


def test_low_engagement_small_sample_never_fires():
    assert organic_low_engagement(
        gsc_impressions=100.0, ga4_sessions=5.0, engagement_rate=0.1,
        measurement_status="available",
    ) is None
    assert organic_low_engagement(
        gsc_impressions=1200.0, ga4_sessions=3.0, engagement_rate=0.1,
        measurement_status="available",
    ) is None


def test_low_engagement_requires_available_status():
    # métrica indisponível -> NUNCA vira finding (critério de aceite A3)
    assert organic_low_engagement(
        gsc_impressions=1200.0, ga4_sessions=200.0, engagement_rate=None,
        measurement_status="partial",
    ) is None
    assert organic_low_engagement(
        gsc_impressions=1200.0, ga4_sessions=None, engagement_rate=0.1,
        measurement_status="missing",
    ) is None


def test_declining_fires_between_equivalent_windows():
    f = engagement_declining(
        sessions_a=300.0, sessions_b=150.0,
        engagement_rate_a=0.5, engagement_rate_b=0.5,
        measurement_status="available",
    )
    assert f is not None
    assert f["rule"] == "engagement_declining"
    assert f["evidence"]["delta_pct"] == -50.0


def test_declining_requires_minimum_sample():
    assert engagement_declining(
        sessions_a=10.0, sessions_b=2.0,
        engagement_rate_a=0.5, engagement_rate_b=0.5,
        measurement_status="available",
    ) is None  # amostra base < 50


def test_declining_no_fabricated_trend_when_missing():
    assert engagement_declining(
        sessions_a=None, sessions_b=150.0,
        engagement_rate_a=None, engagement_rate_b=0.5,
        measurement_status="missing",
    ) is None


def test_search_click_gap_fires():
    f = search_click_engagement_gap(
        gsc_clicks=80.0, ga4_sessions=10.0, engagement_rate=0.2,
        measurement_status="available",
    )
    assert f is not None
    assert f["rule"] == "search_click_engagement_gap"
    assert "promessa do title/snippet" in f["suggested_action"]


def test_search_click_gap_no_fire_when_engagement_ok():
    assert search_click_engagement_gap(
        gsc_clicks=80.0, ga4_sessions=100.0, engagement_rate=0.6,
        measurement_status="available",
    ) is None
    assert search_click_engagement_gap(
        gsc_clicks=5.0, ga4_sessions=1.0, engagement_rate=0.2,
        measurement_status="available",
    ) is None  # cliques abaixo do mínimo


def test_evaluate_url_combines_rules_and_requires_both_sources():
    # clicks altos (1000) tornam o gap exigente (sessions < 500) enquanto
    # low-engagement pede sessions >= 50: 300 satisfaz ambos.
    gsc = {"impressions": 2000.0, "clicks": 1000.0}
    ga4 = {"sessions": 300.0, "engaged_sessions": 100.0, "engagement_rate": 0.20,
           "measurement_status": "available", "window_start": "2026-02-01"}
    prev = {"sessions": 600.0, "engagement_rate": 0.5,
            "window_start": "2026-01-01"}
    findings = evaluate_url(gsc=gsc, ga4=ga4, ga4_prev=prev)
    rules = {f["rule"] for f in findings}
    assert "organic_low_engagement" in rules
    assert "engagement_declining" in rules
    assert "search_click_engagement_gap" in rules
    for f in findings:
        assert f["window"]
        assert f["suggested_action"]
        assert f["limitations"]

    # sem GA4 ou sem GSC -> nenhuma regra (nada nasce de fonte única)
    assert evaluate_url(gsc=gsc, ga4=None) == []
    assert evaluate_url(gsc=None, ga4=ga4) == []


def test_evaluate_url_respects_measurement_status():
    gsc = {"impressions": 2000.0, "clicks": 100.0}
    ga4 = {"sessions": 300.0, "engagement_rate": 0.2,
           "measurement_status": "partial", "window_start": "2026-02-01"}
    assert evaluate_url(gsc=gsc, ga4=ga4) == []
