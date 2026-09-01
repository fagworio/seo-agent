"""Tests for deterministic sitemap diff."""

from hermes_seo_agent.tools.sitemap_diff import sitemap_diff


def test_diff_added_removed_common():
    a = ["https://www.unicorniohater.com.br/a/", "https://www.unicorniohater.com.br/b/"]
    b = ["https://www.unicorniohater.com.br/b/", "https://www.unicorniohater.com.br/c/"]
    diff = sitemap_diff(a, b)
    assert diff.added == ["/c/"]
    assert diff.removed == ["/a/"]
    assert diff.common == ["/b/"]
    assert diff.summary() == {"added": 1, "removed": 1, "common": 1}


def test_diff_host_agnostic():
    """Comparing local vs prod sitemaps must match by path, not host."""
    a = ["http://localhost:8081/a"]
    b = ["https://www.unicorniohater.com.br/a/"]
    diff = sitemap_diff(a, b)
    assert diff.common == ["/a/"]
    assert diff.added == []
    assert diff.removed == []
