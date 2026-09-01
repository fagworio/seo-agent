"""Tests for per-page history: snapshots, before/after diffs, trends."""

from hermes_seo_agent.report.history import (
    aggregate_trends,
    diff_snapshots,
    page_history,
    summarize_page,
)
from hermes_seo_agent.storage.db import Storage


def _snap(**kw) -> dict:
    base = {
        "url": "https://x.com/a/",
        "status_code": 200,
        "title": "",
        "meta_description": "",
        "canonical": "",
        "meta_robots": "",
        "h1": "",
        "word_count": 0,
        "content_hash": "",
        "cwv": {},
        "gsc": {},
    }
    base.update(kw)
    return base


def test_diff_text_changes():
    diff = diff_snapshots(
        _snap(title="Old Title", meta_description="Desc A"),
        _snap(title="New Title", meta_description="Desc A"),
    )
    fields = {c["field"]: c for c in diff["changed"]}
    assert fields["title"]["before"] == "Old Title"
    assert fields["title"]["after"] == "New Title"
    assert "meta_description" not in fields


def test_diff_content_and_status():
    diff = diff_snapshots(
        _snap(content_hash="abc", status_code=200),
        _snap(content_hash="def", status_code=404),
    )
    assert diff["content_changed"] is True
    assert any(c["field"] == "status_code" and c["after"] == "404" for c in diff["changed"])


def test_diff_cwv_improved_worsened():
    diff = diff_snapshots(
        _snap(cwv={"lcp": 3.0, "cls": 0.2, "inp": 150}),
        _snap(cwv={"lcp": 2.2, "cls": 0.3, "inp": 150}),
    )
    improved = {i["metric"]: i for i in diff["cwv"]["improved"]}
    worsened = {w["metric"]: w for w in diff["cwv"]["worsened"]}
    assert improved["lcp"]["before"] == 3.0 and improved["lcp"]["after"] == 2.2
    assert worsened["cls"]["before"] == 0.2 and worsened["cls"]["after"] == 0.3
    assert "inp" not in improved and "inp" not in worsened  # unchanged


def test_diff_gsc_deltas():
    diff = diff_snapshots(
        _snap(gsc={"impressions": 100, "clicks": 5}),
        _snap(gsc={"impressions": 130, "clicks": 9}),
    )
    assert diff["gsc"]["delta_impressions"] == 30
    assert diff["gsc"]["delta_clicks"] == 4


def test_snapshot_history_and_summary(tmp_path):
    db = tmp_path / "hist.db"
    with Storage(str(db)) as storage:
        storage.save_snapshot(url="https://x.com/a/", captured_at="2026-01-01T00:00:00Z",
                              source="audit", title="T1", status_code=200)
        storage.save_snapshot(url="https://x.com/a/", captured_at="2026-01-02T00:00:00Z",
                              source="executor", linked_action="fp1",
                              title="T2", status_code=200,
                              cwv={"cls": 0.3})
        history = page_history(storage, "https://x.com/a/")
        assert len(history) == 2
        assert history[0]["title"] == "T1"

        digest = summarize_page(storage, "https://x.com/a/")
        assert digest["snapshots"] == 2
        assert digest["timeline"][1]["linked_action"] == "fp1"
        assert digest["timeline"][1]["diff"]["changed"][0]["field"] == "title"

        trends = aggregate_trends(storage)
        assert trends["pages_tracked"] == 1
        assert trends["snapshots_total"] == 2
