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
                                                    "failed": 0,
                                                    "in_progress": 0}
        # retomada: claim pega só os pending restantes (cursor real)
        remaining = storage.corpus_claim_pending(rid, limit=10)
        assert remaining == ["https://x.com/p4/", "https://x.com/p5/"]
        # o claim marca in_progress (lease); enfileirar de novo é idempotente
        storage.corpus_enqueue_urls(rid, urls)
        assert storage.corpus_queue_counts(rid)["in_progress"] == 2
        # falha por URL fica registrada na fila
        storage.corpus_mark_failed(rid, "https://x.com/p4/", "boom")
        assert storage.corpus_queue_counts(rid)["failed"] == 1


def test_corpus_claim_is_atomic_lease(tmp_path):
    """Claim ATOMÁTICO: marca in_progress com worker+leased_at; dois claims
    simultâneos pegam lotes disjuntos; leases EXPIRADOS voltam a pending (TTL),
    leases vivos de outro worker NÃO são tocados."""
    db = tmp_path / "lease.db"
    with Storage(str(db)) as storage:
        rid = storage.start_corpus_run(total_urls=6, sitemap_total=6,
                                       sitemap_signature="s")
        urls = [f"https://x.com/p{i}/" for i in range(6)]
        storage.corpus_enqueue_urls(rid, urls)
        # dois 'processos' chamam claim ao mesmo tempo (workers distintos)
        a = storage.corpus_claim_pending(rid, limit=3, worker_id="worker-A")
        b = storage.corpus_claim_pending(rid, limit=3, worker_id="worker-B")
        assert set(a) & set(b) == set()      # disjuntos
        assert sorted(a + b) == sorted(urls)  # cobrem tudo
        counts = storage.corpus_queue_counts(rid)
        assert counts["in_progress"] == 6
        # leases VIVOS (não expirados) não são recuperados, mesmo de outro worker
        assert storage.corpus_recover_expired_leases(
            rid, ttl_seconds=3600, exclude_worker="worker-B") == 0
        assert storage.corpus_queue_counts(rid)["in_progress"] == 6
        # lease EXPiRADO (TTL antigo) volta a pending — só o do worker A
        import datetime as _dt
        past = (_dt.datetime.now(_dt.timezone.utc)
                - _dt.timedelta(seconds=7200)).isoformat()
        storage.conn.execute(
            "UPDATE corpus_queue SET leased_at = ? WHERE worker_id = 'worker-A'",
            (past,),
        )
        storage.conn.commit()
        assert storage.corpus_recover_expired_leases(
            rid, ttl_seconds=3600) == 3
        counts = storage.corpus_queue_counts(rid)
        assert counts["pending"] == 3      # os do A (expirados) voltaram
        assert counts["in_progress"] == 3  # os do B (vivos) permanecem


def test_corpus_recover_excludes_active_worker(tmp_path):
    """O worker atual NÃO rouba seus próprios leases vivos (exclude_worker)
    mesmo quando o TTL é curto — exclusão mútua entre execuções do mesmo
    processo e de processos concorrentes."""
    db = tmp_path / "lease2.db"
    with Storage(str(db)) as storage:
        rid = storage.start_corpus_run(total_urls=2, sitemap_total=2,
                                       sitemap_signature="s")
        storage.corpus_enqueue_urls(rid, ["https://x.com/a/", "https://x.com/b/"])
        storage.corpus_claim_pending(rid, limit=2, worker_id="worker-A")
        # o mesmo worker retoma com TTL curto: excluir o próprio worker
        # preserva os leases que ele acabou de tomar (não se auto-rouba)
        assert storage.corpus_recover_expired_leases(
            rid, ttl_seconds=0, exclude_worker="worker-A") == 0
        assert storage.corpus_queue_counts(rid)["in_progress"] == 2
        # mas um worker concorrente (B) pode recuperar leases de A expirados
        assert storage.corpus_recover_expired_leases(
            rid, ttl_seconds=0, exclude_worker="worker-B") == 2
        assert storage.corpus_queue_counts(rid)["pending"] == 2


def test_heartbeat_renews_lease_prevents_recovery(tmp_path):
    """HEARTBEAT: renovar o leased_at impede que um lease em processamento
    seja recuperado como expirado por outro worker."""
    import datetime as _dt
    db = tmp_path / "hb.db"
    with Storage(str(db)) as storage:
        rid = storage.start_corpus_run(total_urls=1, sitemap_total=1,
                                       sitemap_signature="s")
        storage.corpus_enqueue_urls(rid, ["https://x.com/a/"])
        storage.corpus_claim_pending(rid, limit=1, worker_id="worker-A")
        # envelhece o lease artificialmente, depois faz heartbeat (renova)
        past = (_dt.datetime.now(_dt.timezone.utc)
                - _dt.timedelta(seconds=7200)).isoformat()
        storage.conn.execute(
            "UPDATE corpus_queue SET leased_at = ? WHERE worker_id = 'worker-A'",
            (past,),
        )
        storage.conn.commit()
        assert storage.corpus_renew_lease(rid, ["https://x.com/a/"], "worker-A") == 1
        # com lease renovado, a recuperação por TTL NÃO o pega
        assert storage.corpus_recover_expired_leases(
            rid, ttl_seconds=3600, exclude_worker="worker-B") == 0
        assert storage.corpus_queue_counts(rid)["in_progress"] == 1


def test_mark_requires_lease_owner(tmp_path):
    """done/failed SÓ valem se o worker ainda é o dono: quem perdeu o lease
    (recuperado como expirado por outro) não registra o resultado — evita
    duplicação entre processos."""
    db = tmp_path / "owner.db"
    with Storage(str(db)) as storage:
        rid = storage.start_corpus_run(total_urls=1, sitemap_total=1,
                                       sitemap_signature="s")
        storage.corpus_enqueue_urls(rid, ["https://x.com/a/"])
        storage.corpus_claim_pending(rid, limit=1, worker_id="worker-A")
        # B recupera o lease de A como expirado (A 'morreu')
        import datetime as _dt
        past = (_dt.datetime.now(_dt.timezone.utc)
                - _dt.timedelta(seconds=7200)).isoformat()
        storage.conn.execute(
            "UPDATE corpus_queue SET leased_at = ? WHERE worker_id = 'worker-A'",
            (past,),
        )
        storage.conn.commit()
        assert storage.corpus_recover_expired_leases(rid, ttl_seconds=3600) == 1
        storage.corpus_claim_pending(rid, limit=1, worker_id="worker-B")
        # A tenta concluir a URL que perdeu -> mark retorna False (não registra)
        assert storage.corpus_mark_done(rid, "https://x.com/a/", "worker-A") is False
        # B (dono atual) conclui normalmente
        assert storage.corpus_mark_done(rid, "https://x.com/a/", "worker-B") is True
        assert storage.corpus_queue_counts(rid)["done"] == 1
        # mesmo comportamento para failed
        storage.corpus_enqueue_urls(rid, ["https://x.com/b/"])
        storage.corpus_claim_pending(rid, limit=1, worker_id="worker-C")
        storage.corpus_claim_pending(rid, limit=1, worker_id="worker-D")
        storage.corpus_recover_expired_leases(rid, ttl_seconds=0)
        storage.corpus_claim_pending(rid, limit=1, worker_id="worker-D")
        assert storage.corpus_mark_failed(rid, "https://x.com/b/", "boom",
                                          "worker-C") is False
        assert storage.corpus_mark_failed(rid, "https://x.com/b/", "boom",
                                          "worker-D") is True


def test_global_coverage_independent_of_batch(tmp_path):
    """Cobertura GLOBAL usa a fila-snapshot do sitemap (interseção exata),
    não o total do lote — um run limitado não infla a cobertura."""
    db = tmp_path / "gcov.db"
    with Storage(str(db)) as storage:
        # sitemap completo = 100 URLs; só 1 indexada (https://x.com/0/)
        sitemap = [f"https://x.com/{i}/" for i in range(100)]
        build_corpus(storage, [_page(url="https://x.com/0/")],
                     built_at="2026-01-01T00:00:00+00:00")
        rid = storage.start_corpus_run(total_urls=2, sitemap_total=100,
                                       sitemap_signature="full")
        storage.corpus_enqueue_urls(rid, sitemap)  # snapshot completo na fila
        storage.finish_corpus_run(rid, status="ok")
        cov = storage.corpus_global_coverage()
        assert cov["global_sitemap_total"] == 100
        assert cov["global_coverage_pct"] == 1.0   # 1 doc / 100, não 50%


def test_rebuild_limit_counts_attempts_not_successes(monkeypatch, capsys, tmp_path):
    """O orçamento de --limit é TENTATIVAS: se muitas URLs falham, a execução
    não estoura o limite nem drena a fila de falhas (o bug apontado)."""
    db = tmp_path / "attempt.db"
    fetches: list[str] = []

    class _FakeStatic:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def all_sitemap_urls(self):
            return [f"https://x.com/p{i}/" for i in range(10)]

        def fetch_page(self, url):
            fetches.append(url)
            if int(url.rstrip("/").split("/")[-1][1:]) % 2 == 0:  # pares falham
                raise ConnectionError("boom")
            return _page(url=url)

    monkeypatch.setattr("hermes_seo_agent.cli.StaticSiteClient", lambda c: _FakeStatic())
    config = Config(wordpress_url="http://localhost", sqlite_path=str(db))
    args = argparse.Namespace(action="rebuild", limit=4, resume_id=0)
    rc = _cmd_corpus(args, config)
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    # --limit 4 = 4 TENTATIVAS (2 sucessos + 2 falhas), não 4 sucessos
    assert out["summary"]["attempted_this_run"] == 4
    assert len(fetches) == 4
    assert out["summary"]["processed_this_run"] == 2
    assert out["summary"]["failed_this_run"] == 2
    assert out["summary"]["queue"]["pending"] == 6  # fila não foi drenada


def test_global_coverage_exposes_basis_run_id(tmp_path):
    """A cobertura global expõe coverage_basis_run_id: durante uma execução em
    curso, fica explícito que a base é um run histórico, não o crawl atual."""
    db = tmp_path / "basis.db"
    with Storage(str(db)) as storage:
        sitemap = ["https://x.com/a/"]
        r1 = storage.start_corpus_run(total_urls=1, sitemap_total=1,
                                      sitemap_signature="s1")
        storage.corpus_enqueue_urls(r1, sitemap)
        storage.finish_corpus_run(r1, status="ok")
        cov = storage.corpus_global_coverage()
        assert cov["coverage_basis_run_id"] == r1
        assert cov["coverage_basis_status"] == "ok"
        # run em curso NÃO substitui a base concluída
        r2 = storage.start_corpus_run(total_urls=1, sitemap_total=1,
                                      sitemap_signature="s2")
        storage.corpus_enqueue_urls(r2, ["https://x.com/new/"])
        cov2 = storage.corpus_global_coverage()
        assert cov2["coverage_basis_run_id"] == r1  # ainda o histórico
        assert cov2["coverage_basis_status"] == "ok"


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
    args = argparse.Namespace(action="rebuild", limit=0, resume_id=0)
    rc = _cmd_corpus(args, config)
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["summary"]["processed_this_run"] == 1
    assert out["summary"]["failed_this_run"] == 1
    assert out["summary"]["run_status"] == "partial"
    assert out["summary"]["sitemap_total"] == 2      # sitemap completo registrado
    assert out["summary"]["queue"] == {"pending": 0, "done": 1, "failed": 1,
                                       "in_progress": 0}
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
    args = argparse.Namespace(action="rebuild", limit=0, resume_id=0)
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
    args = argparse.Namespace(action="rebuild", limit=0, resume_id=0)

    assert _cmd_corpus(args, config) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["summary"]["changed_this_run"] == 1

    # segundo rebuild: conteúdo idêntico -> 0 mudanças
    assert _cmd_corpus(args, config) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["summary"]["processed_this_run"] == 1
    assert second["summary"]["changed_this_run"] == 0


def test_rebuild_limit_paginates_advancing_each_run(monkeypatch, capsys, tmp_path):
    """Paginação real de --limit: cada execução processa até N URLs e a
    seguinte CONTINUA de onde parou (não recria o mesmo recorte)."""
    db = tmp_path / "page.db"
    fetches: list[str] = []

    class _FakeStatic:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def all_sitemap_urls(self):
            return [f"https://x.com/p{i}/" for i in range(5)]

        def fetch_page(self, url):
            fetches.append(url)
            return _page(url=url)

    monkeypatch.setattr("hermes_seo_agent.cli.StaticSiteClient", lambda c: _FakeStatic())
    config = Config(wordpress_url="http://localhost", sqlite_path=str(db))
    args = argparse.Namespace(action="rebuild", limit=2, resume_id=0)

    # 1ª execução: processa 2 de 5
    assert _cmd_corpus(args, config) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["summary"]["processed_this_run"] == 2
    assert first["summary"]["finished"] is False        # fila continua
    assert first["summary"]["queue"]["pending"] == 3

    # 2ª execução: CONTINUA (mesmo run) e processa mais 2
    assert _cmd_corpus(args, config) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["summary"]["processed_this_run"] == 2
    assert second["summary"]["resumed"] is True
    assert second["summary"]["queue"]["pending"] == 1

    # 3ª execução: processa o último e finaliza
    assert _cmd_corpus(args, config) == 0
    third = json.loads(capsys.readouterr().out)
    assert third["summary"]["processed_this_run"] == 1
    assert third["summary"]["finished"] is True
    assert third["summary"]["queue"]["pending"] == 0
    assert len(fetches) == 5  # cada URL foi processada exatamente uma vez
