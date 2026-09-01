"""Tests for the deterministic post-improvement analysis."""

from hermes_seo_agent.report.expectations import build_expectation
from hermes_seo_agent.report.post_audit import (
    content_checklist,
    priority_score,
    total_gain,
)


def _metrics(impressions=3245, clicks=0, ctr=0.0, position=2.0):
    return build_expectation({
        "impressions": impressions, "clicks": clicks,
        "ctr": ctr, "position": position,
    })


def test_low_ctr_generates_title_meta_item():
    checklist = content_checklist(_metrics(), {"word_count": 800, "age_days": 30, "lost_traffic": False})
    items = {i["item"]: i for i in checklist}
    assert "title_meta" in items
    assert items["title_meta"]["gain_clicks"] > 0


def test_zero_click_generates_intent_item():
    checklist = content_checklist(_metrics(clicks=0), {"word_count": 800, "age_days": 30, "lost_traffic": False})
    items = {i["item"]: i for i in checklist}
    assert "intent" in items


def test_thin_content_detected():
    checklist = content_checklist(_metrics(), {"word_count": 120, "age_days": 30, "lost_traffic": False})
    items = {i["item"]: i for i in checklist}
    assert "thin_content" in items


def test_stale_and_lost_traffic():
    checklist = content_checklist(_metrics(), {"word_count": 800, "age_days": 300, "lost_traffic": True})
    items = {i["item"]: i for i in checklist}
    assert "stale" in items
    assert "lost_traffic" in items


def test_rank_item_for_bad_position():
    checklist = content_checklist(_metrics(impressions=500, position=12.0),
                                  {"word_count": 800, "age_days": 30, "lost_traffic": False})
    items = {i["item"]: i for i in checklist}
    assert "rank" in items


def test_no_items_for_healthy_page():
    checklist = content_checklist(
        build_expectation({"impressions": 1000, "clicks": 50, "ctr": 0.05, "position": 2.0}),
        {"word_count": 1000, "age_days": 30, "lost_traffic": False},
    )
    assert checklist == []


def test_priority_score_ranks_opportunity():
    low_ctr = priority_score(
        build_expectation({"impressions": 5000, "clicks": 0, "ctr": 0.0, "position": 5.0}),
        {"word_count": 800, "age_days": 30, "lost_traffic": True},
    )
    healthy = priority_score(
        build_expectation({"impressions": 5000, "clicks": 300, "ctr": 0.06, "position": 2.0}),
        {"word_count": 1000, "age_days": 30, "lost_traffic": False},
    )
    assert low_ctr > healthy


def test_total_gain_does_not_sum_overlapping_hypotheses():
    checklist = [
        {"gain_clicks": 100.0},
        {"gain_clicks": None},
        {"gain_clicks": 50.0},
    ]
    assert total_gain(checklist) == 100.0
