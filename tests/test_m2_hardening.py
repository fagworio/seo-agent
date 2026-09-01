"""Tests for M2 hardening — corpus incremental com checkpoint, failures e coverage."""

import argparse
import json

from hermes_seo_agent.cli import _cmd_corpus
from hermes_seo_agent.config import Config
from hermes_seo_agent.connectors.static_site import PageSnapshot
from hermes_seo_agent.corpus.builder import build_corpus
from hermes_seo_agent.storage.db import Storage


def _page(url="https://x.com/a/", body="conteúdo do artigo A"):
    page = PageSnapshot(url, 200)
    page.title = "Artigo A"
    page.h1 = ["Artigo A"]
    page.body_text = body
    page.html = f"<h1>Artigo A</h1><p>{body}</p>"
    page.meta_robots = ""
    page.canonical = url
    return page


def test_run_checkpoint_and_failures(tmp_path):
    db = tmp_path / "run.db"
    with Storage(str(db)) as storage:
        rid = storage.start_corpus_run(total_urls=5)
        storage.update_corpus_run(rid, processed=3, changed=2, failed=1)
        storage.record_corpus_failure(rid, "https://x.com/fail/", "timeout")
        storage.finish_corpus_run(rid, status="partial")
        summary = storage.corpus_run_summary()
        assert summary["runs"][0]["status"] == "partial"
        assert summary["runs"][0]["processed"] == 3
        assert summary["runs"][0]["changed"] == 2
        assert summary["runs"][0]["failed"] == 1
        assert summary["last_run_failure_count"] == 1
        assert summary["last_run_failures"][0]["url"] == "https://x.com/fail/"


def test_coverage_report_matches_sitemap(tmp_path):
    db = tmp_path / "cov.db"
    with Storage(str(db)) as storage:
        build_corpus(storage, [_page()], built_at="2026-01-01T00:00:00+00:00")
        report = storage.corpus_coverage_report(
            sitemap_urls=["https://x.com/a/", "https://x.com/b/"])
        assert report["indexed_docs"] == 1
        assert report["sitemap_total"] == 2
        assert report["sitemap_without_corpus"] == 1     # b ainda não indexado
        assert report["corpus_outside_sitemap"] == 0
        assert report["coverage_pct"] == 50.0
        # staleness: sem inventory correspondente -> doc conta como stale
        assert report["staleness"] == 1


def test_staleness_detects_changed_content(tmp_path):
    db = tmp_path / "stale.db"
    with Storage(str(db)) as storage:
        build_corpus(storage, [_page(body="versão 1")], built_at="2026-01-01T00:00:00+00:00")
        # inventory com o MESMO hash -> não stale
        storage.save_corpus_document(
            url="https://x.com/a/", title="Artigo A", h1="Artigo A",
            body_text="versão 1", content_hash="same", built_at="2026-01-01T00:00:00+00:00")
        # inventory com hash DIFERENTE -> corpus fica stale
        storage.save_corpus_document(
            url="https://x.com/a/", title="Artigo A", h1="Artigo A",
            body_text="versão 2 ATUALIZADA", content_hash="new-hash",
            built_at="2026-01-02T00:00:00+00:00")
        report = storage.corpus_coverage_report()
        assert report["staleness"] == 1


def test_rebuild_cli_records_run_and_failures(monkeypatch, capsys, tmp_path):
    db = tmp_path / "cli.db"

    class _FakeStatic:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def all_sitemap_urls(self):
            return ["https://x.com/a/", "https://x.com/b/"]

        def fetch_page(self, url):
            if url.endswith("/b/"):
                raise ConnectionError("boom")
            return _page(url=url)

    monkeypatch.setattr("hermes_seo_agent.cli.StaticSiteClient", lambda c: _FakeStatic())
    config = Config(wordpress_url="http://localhost", sqlite_path=str(db))
    args = argparse.Namespace(action="rebuild", limit=0)
    rc = _cmd_corpus(args, config)
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["summary"]["processed"] == 1
    assert out["summary"]["failed"] == 1
    assert out["summary"]["run_status"] == "partial"
    with Storage(str(db)) as storage:
        summary = storage.corpus_run_summary()
        assert summary["runs"][0]["status"] == "partial"
        assert summary["last_run_failures"][0]["url"] == "https://x.com/b/"


def test_rebuild_is_incremental_across_runs(monkeypatch, capsys, tmp_path):
    db = tmp_path / "inc.db"

    class _FakeStatic:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def all_sitemap_urls(self):
            return ["https://x.com/a/"]

        def fetch_page(self, url):
            return _page(url=url)

    monkeypatch.setattr("hermes_seo_agent.cli.StaticSiteClient", lambda c: _FakeStatic())
    config = Config(wordpress_url="http://localhost", sqlite_path=str(db))
    args = argparse.Namespace(action="rebuild", limit=0)

    assert _cmd_corpus(args, config) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["summary"]["changed"] == 1

    # segundo rebuild: conteúdo idêntico -> 0 mudanças
    assert _cmd_corpus(args, config) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["summary"]["processed"] == 1
    assert second["summary"]["changed"] == 0
