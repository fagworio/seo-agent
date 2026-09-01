"""Tests for GA4 A2 — operational collection and calibration CLI (mocked)."""

import argparse
import json

import pytest

from hermes_seo_agent.cli import _cmd_ga4
from hermes_seo_agent.config import Config
from hermes_seo_agent.storage.db import Storage


def _config(db_path) -> Config:
    return Config(
        wordpress_url="http://localhost",
        static_site_url="https://www.unicorniohater.com.br",
        app_user="u", app_password="p",
        dry_run=False,
        ga4_property_id="123456789",
        google_credentials="fake-sa.json",
        sqlite_path=str(db_path),
    )


def _ga4_result(rows=None, unmatched=None, row_count=None):
    return {
        "rows": rows or [{
            "url": "https://www.unicorniohater.com.br/post/",
            "domain_valid": True, "matched_sitemap": True,
            "sessions": 100.0, "engaged_sessions": 60.0,
            "engagement_rate": 0.6, "engagement_time": 1200.0,
            "key_events": 5.0, "measurement_status": "available",
        }],
        "row_count": row_count or 1,
        "unmatched": unmatched or [],
        "quota": {"tokensPerDay": {"remaining": 100}},
    }


class _FakeGA4:
    def __init__(self, result):
        self._result = result
        self.calls = []

    def status(self, **kw):
        self.calls.append(("status", kw))
        return {"configured": True, "property_id": "123456789", "token_ok": True,
                "window": {"start": kw["start_date"], "end": kw["end_date"]},
                "rows_returned": self._result["row_count"],
                "canonical_urls": len(self._result["rows"]),
                "unmatched": self._result["unmatched"],
                "quota": self._result["quota"]}

    def organic_landing_performance(self, **kw):
        self.calls.append(("organic", kw))
        return self._result

    def page_engagement(self, **kw):
        self.calls.append(("engagement", kw))
        return self._result


class _FakeGSC:
    def __init__(self, rows):
        self._rows = rows

    def search_analytics_by_page(self, **kw):
        return self._rows


def test_ga4_status(monkeypatch, capsys):
    db = "/tmp/ga4-cli-status.db"
    fake = _FakeGA4(_ga4_result())
    monkeypatch.setattr("hermes_seo_agent.cli.AnalyticsClient", lambda c: fake)
    rc = _cmd_ga4(argparse.Namespace(action="status", days=28), _config(db))
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["summary"]["canonical_urls"] == 1
    assert out["summary"]["unmatched"] == 0
    assert out["ga4_status"]["property_id"] == "123456789"


def test_ga4_collect_stores_and_marks_partial(monkeypatch, capsys, tmp_path):
    db = tmp_path / "ga4-cli.db"
    result = _ga4_result(
        rows=[{
            "url": "https://www.unicorniohater.com.br/post/",
            "domain_valid": True, "matched_sitemap": True,
            "sessions": 100.0, "engaged_sessions": 60.0,
            "engagement_rate": 0.6, "engagement_time": 1200.0,
            "key_events": 5.0, "measurement_status": "available",
        }],
        unmatched=[{"landing": "https://evil.example.com/x/",
                    "reason": "domain mismatch"}],
    )
    fake = _FakeGA4(result)
    monkeypatch.setattr("hermes_seo_agent.cli.AnalyticsClient", lambda c: fake)

    class _FakeStatic:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def all_sitemap_urls(self):
            return ["https://www.unicorniohater.com.br/post/"]

    monkeypatch.setattr("hermes_seo_agent.cli.StaticSiteClient", lambda c: _FakeStatic())

    args = argparse.Namespace(action="collect", days=28, store=True, limit=0)
    rc = _cmd_ga4(args, _config(db))
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["summary"]["run_status"] == "partial"
    assert out["summary"]["rows_matched"] == 1
    assert out["summary"]["rows_unmatched"] == 1
    with Storage(str(db)) as storage:
        m = storage.ga4_metrics_for_url("https://www.unicorniohater.com.br/post/")
        assert m["sessions"] == 100.0
        health = storage.ga4_collection_health()["organic_landing"]
        assert health and health[0]["rows_unmatched"] == 1


def test_ga4_collect_without_store_persists_nothing(monkeypatch, capsys, tmp_path):
    db = tmp_path / "ga4-nostore.db"
    fake = _FakeGA4(_ga4_result())
    monkeypatch.setattr("hermes_seo_agent.cli.AnalyticsClient", lambda c: fake)

    class _FakeStatic:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def all_sitemap_urls(self):
            return []

    monkeypatch.setattr("hermes_seo_agent.cli.StaticSiteClient", lambda c: _FakeStatic())

    args = argparse.Namespace(action="collect", days=28, store=False, limit=0)
    rc = _cmd_ga4(args, _config(db))
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["summary"]["stored"] is False
    with Storage(str(db)) as storage:
        assert storage.ga4_collection_health()["organic_landing"] == []


def test_ga4_report_calibration(monkeypatch, capsys, tmp_path):
    db = tmp_path / "ga4-calib.db"
    fake = _FakeGA4(_ga4_result())
    monkeypatch.setattr("hermes_seo_agent.cli.AnalyticsClient", lambda c: fake)
    monkeypatch.setattr("hermes_seo_agent.cli.SearchConsoleClient",
                        lambda c: _FakeGSC([{
                            "keys": ["https://www.unicorniohater.com.br/post/"],
                            "clicks": 5, "impressions": 500, "ctr": 0.01,
                            "position": 4.0,
                        }]))

    args = argparse.Namespace(action="report", days=28, limit=50, store=False)
    rc = _cmd_ga4(args, _config(db))
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    calib = out["calibration"][0]
    assert calib["url"] == "https://www.unicorniohater.com.br/post/"
    assert calib["gsc_clicks"] == 5
    assert calib["ga4_organic_sessions"] == 100.0
    assert calib["coverage"] == "matched"


def test_ga4_requires_property_in_cli(monkeypatch, capsys):
    db = "/tmp/ga4-noprop.db"
    config = Config(wordpress_url="http://localhost", sqlite_path=db)
    rc = _cmd_ga4(argparse.Namespace(action="status", days=28), config)
    out = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert "GA4_PROPERTY_ID" in out["error"]
