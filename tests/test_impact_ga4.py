"""Tests for GA4 A5 — integrated measurement (GSC + GA4, no causality)."""

from hermes_seo_agent.report.impact_ga4 import (
    baseline_ga4,
    baseline_gsc,
    combined_verdict,
    engagement_deltas,
    engagement_verdict,
)


def test_engagement_deltas_improved():
    before = {"sessions": 100.0, "engaged_sessions": 50.0, "engagement_rate": 0.5,
              "measurement_status": "available"}
    after = {"sessions": 140.0, "engaged_sessions": 90.0, "engagement_rate": 0.64,
             "measurement_status": "available"}
    d = engagement_deltas(before, after)
    assert d["sessions_delta"] == 40.0
    assert d["sessions_pct"] == 40.0
    assert d["data_quality"] == "available"
    assert d["verdict"] == "improved"


def test_engagement_deltas_worsened():
    before = {"sessions": 100.0, "engaged_sessions": 50.0, "engagement_rate": 0.5,
              "measurement_status": "available"}
    after = {"sessions": 60.0, "engaged_sessions": 30.0, "engagement_rate": 0.5,
             "measurement_status": "available"}
    assert engagement_deltas(before, after)["verdict"] == "worsened"


def test_engagement_deltas_insufficient_without_available_data():
    before = {"sessions": 100.0, "engaged_sessions": 50.0, "engagement_rate": 0.5,
              "measurement_status": "available"}
    after = {"sessions": 140.0, "engaged_sessions": 90.0, "engagement_rate": 0.64,
             "measurement_status": "partial"}
    d = engagement_deltas(before, after)
    assert d["verdict"] == "insufficient_data"
    assert "partial" in d["data_quality"]
    # baseline ausente também é insuficiente (ausência ≠ zero)
    assert engagement_deltas(None, after)["verdict"] == "insufficient_data"


def test_engagement_verdict_mixed():
    d = {"sessions_delta": 10.0, "engagement_rate_delta": -0.1}
    assert engagement_verdict(d) == "mixed"


def test_combined_verdict_priority():
    # piora em qualquer dimensão domina
    assert combined_verdict(
        {"verdict": "improved"}, {"verdict": "worsened"}) == "worsened"
    assert combined_verdict(
        {"verdict": "worsened"}, {"verdict": "improved"}) == "worsened"
    # melhor em qualquer uma -> improved
    assert combined_verdict(
        {"verdict": "improved"}, {"verdict": "neutral"}) == "improved"
    # uma dimensão insuficiente NÃO invalida a outra (mede com o que há)
    assert combined_verdict(
        {"verdict": "improved"}, {"verdict": "insufficient_data"}) == "improved"
    assert combined_verdict(
        {"verdict": "insufficient_data"}, {"verdict": "worsened"}) == "worsened"
    # apenas quando TODAS são insuficientes
    assert combined_verdict(
        {"verdict": "insufficient_data"}, {"verdict": "insufficient_data"}) == "insufficient_data"
    assert combined_verdict(
        {"verdict": "neutral"}, {"verdict": "neutral"}) == "neutral"
    assert combined_verdict(
        {"verdict": "mixed"}, {"verdict": "neutral"}) == "mixed"


def test_baseline_slicing_forward_and_backward_compatible():
    nested = {"gsc": {"impressions": 1}, "ga4": {"sessions": 2}}
    assert baseline_gsc(nested) == {"impressions": 1}
    assert baseline_ga4(nested) == {"sessions": 2}
    # baseline legado (dict plano) continua funcionando
    legacy = {"impressions": 1, "clicks": 3}
    assert baseline_gsc(legacy) == legacy
    assert baseline_ga4(legacy) is None
    assert baseline_gsc(None) is None
