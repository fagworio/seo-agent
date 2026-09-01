"""Tests for M8 — opportunity outcomes, measurement and recalibration."""

from hermes_seo_agent.storage.db import Storage


def _register(storage: Storage, *, keyword="gojo idade", otype="expand_existing",
              verdict="improved"):
    oid = storage.save_opportunity_outcome(
        keyword=keyword, opportunity_type=otype, decision="expand_existing",
        evidence={"demand_score": 0.8}, candidate_score=0.4, action_score=0.6,
        human_decision="approved", implemented_action="expand",
        url="https://x.com/a/", implemented_at="2026-01-01T00:00:00+00:00",
    )
    storage.set_outcome_verdict(oid, verdict=verdict, days=28,
                                result={"gsc": {"clicks": 10}})
    return oid


def test_register_and_list_outcome(tmp_path):
    with Storage(tmp_path / "o.db") as storage:
        oid = _register(storage)
        items = storage.list_opportunity_outcomes()
        assert len(items) == 1
        assert items[0]["id"] == oid
        assert items[0]["keyword"] == "gojo idade"
        assert items[0]["verdict"] == "improved"
        assert items[0]["evidence"]["demand_score"] == 0.8
        assert items[0]["candidate_score"] == 0.4
        assert items[0]["action_score"] == 0.6


def test_register_rejection_preserves_reason(tmp_path):
    with Storage(tmp_path / "o2.db") as storage:
        oid = storage.save_opportunity_outcome(
            keyword="x", opportunity_type="new_content", decision="new_content",
            human_decision="rejected", rejection_reason="fora do território")
        items = storage.list_opportunity_outcomes()
        assert items[0]["human_decision"] == "rejected"
        assert items[0]["rejection_reason"] == "fora do território"


def test_recalibration_rule_simple(tmp_path):
    with Storage(tmp_path / "o3.db") as storage:
        # 4 outcomes do mesmo tipo, todos improved -> +0.05 de peso
        for i in range(4):
            _register(storage, keyword=f"k{i}", otype="expand_existing",
                      verdict="improved")
        # 3 outcomes de outro tipo, todos worsened -> -0.1 de peso
        for i in range(3):
            _register(storage, keyword=f"w{i}", otype="new_content",
                      verdict="worsened")
        stats = storage.recalibration_stats()
        by_type = {t["opportunity_type"]: t for t in stats["by_type"]}
        assert by_type["expand_existing"]["improved_rate"] == 1.0
        assert by_type["expand_existing"]["suggested_weight_adjustment"] == 0.05
        assert by_type["new_content"]["improved_rate"] == 0.0
        assert by_type["new_content"]["suggested_weight_adjustment"] == -0.1
        assert "perdem 0.1 de peso" in stats["rule"]


def test_recalibration_requires_minimum_cases(tmp_path):
    with Storage(tmp_path / "o4.db") as storage:
        _register(storage, otype="refresh", verdict="improved")  # só 1 caso
        stats = storage.recalibration_stats()
        refresh = next(t for t in stats["by_type"] if t["opportunity_type"] == "refresh")
        assert refresh["suggested_weight_adjustment"] == 0.0  # < 3 casos
        assert "poucos casos" in refresh["note"]
