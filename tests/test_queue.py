"""Tests for the inspection queue priority logic (pure, deterministic)."""

import datetime

from hermes_seo_agent.queue.inspection import (
    assign_priority,
    build_queue_entries,
    is_new_past_grace,
    lost_traffic,
    remaining_budget,
)


def test_priority_tiers():
    assert assign_priority() == 6
    assert assign_priority(is_new_past_grace=True) == 1
    assert assign_priority(zero_impressions=True) == 2
    assert assign_priority(lost_traffic=True) == 3
    assert assign_priority(non_200=True) == 4
    assert assign_priority(conflict=True) == 5
    # lowest number wins
    assert assign_priority(non_200=True, zero_impressions=True) == 2


def test_is_new_past_grace():
    now = datetime.datetime(2026, 1, 15, tzinfo=datetime.timezone.utc)
    # 10h old < 24h grace -> not tier 1
    assert not is_new_past_grace("2026-01-15T02:00:00+00:00", grace_hours=24, now=now)
    # 48h old, within 30 days -> tier 1
    assert is_new_past_grace("2026-01-13T02:00:00+00:00", grace_hours=24, now=now)
    # 40 days old -> not tier 1 (falls back to other tiers)
    assert not is_new_past_grace("2025-12-05T02:00:00+00:00", grace_hours=24, now=now)


def test_lost_traffic():
    assert lost_traffic(100, 40, decline_ratio=0.5)
    assert not lost_traffic(100, 90, decline_ratio=0.5)
    assert not lost_traffic(0, 10)


def test_build_queue_entries_priorities():
    urls = [
        "https://www.unicorniohater.com.br/new-post/",
        "https://www.unicorniohater.com.br/zero-imp/",
        "https://www.unicorniohater.com.br/lost/",
        "https://www.unicorniohater.com.br/broken/",
        "https://www.unicorniohater.com.br/conflict/",
        "https://www.unicorniohater.com.br/old/",
    ]
    entries = build_queue_entries(
        urls,
        modified_by_url={"/new-post/": "2026-01-13T02:00:00+00:00"},
        impressions_by_url={"/zero-imp/": 0.0, "/lost/": 40.0},
        prev_impressions_by_url={"/lost/": 100.0},
        non_200_urls={"/broken/"},
        conflict_urls={"/conflict/"},
        grace_hours=24,
        now=datetime.datetime(2026, 1, 15, tzinfo=datetime.timezone.utc),
    )
    by_path = {e["url"].rsplit("/", 2)[-2]: e["priority"] for e in entries}
    assert by_path["new-post"] == 1
    assert by_path["zero-imp"] == 2
    assert by_path["lost"] == 3
    assert by_path["broken"] == 4
    assert by_path["conflict"] == 5
    assert by_path["old"] == 6


def test_remaining_budget():
    assert remaining_budget(1800, 10) == 1790
    assert remaining_budget(100, 200) == 0
