"""Tests for M6 — Opportunity Decision Engine (tree + two scores)."""

from hermes_seo_agent.report.decision_engine import (
    action_score,
    candidate_score,
    decide,
)


def _intent(**over):
    base = {
        "demand_score": 0.8,
        "relevant": True,
        "corpus_covers": True,
        "coverage_sufficient": False,
        "competing_urls": 1,
        "is_question": False,
        "stale": False,
        "rankability_score": 0.6,
        "trend": "growing",
        "confidence": 0.7,
    }
    base.update(over)
    return base


def test_weak_demand_monitors():
    out = decide(_intent(demand_score=0.1))
    assert out["decision"] == "weak_signal"
    assert out["opportunity_type"] == "engagement_opportunity"
    assert "monitorar" in out["reason"]


def test_irrelevant_is_discarded():
    out = decide(_intent(relevant=False))
    assert out["decision"] == "discard"
    assert "território editorial" in out["reason"]


def test_no_corpus_content_is_new_content():
    out = decide(_intent(corpus_covers=False))
    assert out["decision"] == "new_content"
    assert out["opportunity_type"] == "new_content"


def test_question_without_content_is_supporting_post():
    out = decide(_intent(corpus_covers=False, is_question=True))
    assert out["decision"] == "supporting_post"


def test_competing_urls_trigger_cannibalization_review():
    out = decide(_intent(competing_urls=3))
    assert out["decision"] == "cannibalization_review"
    assert "URLs competem" in out["reason"]


def test_sufficient_coverage_is_internal_link():
    out = decide(_intent(coverage_sufficient=True))
    assert out["decision"] == "internal_link"


def test_stale_content_is_refresh():
    out = decide(_intent(stale=True))
    assert out["decision"] == "refresh"


def test_default_is_expand_existing():
    out = decide(_intent())
    assert out["decision"] == "expand_existing"
    assert "cobertura é insuficiente" in out["reason"]


def test_candidate_score_separate_from_action_score():
    intent = _intent()
    cs = candidate_score(intent)
    as_ = action_score(intent)
    # CandidateScore usa 5 fatores; ActionScore usa 3 (impacto×confiança×facilidade)
    assert set(cs["factors"]) == {"demanda", "topical_fit", "rankability",
                                  "tendencia", "confianca"}
    assert set(as_["factors"]) >= {"impacto", "confianca", "facilidade"}
    assert cs["score"] >= 0.0
    assert as_["score"] >= 0.0


def test_candidate_score_trend_affects():
    growing = candidate_score(_intent(trend="growing"))
    declining = candidate_score(_intent(trend="declining"))
    assert growing["score"] > declining["score"]
    assert declining["factors"]["tendencia"] == 0.3


def test_action_score_uses_impact_confidence_ease():
    as_ = action_score(_intent(impact_clicks=100.0, confidence=0.8,
                               opportunity_type="new_content"))
    assert as_["factors"]["impacto"] > 0
    assert as_["factors"]["confianca"] == 0.8
