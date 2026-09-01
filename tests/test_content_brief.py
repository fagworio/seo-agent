"""Tests for advisory, evidence-backed content recommendations."""

from hermes_seo_agent.connectors.static_site import PageSnapshot
from hermes_seo_agent.report.content_brief import build_content_brief, cannibalization_suggestions


def _page(**values):
    page = PageSnapshot("https://example.com/post/", 200)
    page.title = "Guia de Gojo"
    page.h1 = ["Guia de Gojo"]
    page.h2s = ["Resumo"]
    page.body_text = "Um texto curto sobre o personagem."
    page.links = []
    for key, value in values.items():
        setattr(page, key, value)
    return page


def test_brief_identifies_query_alignment_and_question_gap():
    brief = build_content_brief(_page(), [{
        "keys": ["quantos anos tem o gojo"], "impressions": 200,
        "clicks": 2, "position": 8,
    }])
    items = {item["item"] for item in brief["suggestions"]}
    assert "query_title_alignment" in items
    assert "question_gap" in items
    assert "content_depth" in items


def test_brief_does_not_recommend_internal_links_when_present():
    brief = build_content_brief(_page(
        body_text="palavra " * 200,
        links=["/outro-artigo/"],
    ), [])
    assert brief["signals"]["internal_link_count"] == 1
    assert "internal_linking" not in {item["item"] for item in brief["suggestions"]}


def test_cannibalization_is_a_review_signal_with_related_urls():
    first = {"url": "https://example.com/a/", "content_brief": {"signals": {
        "queries_considered": [{"query": "gojo idade", "impressions": 30}],
    }}}
    second = {"url": "https://example.com/b/", "content_brief": {"signals": {
        "queries_considered": [{"query": "gojo idade", "impressions": 20}],
    }}}
    result = cannibalization_suggestions([first, second])
    assert result[first["url"]][0]["item"] == "possible_cannibalization"
    assert result[first["url"]][0]["related_urls"] == [second["url"]]
