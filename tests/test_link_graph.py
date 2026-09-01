"""Tests for E0 internal link graph (deterministic)."""

from hermes_seo_agent.connectors.static_site import PageSnapshot
from hermes_seo_agent.tools.link_graph import build_graph, is_editorial_target, resolve_links


def _page(url, links):
    p = PageSnapshot(url, 200)
    p.links = links
    return p


def test_is_editorial_target_filters_assets_and_utility():
    assert is_editorial_target("https://x.com/post-a/")
    assert is_editorial_target("https://x.com/")
    assert not is_editorial_target("https://x.com/assets/img.webp")
    assert not is_editorial_target("https://x.com/wp-content/uploads/a.jpg")
    assert not is_editorial_target("https://x.com/autor/joao/")
    assert not is_editorial_target("https://x.com/contato/")
    assert not is_editorial_target("https://x.com/buscar/?q=x")


def test_resolve_links_absolutizes_and_skips_external():
    links = ["/post-b/", "https://other.com/x/", "post-c/"]
    resolved = resolve_links("https://x.com/post-a/", links)
    assert "https://x.com/post-b/" in resolved
    assert "https://x.com/post-a/post-c/" in resolved  # relativo à pasta da página
    assert "https://other.com/x/" in resolved  # kept (external), filtered later by key


def test_build_graph_counts_in_out_and_orphans():
    pages = [
        _page("https://x.com/a/", ["https://x.com/b/", "https://x.com/assets/logo.png"]),
        _page("https://x.com/b/", ["https://x.com/c/"]),
        _page("https://x.com/c/", []),
        _page("https://x.com/d/", []),
    ]
    graph = build_graph(pages)
    assert graph["in_counts"]["/b/"] == 1
    assert graph["in_counts"]["/c/"] == 1
    assert graph["out_counts"]["/a/"] == 1  # asset filtered
    # d has no in-links -> orphan (original URL preserved in the report)
    assert "https://x.com/d/" in graph["orphans"]
    # hubs ordenados por in_links desc
    assert graph["hubs"][0][1] == 1


def test_build_graph_excludes_self_links():
    pages = [
        _page("https://x.com/a/", ["https://x.com/a/", "https://x.com/b/"]),
        _page("https://x.com/b/", []),
    ]
    graph = build_graph(pages)
    assert graph["out_counts"]["/a/"] == 1  # self excluded
