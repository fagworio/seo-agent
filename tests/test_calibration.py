"""M8-V2 (R9) — calibração de pesos pelos resultados medidos."""
import pytest

from hermes_seo_agent.report.calibration import (
    BANDS, calibration_report, calibrated_output_weights, improved, score_of)


def _outcome(score, verdict=None, position_delta=None, ctr_delta=None):
    results = {}
    for window in ("90d", "56d", "28d", "7d"):
        if position_delta is not None or ctr_delta is not None:
            gsc = {}
            if position_delta is not None:
                gsc["position"] = position_delta
            if ctr_delta is not None:
                gsc["ctr"] = ctr_delta
            results[window] = {"gsc_deltas": gsc}
    return {"candidate_score": score, "action_score": score, "verdict": verdict,
            "results": results}


def test_improved_detects_verdict_and_delta():
    assert improved(_outcome(0.8, verdict="improved")) is True
    assert improved(_outcome(0.8, verdict="worsened")) is False
    assert improved(_outcome(0.8, position_delta=-2)) is True
    assert improved(_outcome(0.8, ctr_delta=+0.01)) is True
    assert improved(_outcome(0.8, position_delta=+3)) is False
    assert improved(_outcome(0.8)) is None


def test_score_of_prefers_candidate():
    assert score_of({"candidate_score": 0.3, "action_score": 0.7}) == 0.3


def test_calibration_report_groups_by_band():
    outcomes = [
        _outcome(0.90, verdict="improved"),
        _outcome(0.85, verdict="improved"),
        _outcome(0.88, verdict="worsened"),
        _outcome(0.50, verdict="improved"),
        _outcome(0.45, verdict="worsened"),
        _outcome(0.30, verdict="worsened"),
    ]
    report = calibration_report(outcomes)
    assert report["n_outcomes"] == 6
    high = report["bands"]["80-100"]
    assert high["n"] == 3 and high["improved"] == 2
    assert high["improved_rate"] == round(2 / 3, 3)
    assert report["gradient"] is not None


def test_calibration_report_positive_gradient_when_high_score_predicts():
    outcomes = [
        _outcome(0.9, verdict="improved"), _outcome(0.85, verdict="improved"),
        _outcome(0.3, verdict="worsened"), _outcome(0.2, verdict="worsened"),
    ]
    report = calibration_report(outcomes)
    assert report["gradient"] > 0


def test_calibrated_weights_default_when_no_evidence():
    weights = calibrated_output_weights({"gradient": None})
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    assert weights["rankability"] == 0.30


def test_calibrated_weights_boost_rankability_and_renormalize():
    weights = calibrated_output_weights({"gradient": 0.3})
    assert weights["rankability"] > 0.30
    assert abs(sum(weights.values()) - 1.0) < 1e-6
