"""Tests for fail-closed config parsing."""

import pytest

from hermes_seo_agent.config import ConfigError, load_config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("WORDPRESS_URL", "WORDPRESS_API_BASE", "WORDPRESS_APP_USER",
                "WORDPRESS_APP_PASSWORD", "STATIC_SITE_URL", "SITEMAP_URL",
                "DRY_RUN", "GOOGLE_API_KEY", "PAGESPEED_API_KEY",
                "CRUX_API_KEY", "GA4_PROPERTY_ID", "GOOGLE_APPLICATION_CREDENTIALS"):
        monkeypatch.delenv(key, raising=False)
    # Point the .env loader at a missing file so a local .env never leaks in.
    monkeypatch.setenv("SEO_ENV_FILE", "/nonexistent/seo-agent.env")


def test_defaults_are_dry_run():
    cfg = load_config()
    assert cfg.dry_run is True
    assert cfg.wordpress_url == "http://wordpress.dvl.to:8080"


def test_write_mode_requires_credentials(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    with pytest.raises(ConfigError):
        load_config()


def test_write_mode_accepts_credentials(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("WORDPRESS_APP_USER", "u")
    monkeypatch.setenv("WORDPRESS_APP_PASSWORD", "p")
    cfg = load_config()
    assert cfg.app_user == "u"


def test_invalid_url_rejected(monkeypatch):
    monkeypatch.setenv("WORDPRESS_URL", "not-a-url")
    with pytest.raises(ConfigError):
        load_config()


def test_api_base_safety(monkeypatch):
    monkeypatch.setenv("WORDPRESS_API_BASE", "/wp-json/wp/v2?evil=1")
    with pytest.raises(ConfigError):
        load_config()


def test_google_api_key_fallback_for_pagespeed_and_crux(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaSy-fallback-key")
    cfg = load_config()
    assert cfg.pagespeed_api_key == "AIzaSy-fallback-key"
    assert cfg.crux_api_key == "AIzaSy-fallback-key"


def test_specific_keys_override_google_api_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaSy-fallback-key")
    monkeypatch.setenv("PAGESPEED_API_KEY", "AIzaSy-psi-key")
    cfg = load_config()
    assert cfg.pagespeed_api_key == "AIzaSy-psi-key"
    assert cfg.crux_api_key == "AIzaSy-fallback-key"


def test_gsc_site_url_accepts_domain_property(monkeypatch):
    monkeypatch.setenv("GSC_SITE_URL", "sc-domain:unicorniohater.com.br")
    cfg = load_config()
    assert cfg.gsc_site_url == "sc-domain:unicorniohater.com.br"


def test_gsc_site_url_rejects_invalid(monkeypatch):
    monkeypatch.setenv("GSC_SITE_URL", "sc-domain:")
    with pytest.raises(ConfigError):
        load_config()
