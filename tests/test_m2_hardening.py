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
        rid = storage.start_corpus_run(total_urls=5, sitemap_total=100,
                                       sitemap_signature="sig1")
        storage.update_corpus_run(rid, processed=3, changed=2, failed=1)
        storage.record_corpus_failure(rid, "https://x.com/fail/", "timeout")
        storage.finish_corpus_run(rid, status="partial")
        summary = storage.corpus_run_summary()
        assert summary["runs"][0]["status"] == "partial"
        assert summary["runs"][0]["processed"] == 3
        assert summary["runs"][0]["changed"] == 2
        assert summary["runs"][0]["failed"] == 1
        assert summary["runs"][0]["sitemap_total"] == 100  # sitemap completo
        assert summary["last_run_failure_count"] == 1
        assert summary["last_run_failures"][0]["url"] == "https://x.com/fail/"


def test_corpus_queue_cursor_and_resume(tmp_path):
    """A fila por URL é o cursor: re-executar retoma os pending, não recomeça
    do prefixo do sitemap (o que o usuário apontou como pendência crítica)."""
    db = tmp_path / "queue.db"
    with Storage(str(db)) as storage:
        rid = storage.start_corpus_run(total_urls=6, sitemap_total=6,
                                       sitemap_signature="s")
        urls = [f"https://x.com/p{i}/" for i in range(6)]
        storage.corpus_enqueue_urls(rid, urls)
        # processa 2 lotes (4 URLs) e 'cai'
        for _ in range(4):
            pending = storage.corpus_claim_pending(rid, limit=1)
            storage.corpus_mark_done(rid, pending[0])
        assert storage.corpus_queue_counts(rid) == {"pending": 2, "done": 4,
                                                    "failed": 0}
        # retomada: claim pega só os pending restantes (cursor real)
        remaining = storage.corpus_claim_pending(rid, limit=10)
        assert remaining == ["https://x.com/p4/", "https://x.com/p5/"]
        # enfileirar de novo é idempotente (UNIQUE run+url)
        storage.corpus_enqueue_urls(rid, urls)
        assert storage.corpus_queue_counts(rid)["pending"] == 2
        # falha por URL fica registrada na fila
        storage.corpus_mark_failed(rid, "https://x.com/p4/", "boom")
        assert storage.corpus_queue_counts(rid)["failed"] == 1


def test_global_coverage_independent_of_batch(tmp_path):
    """Cobertura GLOBAL usa o sitemap completo do run, não o total do lote —
    um run limitado não infla a cobertura (o bug apontado)."""
    db = tmp_path / "gcov.db"
    with Storage(str(db)) as storage:
        build_corpus(storage, [_page()], built_at="2026-01-01T00:00:00+00:00")
        # lote de 2 URLs, mas sitemap completo = 100
        rid = storage.start_corpus_run(total_urls=2, sitemap_total=100,
                                       sitemap_signature="full")
        storage.finish_corpus_run(rid, status="ok")
        cov = storage.corpus_global_coverage()
        assert cov["global_sitemap_total"] == 100
        assert cov["global_coverage_pct"] == 1.0   # 1 doc / 100, não 50%
        assert "sitemap completo" in cov["basis"]


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
        # sem registro no inventory -> NÃO é stale; é não-verificável
        assert report["staleness"] == 0
        assert report["unverifiable_docs"] == 1


def test_staleness_detects_changed_content(tmp_path):
    db = tmp_path / "stale.db"
    with Storage(str(db)) as storage:
        build_corpus(storage, [_page(body="versão 1")], built_at="2026-01-01T00:00:00+00:00")
        # inventory com o MESMO hash -> não stale
        storage.save_editorial_inventory(
            [_page(body="versão 1")], crawled_at="2026-01-01T00:00:00+00:00")
        assert storage.corpus_coverage_report()["staleness"] == 0
        # inventory com hash DIFERENTE -> corpus fica stale (conteúdo mudou)
        storage.save_editorial_inventory(
            [_page(body="versão 2 ATUALIZADA")], crawled_at="2026-01-02T00:00:00+00:00")
        report = storage.corpus_coverage_report()
        assert report["staleness"] == 1
        assert report["unverifiable_docs"] == 0


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
    assert out["summary"]["sitemap_total"] == 2      # sitemap completo registrado
    assert out["summary"]["queue"] == {"pending": 0, "done": 1, "failed": 1}
    with Storage(str(db)) as storage:
        summary = storage.corpus_run_summary()
        assert summary["runs"][0]["status"] == "partial"
        assert summary["last_run_failures"][0]["url"] == "https://x.com/b/"


def test_rebuild_resumes_queue_not_restarts(monkeypatch, capsys, tmp_path):
    """Retomada REAL: se há um run running com fila pendente, o próximo rebuild
    processa só os pending (não recomeça do prefixo nem re-processa os done)."""
    db = tmp_path / "resume.db"
    calls: list[str] = []

    class _FakeStatic:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def all_sitemap_urls(self):
            return ["https://x.com/a/", "https://x.com/b/", "https://x.com/c/"]

        def fetch_page(self, url):
            calls.append(url)
            return _page(url=url)

    monkeypatch.setattr("hermes_seo_agent.cli.StaticSiteClient", lambda c: _FakeStatic())
    config = Config(wordpress_url="http://localhost", sqlite_path=str(db))

    # 1º run: processa a, b e 'cai' antes de c (simula: c fica pending)
    import hashlib
    sitemap = ["https://x.com/a/", "https://x.com/b/", "https://x.com/c/"]
    signature = hashlib.sha256("\n".join(sitemap).encode("utf-8")).hexdigest()[:16]
    with Storage(str(db)) as storage:
        rid = storage.start_corpus_run(total_urls=3, sitemap_total=3,
                                       sitemap_signature=signature)
        storage.corpus_enqueue_urls(rid, sitemap)
        for u in ("https://x.com/a/", "https://x.com/b/"):
            storage.corpus_mark_done(rid, u)
        storage.update_corpus_run(rid, processed=2, changed=2, failed=0)
        # run permanece 'running' (queda simulada)

    # 2º rebuild: retoma o MESMO run e processa só o pending (c)
    args = argparse.Namespace(action="rebuild", limit=0)
    rc = _cmd_corpus(args, config)
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["summary"]["resumed"] is True
    assert out["summary"]["run_status"] == "ok"
    assert out["summary"]["queue"]["pending"] == 0
    # a e b NÃO foram refetchados no retomada (já done); só c foi pendente
    resumed_calls = calls[-1:]
    assert resumed_calls == ["https://x.com/c/"]
    assert len(calls) == 1  # apenas o pending foi processado


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
