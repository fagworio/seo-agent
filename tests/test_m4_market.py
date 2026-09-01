"""Tests for M4 — MarketIntelligenceProvider contract and corpus check."""

from hermes_seo_agent.services.market_intelligence import (
    MarketIntelligenceProvider,
    NoopProvider,
    get_provider,
)
from hermes_seo_agent.storage.db import Storage


class _FakeProvider(MarketIntelligenceProvider):
    name = "fake"
    cost_per_call_cents = 25
    config_key = "FAKE_KEY"

    def keyword_metrics(self, keyword, *, limit=10):
        return [{"keyword": keyword, "volume": 1000, "difficulty": 0.4}]

    def keyword_suggestions(self, seed, *, limit=20):
        return [{"keyword": f"{seed} x", "volume": 100}]

    def competitor_gap(self, topic, *, limit=10):
        return [{"keyword": topic, "gap": True}]

    def serp_snapshot(self, keyword, *, limit=10):
        return [{"url": "https://competitor.com/a/", "position": 1}]

    def trend_signal(self, keyword):
        return {"trend": "rising", "delta_pct": 12.5}


def test_noop_provider_never_fabricates():
    p = NoopProvider(None)
    assert p.keyword_metrics("x") == []          # ausência ≠ zero
    assert p.trend_signal("x") == {}
    # factory default agora é scrape (frontend público, sem credencial)
    assert get_provider(None).name == "trends_scrape"


def test_evidence_includes_cost_quota_origin():
    p = _FakeProvider(None)
    ev = p._evidence("gojo", method="keyword_metrics",
                     rows=p.keyword_metrics("gojo"), quota={"used": 1})
    assert ev["provider"] == "fake"
    assert ev["cost_cents"] == 25
    assert ev["quota"] == {"used": 1}
    assert ev["data_status"] == "available"
    assert ev["collected_at"]
    # sem linhas -> missing (nunca "zero métricas")
    ev2 = p._evidence("x", method="keyword_metrics", rows=[])
    assert ev2["data_status"] == "missing"
    assert ev2["cost_cents"] == 0


def _seed_corpus(storage: Storage) -> None:
    from hermes_seo_agent.corpus.builder import build_corpus
    from hermes_seo_agent.connectors.static_site import PageSnapshot
    page = PageSnapshot("https://x.com/op/", 200)
    page.title = "Guia de One Piece"
    page.h1 = ["Guia de One Piece"]
    page.body_text = "One Piece é um anime sobre Luffy e os Chapéus de Palha."
    page.html = "<h1>Guia de One Piece</h1><p>Luffy navega.</p>"
    build_corpus(storage, [page], built_at="2026-01-01T00:00:00+00:00")


def test_candidate_checks_corpus_before_action(tmp_path):
    db = tmp_path / "m.db"
    with Storage(str(db)) as storage:
        _seed_corpus(storage)
        p = _FakeProvider(None)
        # keyword coberta pelo corpus -> expand_existing (nunca new_content)
        covered = p.candidate(storage, "one piece", method="keyword_metrics",
                              external=p.keyword_metrics("one piece"))
        assert covered["corpus_covers"] is True
        assert covered["suggested_action"] == "expand_existing"
        assert covered["needs_human_review"] is True
        assert covered["external_evidence"]["provider"] == "fake"
        # keyword nova -> new_content (candidato, nunca pauta automática)
        fresh = p.candidate(storage, "exterminador do futuro 4k", method="keyword_metrics")
        assert fresh["corpus_covers"] is False
        assert fresh["suggested_action"] == "new_content"
        assert fresh["needs_human_review"] is True


def test_candidate_without_external_data_is_safe(tmp_path):
    db = tmp_path / "m2.db"
    with Storage(str(db)) as storage:
        _seed_corpus(storage)
        p = NoopProvider(None)
        c = p.candidate(storage, "one piece", method="keyword_metrics")
        assert c["internal"]["internal_docs"] >= 1
        assert "external_evidence" not in c  # sem fonte externa não há evidência
        assert c["suggested_action"] == "expand_existing"
