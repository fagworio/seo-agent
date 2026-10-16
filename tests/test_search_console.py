"""Tests for the Search Console connector + queue storage (mock transport)."""

import json

import httpx
import pytest

from hermes_seo_agent.config import load_config
from hermes_seo_agent.connectors.base import ConnectorError, HttpClient
from hermes_seo_agent.connectors.search_console import SearchConsoleClient
from hermes_seo_agent.storage.db import Storage


def _make_config(monkeypatch):
    for key in ("WORDPRESS_URL", "WORDPRESS_APP_USER", "WORDPRESS_APP_PASSWORD",
                "DRY_RUN", "GSC_SITE_URL", "GOOGLE_APPLICATION_CREDENTIALS",
                "SEO_ENV_FILE", "SQLITE_PATH"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SEO_ENV_FILE", "/nonexistent")
    monkeypatch.setenv("SQLITE_PATH", "/tmp/seo-test-gsc.db")
    return load_config()


def _gsc_client(config, handler):
    http = HttpClient(transport=httpx.MockTransport(handler))
    return SearchConsoleClient(config, token_provider=lambda: "fake-token", http=http)


def test_search_analytics(monkeypatch):
    config = _make_config(monkeypatch)
    monkeypatch.setenv("GSC_SITE_URL", "https://www.unicorniohater.com.br/")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer fake-token"
        body = json.loads(request.content)
        assert body["startDate"] == "2026-01-01"
        return httpx.Response(200, json={"rows": [{"keys": ["game x"], "clicks": 5,
                                                   "impressions": 100, "ctr": 0.05}]})

    client = _gsc_client(config, handler)
    rows = client.search_analytics(start_date="2026-01-01", end_date="2026-01-28")
    assert rows[0]["impressions"] == 100


def test_search_analytics_paginates_with_start_row_and_deduplicates(monkeypatch):
    config = _make_config(monkeypatch)
    monkeypatch.setenv("GSC_SITE_URL", "https://www.unicorniohater.com.br/")
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        start_row = int(body.get("startRow", 0))
        if start_row == 0:
            rows = [{"keys": ["q1", "https://x/a"]},
                    {"keys": ["q2", "https://x/b"]}]
        elif start_row == 2:
            # A repeated boundary row must not inflate the result set.
            rows = [{"keys": ["q2", "https://x/b"]},
                    {"keys": ["q3", "https://x/c"]}]
        else:
            rows = []
        return httpx.Response(200, json={"rows": rows})

    client = _gsc_client(config, handler)
    rows = client.search_analytics_query_page(
        start_date="2026-01-01", end_date="2026-01-28", row_limit=2)

    assert [row["keys"][0] for row in rows] == ["q1", "q2", "q3"]
    assert [call.get("startRow", 0) for call in calls] == [0, 2, 4]
    assert all(call["rowLimit"] == 2 for call in calls)
    assert client.last_query_meta["truncated"] is False


def test_search_analytics_remains_single_page_by_default(monkeypatch):
    config = _make_config(monkeypatch)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"rows": [
            {"keys": ["q1"]}, {"keys": ["q2"]},
        ]})

    client = _gsc_client(config, handler)
    rows = client.search_analytics(
        start_date="2026-01-01", end_date="2026-01-28", row_limit=2)

    assert len(rows) == 2
    assert calls == 1
    assert client.last_query_meta["truncated"] is True


def test_setting_checkpoint_is_compare_and_set(tmp_path):
    with Storage(str(tmp_path / "checkpoint.db")) as storage:
        storage.set_setting("title_engine:analysis_cursor", "old")
        assert storage.advance_setting_if_current(
            "title_engine:analysis_cursor", "old", "new") is True
        assert storage.advance_setting_if_current(
            "title_engine:analysis_cursor", "old", "stale") is False
        assert storage.get_setting("title_engine:analysis_cursor") == "new"


def test_named_lease_blocks_live_owner_and_recovers_after_expiry(monkeypatch, tmp_path):
    import hermes_seo_agent.storage.db as db_module

    clock = [100.0]
    monkeypatch.setattr(db_module.time, "time", lambda: clock[0])
    with Storage(str(tmp_path / "lease.db")) as storage:
        assert storage.acquire_named_lease("title_engine:run", "owner-a",
                                          ttl_seconds=10) is True
        assert storage.acquire_named_lease("title_engine:run", "owner-b",
                                          ttl_seconds=10) is False
        assert storage.renew_named_lease("title_engine:run", "owner-a",
                                         ttl_seconds=10) is True
        assert storage.release_named_lease("title_engine:run", "owner-b") is False
        clock[0] = 111.0
        assert storage.renew_named_lease("title_engine:run", "owner-a",
                                         ttl_seconds=10) is False
        assert storage.acquire_named_lease("title_engine:run", "owner-b",
                                          ttl_seconds=10) is True
        assert storage.advance_setting_if_current(
            "title_engine:analysis_cursor", "", "stale-owner",
            lease_key="title_engine:run", lease_owner="owner-a") is False


def test_inspect_url(monkeypatch):
    config = _make_config(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        # Lock the exact endpoint (v1, not webmasters/v3).
        assert request.url.path == "/v1/urlInspection/index:inspect"
        body = json.loads(request.content)
        assert body["inspectionUrl"] == "https://www.unicorniohater.com.br/a/"
        return httpx.Response(200, json={
            "inspectionResult": {"inspectionResultLink": "x", "indexStatusResult": {"verdict": "PASS"}}
        })

    client = _gsc_client(config, handler)
    result = client.inspect_url("https://www.unicorniohater.com.br/a/")
    assert result["indexStatusResult"]["verdict"] == "PASS"


def test_gsc_requires_credentials(monkeypatch):
    config = _make_config(monkeypatch)
    client = SearchConsoleClient(config, token_provider=None)
    with pytest.raises(ConnectorError):
        client.inspect_url("https://www.unicorniohater.com.br/a/")


def test_queue_enqueue_dedupe_dequeue(tmp_path):
    db = tmp_path / "queue.db"
    with Storage(str(db)) as storage:
        inserted = storage.enqueue_urls([
            {"url": "https://x.com/a/", "priority": 1},
            {"url": "https://x.com/b/", "priority": 6},
            {"url": "https://x.com/a/", "priority": 2},  # duplicate pending -> skipped
        ])
        assert inserted == 2
        stats = storage.queue_stats()
        assert stats.get("pending") == 2

        claimed = storage.dequeue_next(limit=10)
        assert [c["url"] for c in claimed] == ["https://x.com/a/", "https://x.com/b/"]
        assert storage.queue_stats().get("in_progress") == 2

        storage.mark_done(claimed[0]["id"], {"ok": True})
        storage.mark_failed(claimed[1]["id"], "boom")
        assert storage.queue_stats().get("done") == 1
        assert storage.queue_stats().get("failed") == 1


def test_queue_budget(tmp_path):
    db = tmp_path / "budget.db"
    with Storage(str(db)) as storage:
        assert storage.budget_used() == 0
        storage.budget_consume(3)
        assert storage.budget_used() == 3
        storage.budget_consume(2)
        assert storage.budget_used() == 5


def test_requeue_after_failure_reuses_row(tmp_path):
    """Regression: a URL that failed must not crash on re-queue + fail again."""
    db = tmp_path / "requeue.db"
    with Storage(str(db)) as storage:
        storage.enqueue_urls([{"url": "https://x.com/a/", "priority": 1}])
        item = storage.dequeue_next(limit=10)[0]
        storage.mark_failed(item["id"], "boom")
        # Re-queue (previous failed row is reused, not duplicated).
        storage.enqueue_urls([{"url": "https://x.com/a/", "priority": 2}])
        item2 = storage.dequeue_next(limit=10)[0]
        storage.mark_failed(item2["id"], "boom again")  # must not violate UNIQUE(url,status)
        rows = storage.conn.execute(
            "SELECT COUNT(*) FROM inspection_queue WHERE url = 'https://x.com/a/'"
        ).fetchone()[0]
        assert rows == 1  # one row per URL


def test_reset_stuck_in_progress(tmp_path):
    db = tmp_path / "stuck.db"
    with Storage(str(db)) as storage:
        storage.enqueue_urls([{"url": "https://x.com/a/", "priority": 1}])
        storage.dequeue_next(limit=10)  # -> in_progress
        assert storage.queue_stats().get("in_progress") == 1
        assert storage.reset_stuck_in_progress() == 1
        assert storage.queue_stats().get("pending") == 1


def test_action_idempotency(tmp_path):
    db = tmp_path / "actions.db"
    with Storage(str(db)) as storage:
        assert not storage.action_executed("abc123")
        storage.record_action(
            cycle_id="c1", rule_id="image_no_alt", url="https://x.com",
            level="safe_fix", fingerprint="abc123",
            before={"alt_text": ""}, after={"alt_text": "x"}, rollback={"alt_text": ""},
        )
        assert storage.action_executed("abc123")


def test_demand_trend_and_window_isolation(tmp_path):
    db = tmp_path / "demand.db"
    with Storage(str(db)) as storage:
        storage.save_query_pages(
            [{"query": "gojo idade", "url": "https://x.com/a/", "impressions": 100,
              "clicks": 2, "ctr": 0.02, "position": 5.0}],
            window_start="2026-01-01", window_end="2026-01-28",
        )
        storage.save_query_pages(
            [{"query": "gojo idade", "url": "https://x.com/a/", "impressions": 40,
              "clicks": 0, "ctr": 0.0, "position": 8.0}],
            window_start="2026-02-01", window_end="2026-02-28",
        )
        # top_demand usa apenas a janela mais recente (não soma as janelas).
        assert storage.latest_window_start() == "2026-02-01"
        top = storage.top_demand(min_impressions=10)
        assert len(top) == 1
        assert top[0]["impressions"] == 40.0
        assert top[0]["position"] == 8.0
        # tendência entre as duas janelas.
        trend = storage.demand_trend("gojo idade", window_a="2026-01-01", window_b="2026-02-01")
        assert trend["delta_pct"] == -60.0
        assert trend["trend"] == "declining"
