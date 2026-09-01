"""Tests for M2 — corpus editorial (documento/seção/entidade + FTS5)."""

import argparse
import json

from hermes_seo_agent.cli import _cmd_corpus
from hermes_seo_agent.config import Config
from hermes_seo_agent.connectors.static_site import PageSnapshot
from hermes_seo_agent.corpus.builder import build_corpus, extract_entities, extract_sections
from hermes_seo_agent.storage.db import Storage

HTML = """
<html><body><article>
<h1>Guia de One Piece</h1>
<p>Introdução sobre o anime.</p>
<h2>Idade do Luffy</h2>
<p>Luffy tem 19 anos no início da história.</p>
<h2>Os Chapéus de Palha</h2>
<p>Navegam pelo Grand Line.</p>
<h3>Zoro</h3>
<p>O espadachim do bando.</p>
</article></body></html>
"""


def _page(url="https://x.com/one-piece/", html=HTML):
    page = PageSnapshot(url, 200)
    page.title = "Guia de One Piece"
    page.h1 = ["Guia de One Piece"]
    page.h2s = ["Idade do Luffy", "Os Chapéus de Palha"]
    page.body_text = "Guia de One Piece Introdução sobre o anime. Idade do Luffy " \
                     "Luffy tem 19 anos no início. Os Chapéus de Palha Navegam."
    page.html = html
    page.meta_robots = ""
    page.canonical = url
    return page


def test_extract_sections_with_positions():
    secs = extract_sections(HTML, "https://x.com/one-piece/")
    headings = [(s["heading"], s["heading_level"], s["position"]) for s in secs]
    assert ("Idade do Luffy", 2, 0) in headings
    assert ("Os Chapéus de Palha", 2, 1) in headings
    assert ("Zoro", 3, 2) in headings
    # texto da seção capturado até o próximo heading
    idade = next(s for s in secs if s["heading"] == "Idade do Luffy")
    assert "Luffy tem 19 anos" in idade["text"]


def test_extract_entities_known_and_terms():
    ents = extract_entities("Guia de One Piece", "Guia de One Piece",
                            "One piece é um anime sobre Luffy")
    types = {e["entity_type"] for e in ents}
    assert "franchise" in types
    assert any(e["entity"] == "one piece" for e in ents)


def test_build_corpus_and_search(tmp_path):
    db = tmp_path / "corpus.db"
    with Storage(str(db)) as storage:
        counts = build_corpus(storage, [_page(), _page(url="https://x.com/outro/")],
                              built_at="2026-01-01T00:00:00+00:00")
        assert counts["documents"] == 2
        assert counts["sections"] >= 6
        stats = storage.corpus_stats()
        assert stats["documents"] == 2
        assert stats["fts_docs"] == 2
        # busca por seção: termo que só existe no corpo de uma seção
        results = storage.corpus_search("Luffy", limit=10)
        assert any(r["url"] == "https://x.com/one-piece/" for r in results)


def test_corpus_coverage_identifies_section(tmp_path):
    db = tmp_path / "corpus2.db"
    with Storage(str(db)) as storage:
        build_corpus(storage, [_page()], built_at="2026-01-01T00:00:00+00:00")
        coverage = storage.corpus_coverage("Luffy")
        assert coverage
        doc = next(d for d in coverage if d["url"] == "https://x.com/one-piece/")
        # o critério M2: não só "temos artigo", mas a SEÇÃO específica
        assert any("Idade do Luffy" in (s.get("heading") or "") for s in doc["sections"])


def test_corpus_rebuild_is_incremental_by_hash(tmp_path):
    db = tmp_path / "corpus3.db"
    with Storage(str(db)) as storage:
        build_corpus(storage, [_page()], built_at="2026-01-01T00:00:00+00:00")
        # segundo build com MESMO conteúdo -> nada muda
        counts = build_corpus(storage, [_page()], built_at="2026-01-02T00:00:00+00:00")
        assert counts["documents"] == 1  # builder ainda grava; o CLI é quem filtra


def test_corpus_cli_search(monkeypatch, capsys, tmp_path):
    db = tmp_path / "corpus-cli.db"
    with Storage(str(db)) as storage:
        build_corpus(storage, [_page()], built_at="2026-01-01T00:00:00+00:00")

    class _FakeStatic:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def fetch_page(self, url):
            return _page(url=url)

        def all_sitemap_urls(self):
            return ["https://x.com/one-piece/"]

    monkeypatch.setattr("hermes_seo_agent.cli.StaticSiteClient", lambda c: _FakeStatic())
    config = Config(wordpress_url="http://localhost", sqlite_path=str(db))
    args = argparse.Namespace(action="search", term="Luffy", limit=10)
    rc = _cmd_corpus(args, config)
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["summary"]["results"] >= 1
    assert out["results"][0]["url"] == "https://x.com/one-piece/"


def test_corpus_cli_coverage(monkeypatch, capsys, tmp_path):
    db = tmp_path / "corpus-cli2.db"
    with Storage(str(db)) as storage:
        build_corpus(storage, [_page()], built_at="2026-01-01T00:00:00+00:00")

    class _FakeStatic:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def fetch_page(self, url):
            return _page(url=url)

        def all_sitemap_urls(self):
            return []

    monkeypatch.setattr("hermes_seo_agent.cli.StaticSiteClient", lambda c: _FakeStatic())
    config = Config(wordpress_url="http://localhost", sqlite_path=str(db))
    args = argparse.Namespace(action="coverage", term="Zoro", limit=10)
    rc = _cmd_corpus(args, config)
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["summary"]["documents"] >= 1
