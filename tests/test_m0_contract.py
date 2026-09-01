"""Tests for M0 — data contract, provenance and integration status."""

import pytest

from hermes_seo_agent.config import Config
from hermes_seo_agent.report.data_status import (
    attach_provenance,
    merge_status,
    normalize_status,
    provenance,
)
from hermes_seo_agent.services.integration_status import IntegrationStatusService
from hermes_seo_agent.storage.db import Storage


def test_normalize_status_canonical():
    assert normalize_status("available") == "available"
    assert normalize_status("ok") == "available"
    assert normalize_status("partial") == "partial"
    assert normalize_status("empty") == "missing"
    assert normalize_status(None) == "missing"
    assert normalize_status("error") == "invalid"
    assert normalize_status("weird") == "invalid"


def test_merge_status_rules():
    assert merge_status("available", "available") == "available"
    assert merge_status("available", "partial") == "partial"
    assert merge_status("available", "missing") == "missing"
    assert merge_status("partial", "missing") == "missing"
    assert merge_status("available", "invalid") == "invalid"


def test_provenance_block():
    p = provenance(source="ga4", window_start="2026-01-01", window_end="2026-01-28",
                   collected_at="2026-01-29", coverage=0.95,
                   limitations="coleta semanal")
    assert p["source"] == "ga4"
    assert p["data_status"] == "available"
    assert p["window"] == {"start": "2026-01-01", "end": "2026-01-28"}
    assert p["coverage"] == 0.95

    with pytest.raises(ValueError):
        provenance(source="nope")


def test_attach_provenance():
    m = attach_provenance({"sessions": 10.0}, source="ga4", data_status="partial")
    assert m["sessions"] == 10.0
    assert m["provenance"]["source"] == "ga4"
    assert m["provenance"]["data_status"] == "partial"


def _config(db_path) -> Config:
    return Config(wordpress_url="http://localhost",
                  static_site_url="https://www.unicorniohater.com.br",
                  sqlite_path=str(db_path))


def test_integration_status_all_sources_present(tmp_path):
    db = tmp_path / "int.db"
    with Storage(str(db)) as storage:
        # GA4 com dados -> available; GSC sem dados -> missing
        storage.save_ga4_page_metrics(
            [{"url": f"https://www.unicorniohater.com.br/p{i}/", "sessions": 10.0,
              "engaged_sessions": 5.0, "engagement_rate": 0.5,
              "measurement_status": "available"} for i in range(150)],
            window_start="2026-01-01", window_end="2026-01-28",
            source_scope="organic_landing",
        )
        config = _config(db)
        config = Config(
            wordpress_url="http://localhost",
            static_site_url="https://www.unicorniohater.com.br",
            google_credentials="fake", ga4_property_id="123",
            crux_api_key="key",
            sqlite_path=str(db),
        )
        service = IntegrationStatusService(config, storage)
        statuses = {s.source: s for s in service.check()}
        assert set(statuses) == {"wordpress", "sitemap", "gsc", "ga4", "crux", "external"}
        assert statuses["ga4"].data_status == "available"
        assert statuses["gsc"].data_status == "missing"     # sem query_pages
        assert statuses["crux"].configured is True
        # M4: default scrape (frontend público) -> external configurada
        assert statuses["external"].configured is True
        assert statuses["external"].extras["provider"] == "trends_scrape"


def test_integration_status_unconfigured_sources(tmp_path):
    db = tmp_path / "int2.db"
    with Storage(str(db)) as storage:
        config = _config(db)  # sem credenciais
        service = IntegrationStatusService(config, storage)
        statuses = {s.source: s for s in service.check()}
        assert statuses["ga4"].data_status == "missing"
        assert statuses["gsc"].data_status == "missing"
        assert statuses["ga4"].detail == "GA4_PROPERTY_ID vazio"


def test_config_limits_defaults_and_env(monkeypatch):
    monkeypatch.delenv("MAX_QUERIES_PER_SOURCE", raising=False)
    monkeypatch.delenv("EXTERNAL_BUDGET_CENTS", raising=False)
    from hermes_seo_agent.config import load_config
    monkeypatch.setenv("SEO_ENV_FILE", "/nonexistent")
    monkeypatch.setenv("SQLITE_PATH", "/tmp/seo-m0.db")
    monkeypatch.setenv("WORDPRESS_URL", "http://x")
    cfg = load_config()
    assert cfg.max_queries_per_source == 500
    assert cfg.external_budget_cents == 0
    monkeypatch.setenv("MAX_QUERIES_PER_SOURCE", "99")
    monkeypatch.setenv("EXTERNAL_BUDGET_CENTS", "1234")
    cfg2 = load_config()
    assert cfg2.max_queries_per_source == 99
    assert cfg2.external_budget_cents == 1234


def test_integration_status_external_with_trends(tmp_path):
    """M4: Trends configurado (scrape ou api) deixa external não-missing."""
    db = tmp_path / "int-trends.db"
    with Storage(str(db)) as storage:
        config = Config(
            wordpress_url="http://localhost",
            static_site_url="https://www.unicorniohater.com.br",
            trends_api_key="trends-key",
            sqlite_path=str(db),
        )
        service = IntegrationStatusService(config, storage)
        statuses = {s.source: s for s in service.check()}
        ext = statuses["external"]
        assert ext.configured is True
        assert ext.data_status == "partial"      # configurado, aguardando call live
        assert ext.extras["provider"] == "trends_scrape"
        assert ext.extras["cost_per_call_cents"] == 0
