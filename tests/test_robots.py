"""Tests for robots.txt parsing and blocking rules."""

from hermes_seo_agent.checks.robots import sitemap_urls_blocked
from hermes_seo_agent.connectors.static_site import RobotsRules


def test_robots_parse():
    rules = RobotsRules.parse("https://x.com", "# comment\nDisallow: /private/\nSitemap: https://x.com/sitemap.xml\n")
    assert rules.disallow == ["/private/"]
    assert rules.sitemaps == ["https://x.com/sitemap.xml"]


def test_robots_blocked():
    rules = RobotsRules.parse("https://x.com", "Disallow: /private/\n")
    assert rules.is_blocked("https://x.com/private/page/")
    assert not rules.is_blocked("https://x.com/public/")


def test_sitemap_urls_blocked_filters_noise():
    rules = RobotsRules.parse("https://x.com", "Disallow: /\n")
    urls = [
        "https://x.com/private/page/",
        "https://x.com/wp-admin/admin-ajax.php",
        "https://x.com/feed/rss/",
        "https://x.com/game/review/",
    ]
    blocked = sitemap_urls_blocked(rules, urls)
    urls_blocked = {b["url"] for b in blocked}
    assert urls_blocked == {"https://x.com/private/page/", "https://x.com/game/review/"}
