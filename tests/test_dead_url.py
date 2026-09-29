"""Sprint 2, item 6 — isolamento de dead URL.

Um teste por criterio de aceite do item, mais a matriz de classificacao. O teste
central e' `test_aceite_1_1900_mortas_nao_reduzem_o_lote`: e' exatamente o bug
operacional que motivou o item (1.900 `/post-N/` 404 drenando o orcamento do audit
e atrasando as URLs saudaveis).
"""
from __future__ import annotations

import pytest

from hermes_seo_agent.lanes import dead_url as DU
from hermes_seo_agent.lanes.handlers import handler_dead_url, register_default_handlers
from hermes_seo_agent.lanes.queue import LaneQueue
from hermes_seo_agent.lanes.worker import LaneWorker, registered_lanes
from hermes_seo_agent.storage.db import Storage

WP = "https://prod.unicorniohater.com.br"
WWW = "https://www.unicorniohater.com.br"


def _morta(store, url, *, status=404, failures=4, in_sitemap=True,
           last_success=None, dirty=1):
    """Insere o estado de auditoria de uma URL morta (o insumo real do audit)."""
    now = "2026-09-29T00:00:00+00:00"
    store.conn.execute(
        "INSERT OR REPLACE INTO url_audit_state (url, wp_post_id, wp_modified, "
        "sitemap_lastmod, last_audited_at, last_success_at, last_status_code, "
        "content_hash, audit_version, dirty, dirty_reason, failure_count, "
        "next_audit_at, created_at, updated_at) "
        "VALUES (?, NULL, NULL, ?, ?, ?, ?, '', 1, ?, 'previous_failure', ?, "
        "        '2026-09-29T00:00:00+00:00', ?, ?)",
        (url, "2026-08-01T00:00:00+00:00" if in_sitemap else None,
         now, last_success, status, dirty, failures, now, now))
    store.conn.commit()


def _saudavel(store, url):
    now = "2026-09-29T00:00:00+00:00"
    store.conn.execute(
        "INSERT OR REPLACE INTO url_audit_state (url, wp_post_id, wp_modified, "
        "sitemap_lastmod, last_audited_at, last_success_at, last_status_code, "
        "content_hash, audit_version, dirty, dirty_reason, failure_count, "
        "next_audit_at, created_at, updated_at) "
        "VALUES (?, NULL, NULL, NULL, ?, ?, 200, '', 1, 0, NULL, 0, ?, ?, ?)",
        (url, now, now, "2026-01-01T00:00:00+00:00", now, now))
    store.conn.commit()


def _wp_post(store, post_id, url):
    store.conn.execute(
        "INSERT OR REPLACE INTO wp_post_state (post_id, url, modified_at, "
        "last_collected_at) VALUES (?, ?, ?, ?)",
        (post_id, url, "2026-01-01T00:00:00+00:00", "2026-09-29T00:00:00+00:00"))
    store.conn.commit()


# ---------------------------------------------------------------------------
# Matriz de classificacao (funcao pura — sem banco, sem rede)
# ---------------------------------------------------------------------------

def test_classifica_transient_para_status_instavel():
    """5xx/timeout nao e' remocao definitiva: nao pode virar `gone`."""
    for status in (500, 502, 503, None, 0):
        d = DU.classify(url=f"{WWW}/x/", status_code=status, failure_count=4,
                        in_sitemap=True, had_success=True)
        assert d.category == "transient", f"status {status} nao e' remocao definitiva"
    assert DU.classify(url="u", status_code=503).back_to_audit is True


def test_classifica_redirect_candidate_quando_existe_no_wp():
    """Conteudo existe no WP atual => slug mudou. Candidato, nunca redirect cego."""
    d = DU.classify(url=f"{WWW}/antigo/", status_code=404, exists_in_wp=True,
                    canonical_url=f"{WWW}/novo/")
    assert d.category == "redirect_candidate"
    assert d.redirect_target == f"{WWW}/novo/"
    assert d.out_of_cycle is True, "sai do ciclo ate' haver evidencia de destino"


def test_classifica_sitemap_cleanup_e_gone():
    """404 estavel e nunca existiu: com fonte sitemap limpa a fonte; sem, sai."""
    com = DU.classify(url=f"{WWW}/post-1/", status_code=404, failure_count=4,
                      in_sitemap=True, had_success=False)
    assert com.category == "sitemap_cleanup"
    sem = DU.classify(url=f"{WWW}/x/", status_code=404, failure_count=4,
                      in_sitemap=False, had_success=False)
    assert sem.category == "gone"


def test_classifica_investigate_quando_existiu_e_sumiu():
    """Ja' respondeu 200 e hoje e' 404: decisao humana, o agente nao apaga sozinho."""
    d = DU.classify(url=f"{WWW}/mat", status_code=404, failure_count=4,
                    in_sitemap=False, had_success=True)
    assert d.category == "investigate"
    assert d.out_of_cycle is True


def test_ordem_das_regras_e_deterministica():
    """`exists_in_wp` vence `had_success`: mesmo 404, categorias diferentes."""
    d = DU.classify(url="u", status_code=404, exists_in_wp=True, had_success=True,
                    in_sitemap=True, failure_count=9)
    assert d.category == "redirect_candidate"


def test_toda_decisao_carrega_motivo_e_evidencia():
    """Aceite 8: classificacao e MOTIVO ficam persistidos/reconstruiveis."""
    d = DU.classify(url="u", status_code=404, failure_count=4, in_sitemap=True)
    assert d.reason and isinstance(d.reason, str) and len(d.reason) > 20
    assert d.evidence["status_code"] == 404
    assert d.evidence["failure_count"] == 4
    assert d.as_dict()["category"] == "sitemap_cleanup"


def test_backoff_do_transient_e_limitado():
    assert DU.backoff_seconds(1) == 3600
    assert DU.backoff_seconds(2) == 6 * 3600
    assert DU.backoff_seconds(99) == 72 * 3600, "teto de 72h, nunca infinito"


def test_path_key_normaliza_encoding_e_host():
    """Slug com zero-width space/emoji percent-encoded e' o MESMO caminho.

    Em producao `url_audit_state` guarda `www.` e `wp_post_state` guarda `prod.`
    para o MESMO portal (medido). Por isso a comparacao e' por CAMINHO — host
    literal daria "nao existe no WP" para toda url do site.
    """
    a = DU._path_key(f"{WWW}/matrix-4-%e2%80%b2-revelados/")
    b = DU._path_key(f"{WP}/matrix-4-′-revelados/")
    assert a == b, "encoding diferente nao pode virar 'pagina morta'"
    assert a == "matrix-4-′-revelados", "o percent-encoding foi resolvido"
    # `_host_key` normaliza apenas o `www.`; `prod.` e' outro host de proposito,
    # e por isso nao entra na comparacao (seria falso negativo em massa).
    assert DU._host_key(WWW) == "unicorniohater.com.br"
    assert DU._host_key(WP) == "prod.unicorniohater.com.br"
    # zero-width space tambem resolve (aparece em slugs reais do portal)
    assert DU._path_key(f"{WWW}/cyber-%e2%80%8bshadow/") == "cyber-\u200bshadow"


# ---------------------------------------------------------------------------
# Acceptance do item
# ---------------------------------------------------------------------------

def test_aceite_1_1900_mortas_nao_reduzem_o_lote(tmp_path):
    """O teste central: 1.900 mortas na fila NAO podem consumir o lote saudavel.

    Antes: elas entram em `previous_failure` e tomam metade do lote todo ciclo.
    Depois de classificadas: zero participacao, e o lote e' 100% saudavel.
    """
    db = str(tmp_path / "dead1.db")
    with Storage(db) as store:
        for i in range(1900):
            _morta(store, f"{WWW}/post-{i}/")
        for i in range(500):
            _saudavel(store, f"{WWW}/noticia-{i}/")

        # ANTES de classificar: elas aparecem e consomem o expresso.
        antes = store.get_urls_for_audit(limit=200)
        mortas_no_lote = [r["url"] for r in antes if "/post-" in r["url"]]
        assert mortas_no_lote, "cenario invalido: as mortas precisam estar elegiveis"

        # Classifica (o que o produtor + handler fazem).
        for i in range(1900):
            u = f"{WWW}/post-{i}/"
            d = DU.plan(store, u)
            assert d.category == "sitemap_cleanup", "as /post-N/ sao limpeza de sitemap"
            store.record_dead_url(url=u, category=d.category, reason=d.reason,
                                  evidence=d.evidence)
            store.apply_dead_url_outcome(url=u, category=d.category,
                                         failure_count=d.evidence["failure_count"])

        depois = store.get_urls_for_audit(limit=200)
        assert len(depois) == 200, "o lote tem de continuar cheio"
        assert not [r for r in depois if "/post-" in r["url"]], (
            "404 conhecida nao pode consumir o orcamento normal de auditoria")
        assert all("/noticia-" in r["url"] for r in depois)

        st = store.dead_url_stats()
        assert st["total"] == 1900
        assert st["por_categoria"]["sitemap_cleanup"] == 1900
        assert st["fora_do_ciclo"] == 1900
        assert st["voltam_ao_audit"] == 0, "aceite 4: so' transient retorna"


def test_aceite_2_dead_url_tem_teto_proprio(tmp_path):
    """A lane tem teto proprio e nao herda o do audit."""
    from hermes_seo_agent.lanes import policy as P

    assert P.lane_limit("dead_url") == 50
    db = str(tmp_path / "dead2.db")
    with Storage(db) as store:
        for i in range(120):
            _morta(store, f"{WWW}/post-{i}/")
        DU.enqueue_dead_urls(store, limit=120)
        register_default_handlers()
        run = LaneWorker(store, "dead_url", worker_id="w", limit=10,
                         heartbeat=False, recover_first=False).run()
        assert run.claimed == 10, "o teto da lane manda, nao a fila"
        assert LaneQueue(store).stats(lane="dead_url")["pending"] == 110


def test_aceite_3_falha_na_dead_url_nao_bloqueia_o_resto(tmp_path):
    """Item ruim na lane nao pode parar o resto: o erro e' do item, nao da lane.

    Dois casos reais: (a) payload incompleto -> `SkipItem` (nao e' falha e nao
    consome tentativa); (b) efeito que EXPLODE -> `fail`, e a lane segue para os
    proximos itens sem parar nada.
    """
    db = str(tmp_path / "dead3.db")
    with Storage(db) as store:
        for i in range(4):
            _morta(store, f"{WWW}/post-{i}/")
        itens = DU.candidates(store, limit=4)
        q = LaneQueue(store)
        itens[1]["payload"] = {"url": None}          # (a) skip
        for it in itens:
            q.enqueue("dead_url", it["work_item_id"], url=it["url"],
                      payload=it["payload"])

        def handler(item, ctx=None):                 # (b) falha real no post-2
            u = str((item.get("payload") or {}).get("url") or "")
            if u.endswith("/post-2/"):
                raise RuntimeError("erro do efeito no item 2")
            return handler_dead_url(item, ctx)

        register_default_handlers()
        run = LaneWorker(store, "dead_url", worker_id="w", handler=handler,
                         heartbeat=False, recover_first=False).run()
        assert run.skipped == 1, "payload incompleto e' skip, nao falha"
        assert run.failed == 1, "excecao no efeito falha SO' aquele item"
        assert run.completed == 2, "os outros itens completam normalmente"
        # o audit segue funcional depois da falha
        assert store.dead_url_state(f"{WWW}/post-0/") is not None
        # e o item que falhou continua na fila (retentavel, nao perdido)
        st = LaneQueue(store).stats(lane="dead_url")
        assert st["pending"] + st["retry"] == 1, "item ruim nao pode sumir"


def test_aceite_4_so_transient_volta_ao_audit(tmp_path):
    """So' `transient` mantem a URL no ciclo, e com backoff."""
    db = str(tmp_path / "dead4.db")
    with Storage(db) as store:
        for cat, url in (("transient", f"{WWW}/t/"), ("gone", f"{WWW}/g/"),
                         ("sitemap_cleanup", f"{WWW}/s/"),
                         ("redirect_candidate", f"{WWW}/r/"),
                         ("investigate", f"{WWW}/i/")):
            _morta(store, url)
            estado = store.apply_dead_url_outcome(url=url, category=cat,
                                                  failure_count=1)
            row = store.conn.execute(
                "SELECT dirty, next_audit_at FROM url_audit_state WHERE url = ?",
                (url,)).fetchone()
            if cat == "transient":
                assert estado == "transient_backoff"
                assert row[0] == 1, "transient continua no ciclo"
                assert row[1] is not None, "com backoff agendado"
            else:
                assert estado.startswith("out_of_cycle"), cat
                assert row[0] == 0, f"{cat} sai do ciclo"
                assert row[1] is None


def test_aceite_5_gone_nao_entra_em_loop(tmp_path):
    """`gone` nao pode voltar nem pelo expresso nem pelo rodizio (P3/P4)."""
    db = str(tmp_path / "dead5.db")
    with Storage(db) as store:
        u = f"{WWW}/post-9/"
        _morta(store, u)
        d = DU.plan(store, u)
        store.record_dead_url(url=u, category=d.category, reason=d.reason,
                              evidence=d.evidence)
        store.apply_dead_url_outcome(url=u, category=d.category,
                                     failure_count=d.evidence["failure_count"])
        # 3 rodadas: nao pode reaparecer em nenhuma
        for _ in range(3):
            vistos = [r["url"] for r in store.get_urls_for_audit(limit=200)]
            assert u not in vistos, "gone reapareceu no audit (loop)"
        assert store.dead_url_candidates(limit=200) == [], (
            "nao pode voltar para a lane de classificacao")


def test_aceite_6_sitemap_cleanup_e_idempotente(tmp_path):
    """Aplicar a mesma limpeza 2x nao pode mudar nada (nem contar 2x)."""
    db = str(tmp_path / "dead6.db")
    with Storage(db) as store:
        u = f"{WWW}/post-7/"
        _morta(store, u)
        d = DU.plan(store, u)
        r1 = store.record_dead_url(url=u, category=d.category, reason=d.reason,
                                   evidence=d.evidence)
        r2 = store.record_dead_url(url=u, category=d.category, reason=d.reason,
                                   evidence=d.evidence)
        assert r1["acao"] == "criado"
        assert r2["acao"] == "inalterado", "2a aplicacao nao muda o registro"
        assert store.dead_url_stats()["por_categoria"]["sitemap_cleanup"] == 1
        # e o efeito no audit tambem e' idempotente
        for _ in range(3):
            store.apply_dead_url_outcome(url=u, category=d.category,
                                         failure_count=4)
        row = store.conn.execute(
            "SELECT dirty, dirty_reason FROM url_audit_state WHERE url = ?",
            (u,)).fetchone()
        assert row[0] == 0 and row[1] == "dead_url:sitemap_cleanup"


def test_aceite_7_mesma_url_nao_gera_trabalho_duplicado(tmp_path):
    """Identidade deterministica: enfileirar 2x e' no-op."""
    db = str(tmp_path / "dead7.db")
    with Storage(db) as store:
        _morta(store, f"{WWW}/post-1/")
        a = DU.enqueue_dead_urls(store, limit=10)
        b = DU.enqueue_dead_urls(store, limit=10)
        assert a["enfileirados"] == 1
        assert b["enfileirados"] == 0, "2o enqueue da mesma URL nao cria item"
        assert LaneQueue(store).stats(lane="dead_url")["pending"] == 1
        # e o id do item e' estavel entre chamadas
        id1 = DU.dead_url_work_item_id(f"{WWW}/post-1/")
        id2 = DU.dead_url_work_item_id(f"{WWW}/post-1/")
        assert id1 == id2 and id1.startswith("dead:")


def test_aceite_8_classificacao_e_motivo_persistidos(tmp_path):
    """A decisao e' auditavel depois: categoria, motivo e evidencia no banco."""
    db = str(tmp_path / "dead8.db")
    with Storage(db) as store:
        u = f"{WWW}/post-3/"
        _morta(store, u)
        DU.enqueue_dead_urls(store, limit=10)
        register_default_handlers()
        run = LaneWorker(store, "dead_url", worker_id="w", heartbeat=False,
                         recover_first=False).run()
        assert run.completed == 1
        st = store.dead_url_state(u)
        assert st is not None
        assert st["category"] == "sitemap_cleanup"
        assert len(st["reason"]) > 20, "o motivo tem de ser legivel"
        assert "sitemap" in st["reason"]
        assert st["evidence_json"] and "404" in st["evidence_json"]
        assert st["action_fingerprint"], "fingerprint da acao persistido"
        assert st["decided_at"]


def test_handler_nao_reanalisa(tmp_path):
    """O handler aplica a decisao do payload; nao recalcula nada no exec."""
    db = str(tmp_path / "dead9.db")
    with Storage(db) as store:
        u = f"{WWW}/post-5/"
        _morta(store, u)
        # decisao FIXA no payload, mesmo divergindo do que o `plan()` diria hoje
        payload = {"url": u, "decision": {
            "url": u, "category": "gone", "reason": "decidido no produtor: 404 fixo",
            "evidence": {"status_code": 404, "failure_count": 4,
                         "in_sitemap": True, "exists_in_wp": False,
                         "had_success": False, "max_attempts": 3},
            "redirect_target": None, "out_of_cycle": True, "back_to_audit": False}}
        register_default_handlers()
        out = handler_dead_url({"work_item_id": "x", "payload": payload},
                               type("C", (), {"db_path": db})())
        assert out["reanalisou"] is False
        assert out["category"] == "gone", "a decisao do payload manda, nao o plan()"
        assert store.dead_url_state(u)["category"] == "gone"


def test_handler_registrado_e_lane_disponivel():
    reg = register_default_handlers()
    assert reg.get("dead_url") == "handler_dead_url"
    assert "dead_url" in registered_lanes()


def test_worker_recusa_lane_sem_handler(tmp_path):
    """Guard do item 5 continua valendo: sem handler, o worker nao improvisa."""
    db = str(tmp_path / "dead10.db")
    with Storage(db) as store:
        w = LaneWorker(store, "lane_sem_handler", worker_id="w", heartbeat=False)
        with pytest.raises(RuntimeError):
            w.run()
