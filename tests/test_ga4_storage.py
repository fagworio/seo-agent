"""Tests for GA4 A1 — persisted history (ga4_collection_runs, ga4_page_metrics)."""

from hermes_seo_agent.storage.db import Storage


def _metrics_row(url="https://x.com/a/", sessions=100.0, engaged=60.0, rate=0.6,
                 time=1200.0, events=5.0, status="available"):
    return {
        "url": url, "sessions": sessions, "engaged_sessions": engaged,
        "engagement_rate": rate, "engagement_time": time, "key_events": events,
        "measurement_status": status,
    }


def test_save_and_read_metrics_latest_window(tmp_path):
    with Storage(tmp_path / "ga4.db") as storage:
        storage.save_ga4_page_metrics(
            [_metrics_row(), _metrics_row("https://x.com/b/", sessions=10.0)],
            window_start="2026-01-01", window_end="2026-01-28",
            source_scope="organic_landing",
        )
        storage.save_ga4_page_metrics(
            [_metrics_row(sessions=200.0)],
            window_start="2026-02-01", window_end="2026-02-28",
            source_scope="organic_landing",
        )
        assert storage.latest_ga4_window() == "2026-02-01"
        m = storage.ga4_metrics_for_url("https://x.com/a/")
        assert m["sessions"] == 200.0              # janela mais recente, não soma
        assert m["window_start"] == "2026-02-01"
        # URL só na janela antiga -> None (ausência ≠ zero)
        assert storage.ga4_metrics_for_url("https://x.com/b/") is None
        # janela histórica explícita
        old = storage.ga4_metrics_for_url(
            "https://x.com/a/", window_start="2026-01-01")
        assert old["sessions"] == 100.0


def test_scopes_do_not_mix(tmp_path):
    with Storage(tmp_path / "ga4s.db") as storage:
        storage.save_ga4_page_metrics(
            [_metrics_row()], window_start="2026-01-01", window_end="2026-01-28",
            source_scope="organic_landing",
        )
        storage.save_ga4_page_metrics(
            [_metrics_row(sessions=5.0)],
            window_start="2026-01-01", window_end="2026-01-28",
            source_scope="page_engagement",
        )
        assert storage.latest_ga4_window() == "2026-01-01"
        assert storage.ga4_metrics_for_url("https://x.com/a/",
                                           source_scope="organic_landing")["sessions"] == 100.0
        assert storage.ga4_metrics_for_url("https://x.com/a/",
                                           source_scope="page_engagement")["sessions"] == 5.0


def test_upsert_same_window_channel_overwrites(tmp_path):
    with Storage(tmp_path / "ga4u.db") as storage:
        storage.save_ga4_page_metrics(
            [_metrics_row(sessions=100.0)],
            window_start="2026-01-01", window_end="2026-01-28",
            source_scope="organic_landing",
        )
        storage.save_ga4_page_metrics(
            [_metrics_row(sessions=140.0)],
            window_start="2026-01-01", window_end="2026-01-28",
            source_scope="organic_landing",
        )
        rows = storage.conn.execute(
            "SELECT COUNT(*) FROM ga4_page_metrics WHERE url = 'https://x.com/a/'"
        ).fetchone()[0]
        assert rows == 1
        assert storage.ga4_metrics_for_url("https://x.com/a/")["sessions"] == 140.0


def test_trend_between_equivalent_windows(tmp_path):
    with Storage(tmp_path / "ga4t.db") as storage:
        storage.save_ga4_page_metrics(
            [_metrics_row(sessions=200.0, engaged=100.0, rate=0.5)],
            window_start="2026-01-01", window_end="2026-01-28",
            source_scope="organic_landing",
        )
        storage.save_ga4_page_metrics(
            [_metrics_row(sessions=100.0, engaged=80.0, rate=0.8)],
            window_start="2026-02-01", window_end="2026-02-28",
            source_scope="organic_landing",
        )
        trend = storage.ga4_trend_for_url(
            "https://x.com/a/", window_a="2026-01-01", window_b="2026-02-01")
        assert trend["delta_pct"] == -50.0
        assert trend["trend"] == "declining"
        assert trend["engagement_rate_a"] == 0.5
        assert trend["engagement_rate_b"] == 0.8
        # URL sem dado em uma das janelas -> delta None, sem trend inventada
        empty = storage.ga4_trend_for_url(
            "https://x.com/outra/", window_a="2026-01-01", window_b="2026-02-01")
        assert empty["delta_pct"] is None
        assert empty["sessions_a"] is None


def test_collection_runs_and_health(tmp_path):
    with Storage(tmp_path / "ga4r.db") as storage:
        storage.save_ga4_collection_run(
            source_scope="organic_landing", window_start="2026-01-01",
            window_end="2026-01-28", status="ok",
            rows_received=10, rows_matched=8, rows_unmatched=2,
        )
        storage.save_ga4_collection_run(
            source_scope="organic_landing", window_start="2026-02-01",
            window_end="2026-02-28", status="partial",
            rows_received=9, rows_matched=9, rows_unmatched=0,
            error="quota próximo do limite",
        )
        storage.save_ga4_collection_run(
            source_scope="page_engagement", window_start="2026-02-01",
            window_end="2026-02-28", status="empty", rows_received=0,
            rows_matched=0, rows_unmatched=0,
        )
        health = storage.ga4_collection_health()
        assert len(health["organic_landing"]) == 2
        assert health["organic_landing"][0]["status"] == "partial"
        assert health["organic_landing"][0]["error"] == "quota próximo do limite"
        assert len(health["page_engagement"]) == 1
        assert health["page_engagement"][0]["status"] == "empty"
