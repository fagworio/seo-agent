"""Tests for M3 — entities, topic graph and cluster coverage."""

from hermes_seo_agent.report.topics import (
    build_topic_graph,
    canonical_entity,
    cluster_coverage,
    normalize_entity,
)
from hermes_seo_agent.storage.db import Storage


def _seed(storage: Storage) -> None:
    # corpus com entidades
    storage.replace_corpus_entities("https://x.com/op1/", [
        {"entity": "one piece", "entity_type": "franchise", "count": 5},
        {"entity": "luffy", "entity_type": "term", "count": 3},
    ])
    storage.replace_corpus_entities("https://x.com/op2/", [
        {"entity": "One Piece", "entity_type": "franchise", "count": 4},
    ])
    storage.replace_corpus_entities("https://x.com/jjk1/", [
        {"entity": "jujutsu kaisen", "entity_type": "franchise", "count": 6},
    ])
    # inventário (indexabilidade + frescor)
    storage.save_corpus_document(
        url="https://x.com/op1/", title="OP 1", h1="", body_text="x",
        is_noindex=0, status_code=200, built_at="2026-01-01T00:00:00+00:00")
    storage.save_corpus_document(
        url="https://x.com/op2/", title="OP 2", h1="", body_text="x",
        is_noindex=1, status_code=200, built_at="2026-01-02T00:00:00+00:00")
    # GSC: query citando a entidade
    storage.save_query_pages(
        [{"query": "one piece luffy", "url": "https://x.com/op1/",
          "impressions": 800, "clicks": 20, "ctr": 0.025, "position": 2.5,
          "intent": "informational"}],
        window_start="2026-02-01", window_end="2026-02-28",
    )
    storage.conn.commit()


def test_normalize_and_canonical():
    assert normalize_entity("One Piece!") == "one piece"
    assert normalize_entity("JUJUTSU KAISEN") == "jujutsu kaisen"
    assert canonical_entity("jjk") == "jujutsu kaisen"
    assert canonical_entity("One Piece") == "one piece"


def test_topic_graph_merges_corpus_and_gsc(tmp_path):
    with Storage(tmp_path / "t.db") as storage:
        _seed(storage)
        graph = build_topic_graph(storage)
        entities = {c["entity"]: c for c in graph}
        # corpus "One Piece" e "one piece" normalizam para o mesmo cluster
        assert entities["one piece"]["urls"] == ["https://x.com/op1/", "https://x.com/op2/"]
        assert entities["one piece"]["corpus_urls"] == 2
        # jjk: 1 URL só do corpus
        assert entities["jujutsu kaisen"]["urls"] == ["https://x.com/jjk1/"]


def test_cluster_coverage_fields(tmp_path):
    with Storage(tmp_path / "t2.db") as storage:
        _seed(storage)
        cov = cluster_coverage(storage, "one piece")
        assert cov["entity"] == "one piece"
        assert cov["posts"] == 2
        assert cov["indexable_urls"] == 1          # op2 é noindex
        assert cov["impressions"] == 800.0
        assert cov["clicks"] == 20.0
        assert cov["top3_queries"] == 1            # posição 2.5
        assert cov["top10_queries"] == 1
        assert cov["ga4_status"] == "missing"      # sem GA4 persistido
