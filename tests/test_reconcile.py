"""Tests for the three-way reconciliation logic (pure, deterministic).

Comparison keys are path-only (host-independent), because the WordPress host
differs from the static host.
"""

from hermes_seo_agent.inventory.reconcile import (
    normalize_url,
    reconcile,
    wp_link_to_static,
)


def test_normalize_url_is_path_only():
    assert normalize_url("https://www.unicorniohater.com.br/game/x/") == "/game/x/"
    assert normalize_url("HTTP://UnicornioHater.com.br/game/x") == "/game/x/"
    assert normalize_url("https://unicorniohater.com.br/game/x?page=2#a") == "/game/x/"
    assert normalize_url("http://wordpress.dvl.to:8080/game/x/") == "/game/x/"


def test_wp_link_to_static_maps_host():
    assert wp_link_to_static("http://wordpress.dvl.to:8080/game/x/", "www.unicorniohater.com.br") == \
        "http://www.unicorniohater.com.br/game/x/"


def test_reconcile_missing_from_sitemap():
    posts = [{"link": "https://www.unicorniohater.com.br/post-a/"}, {"link": "https://www.unicorniohater.com.br/post-b/"}]
    sitemap = ["https://www.unicorniohater.com.br/post-a/"]
    report = reconcile(posts, sitemap)
    assert report.in_sitemap == ["/post-a/"]
    assert report.missing_from_sitemap == ["/post-b/"]


def test_reconcile_orphan_in_sitemap():
    posts = [{"link": "https://www.unicorniohater.com.br/post-a/"}]
    sitemap = ["https://www.unicorniohater.com.br/post-a/", "https://www.unicorniohater.com.br/ghost/"]
    report = reconcile(posts, sitemap)
    assert report.orphan_in_sitemap == ["/ghost/"]


def test_reconcile_wp_static_mismatch():
    posts = [{"link": "https://www.unicorniohater.com.br/post-a/"}]
    sitemap = ["https://www.unicorniohater.com.br/post-a/"]
    static = ["https://www.unicorniohater.com.br/"]
    report = reconcile(posts, sitemap, static_urls=static)
    assert len(report.wp_static_mismatch) == 1
    assert report.wp_static_mismatch[0]["expected_static"] == "https://www.unicorniohater.com.br/post-a/"


def test_reconcile_wp_host_agnostic():
    """WP links carry the internal host; reconciliation matches by path."""
    posts = [{"link": "http://wordpress.dvl.to:8080/post-a/"}]
    sitemap = ["https://www.unicorniohater.com.br/post-a/"]
    report = reconcile(posts, sitemap)
    assert report.in_sitemap == ["/post-a/"]
    assert report.missing_from_sitemap == []
