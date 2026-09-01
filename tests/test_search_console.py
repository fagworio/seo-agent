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
