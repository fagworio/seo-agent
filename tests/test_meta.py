"""Tests for deterministic meta/canonical checks."""

from hermes_seo_agent.checks.meta import (
    canonical_findings,
    duplicate_title_findings,
    meta_findings,
)
from hermes_seo_agent.connectors.static_site import PageSnapshot


def _page(url="https://www.unicorniohater.com.br/a/", **kw):
    p = PageSnapshot(url=url, status_code=200)
    for key, value in kw.items():
        setattr(p, key, value)
    return p


def test_meta_missing_title_and_desc():
    findings = meta_findings(_page())
    rules = {f["rule_id"] for f in findings}
    assert "title_missing" in rules
    assert "meta_missing" in rules


def test_meta_too_long():
    findings = meta_findings(_page(title="T" * 80, meta_description="D" * 200))
    rules = {f["rule_id"] for f in findings}
    assert "title_too_long" in rules
    assert "meta_too_long" in rules


def test_canonical_missing():
    findings = canonical_findings(_page(canonical=""))
    assert findings[0]["rule_id"] == "canonical_missing"


def test_canonical_conflict():
    findings = canonical_findings(_page(canonical="https://www.unicorniohater.com.br/other/"),
                                  expected_canonical="https://www.unicorniohater.com.br/a/")
    assert findings[0]["rule_id"] == "canonical_conflict"


def test_duplicate_titles():
    pages = [
        _page("https://www.unicorniohater.com.br/a/", title="Same Title"),
        _page("https://www.unicorniohater.com.br/b/", title="Same  Title!"),
        _page("https://www.unicorniohater.com.br/c/", title="Unique"),
    ]
    findings = duplicate_title_findings(pages)
    assert len(findings) == 1
    assert findings[0]["rule_id"] == "title_duplicate"
    assert len(findings[0]["urls"]) == 2
