"""Sprint 2 — lanes independentes, claim/lease/fencing e retry classificado.

Cada teste aqui é um dos cenários de aceitação do Sprint 2. A regra central:

    NENHUMA lane espera outra terminar.
    NENHUM item ruim segura o lote.
    NENHUM worker possui uma tarefa para sempre.
    NENHUMA escrita é repetida após crash.
"""
from __future__ import annotations

from hermes_seo_agent.lanes import LaneQueue, policy as P
from hermes_seo_agent.lanes.queue import MAX_RECOVERIES
from hermes_seo_agent.storage.db import Storage

LANE = P.LANE_TITLE_EXECUTION
T0 = "2026-09-29T12:00:00+00:00"
T_LATE = "2026-09-29T12:10:00+00:00"          # 600s depois de T0
LEASE = 300                                    # segundos


# --- identidade estável ------------------------------------------------------

def test_work_item_key_e_estavel_e_distinto():
    """A identidade é determinística (não autoincrement): mesmo trabalho, mesmo id."""
    a = P.work_item_key(P.LANE_AUDIT, "https://x/1")
    b = P.work_item_key(P.LANE_AUDIT, "https://x/1")
    c = P.work_item_key(P.LANE_AUDIT, "https://x/2")
    d = P.work_item_key(P.LANE_DEAD_URL, "https://x/1")
    assert a == b, "mesma entrada tem de gerar o mesmo id"
    assert a != c and a != d
    assert a.startswith("audit:")


def test_enqueue_e_idempotente_e_nao_reabre_item_terminal(tmp_path):
    with Storage(str(tmp_path / "enq.db")) as store:
        q = LaneQueue(store)
        assert q.enqueue(LANE, "wi-1", url="https://x/1", now=T0) is True
        assert q.enqueue(LANE, "wi-1", url="https://x/1", now=T0) is False

        item = q.claim(LANE, "w1", now=T0)[0]
        q.complete("wi-1", "w1", item["lease_version"], now=T0)
        # enfileirar de novo NÃO reabre um item já concluído
        assert q.enqueue(LANE, "wi-1", url="https://x/1", now=T_LATE) is False
        assert q.get("wi-1")["status"] == P.ST_DONE


# --- 1. claim exclusivo ------------------------------------------------------

def test_worker_b_nao_consegue_pegar_o_item_do_worker_a(tmp_path):
    """Aceitação: worker A claim item -> worker B não executa o mesmo item."""
    with Storage(str(tmp_path / "excl.db")) as store:
        q = LaneQueue(store)
        q.enqueue(LANE, "wi-1", url="https://x/1", now=T0)

        batch_a = q.claim(LANE, "worker-A", now=T0)
        assert [i["work_item_id"] for i in batch_a] == ["wi-1"]
        # B olha a mesma lane no mesmo instante: não vê nada
        assert q.claim(LANE, "worker-B", now=T0) == []
        # e B não pode concluir o item de A nem com o token certo
        assert q.complete("wi-1", "worker-B", batch_a[0]["lease_version"],
                          now=T0) is False


# --- 2. crash recovery -------------------------------------------------------

def test_lease_expirado_volta_para_a_fila_e_outro_worker_retoma(tmp_path):
    """Aceitação: worker A morre -> lease expira -> worker B retoma."""
    with Storage(str(tmp_path / "rec.db")) as store:
        q = LaneQueue(store)
        q.enqueue(LANE, "wi-1", url="https://x/1", now=T0)
        q.claim(LANE, "worker-A", now=T0, lease_seconds=LEASE)

        # A morreu: ninguém renova. Antes de expirar, B não pega.
        assert q.claim(LANE, "worker-B", now=T0) == []

        recovered = q.recover_expired(now=T_LATE)
        assert [r["work_item_id"] for r in recovered] == ["wi-1"]
        assert recovered[0]["status"] == P.ST_RETRY

        # B retoma e conclui
        batch_b = q.claim(LANE, "worker-B", now=T_LATE)
        assert len(batch_b) == 1
        assert q.complete("wi-1", "worker-B", batch_b[0]["lease_version"],
                          now=T_LATE) is True
        assert q.get("wi-1")["status"] == P.ST_DONE


def test_worker_morto_nao_deixa_executing_eterno(tmp_path):
    """`executing` órfão também é recuperado — nada fica preso para sempre."""
    with Storage(str(tmp_path / "orphan.db")) as store:
        q = LaneQueue(store)
        q.enqueue(LANE, "wi-1", url="https://x/1", now=T0)
        item = q.claim(LANE, "worker-A", now=T0, lease_seconds=LEASE)[0]
        assert q.mark_executing("wi-1", "worker-A", item["lease_version"], now=T0)
        assert q.get("wi-1")["status"] == P.ST_EXECUTING

        q.recover_expired(now=T_LATE)
        assert q.get("wi-1")["status"] == P.ST_RETRY
        assert q.get("wi-1")["worker_id"] is None
        assert q.claim(LANE, "worker-B", now=T_LATE)


# --- 3. fencing token --------------------------------------------------------

def test_fencing_token_antigo_nao_conclui_nem_grava(tmp_path):
    """Aceitação: worker antigo volta -> token antigo -> não conclui/escreve."""
    with Storage(str(tmp_path / "fence.db")) as store:
        q = LaneQueue(store)
        q.enqueue(LANE, "wi-1", url="https://x/1", now=T0)

        a = q.claim(LANE, "worker-A", now=T0, lease_seconds=LEASE)[0]
        assert a["lease_version"] == 1

        q.recover_expired(now=T_LATE)
        b = q.claim(LANE, "worker-B", now=T_LATE)[0]
        # o recovery incrementa (0/1 -> 2: invalida o token do morto) e o claim
        # incrementa de novo (-> 3). Duas barreiras, não uma.
        assert b["lease_version"] == 3, "recovery + claim incrementam o fencing token"

        # A volta do crash e tenta concluir/gravar com a versão antiga
        assert q.owns_lease("wi-1", "worker-A", a["lease_version"]) is False
        assert q.complete("wi-1", "worker-A", a["lease_version"], now=T_LATE) is False
        failed = q.fail("wi-1", "worker-A", a["lease_version"], "boom", now=T_LATE)
        assert failed["ok"] is False, "o worker antigo não pode nem registrar falha"
        assert q.heartbeat("wi-1", "worker-A", a["lease_version"], now=T_LATE) is False

        # o item continua com B, que conclui normalmente
        assert q.owns_lease("wi-1", "worker-B", b["lease_version"]) is True
        assert q.complete("wi-1", "worker-B", b["lease_version"], now=T_LATE) is True


def test_item_que_derruba_workers_nao_derruba_para_sempre(tmp_path):
    """Proteção extra: o item que mata todo worker vai para `manual_review`."""
    with Storage(str(tmp_path / "kill.db")) as store:
        q = LaneQueue(store)
        q.enqueue(LANE, "wi-assassino", url="https://x/1", now=T0)

        t = T0
        for i in range(MAX_RECOVERIES):
            batch = q.claim(LANE, f"worker-{i}", now=t, lease_seconds=60)
            assert len(batch) == 1, f"claim {i} deveria pegar o item"
            t = P.plus_seconds(t, 120)          # o worker morre, o lease expira
            q.recover_expired(now=t)

        assert q.get("wi-assassino")["status"] == P.ST_MANUAL_REVIEW
        assert q.claim(LANE, "worker-final", now=P.plus_seconds(t, 3600)) == []


# --- 4. retry/backoff classificado ------------------------------------------

def test_retryable_agenda_backoff_e_nao_repete_imediatamente(tmp_path):
    """Nada de 'falhou -> tenta de novo já': o retry tem hora marcada."""
    with Storage(str(tmp_path / "backoff.db")) as store:
        q = LaneQueue(store)
        q.enqueue(LANE, "wi-b", url="https://x/1", now=T0)
        item = q.claim(LANE, "w1", now=T0)[0]

        res = q.fail("wi-b", "w1", item["lease_version"],
                     "ConnectionError: timeout", now=T0)
        assert res["status"] == P.ST_RETRY
        assert res["error_class"] == P.ERR_RETRYABLE
        assert res["attempt_count"] == 1
        assert res["next_attempt_at"] > T0

        # agora ninguém pega (nem outro worker)
        assert q.claim(LANE, "w2", now=T0) == []
        # depois do backoff, volta a ser elegível
        later = P.plus_seconds(T0, P.backoff_seconds(1, seed="wi-b") + 1)
        assert len(q.claim(LANE, "w2", now=later)) == 1


def test_esgotar_tentativas_manda_para_manual_review_sem_loop(tmp_path):
    with Storage(str(tmp_path / "max.db")) as store:
        q = LaneQueue(store)
        q.enqueue(LANE, "wi-x", url="https://x/1", max_attempts=3, now=T0)

        t = T0
        for i in range(1, 4):
            item = q.claim(LANE, f"w{i}", now=t)[0]
            res = q.fail("wi-x", f"w{i}", item["lease_version"], "timeout 503", now=t)
            if i < 3:
                assert res["status"] == P.ST_RETRY
                t = P.plus_seconds(t, P.backoff_seconds(i, seed="wi-x") + 1)
            else:
                assert res["status"] == P.ST_MANUAL_REVIEW, "não pode ficar em loop"
        assert q.claim(LANE, "w-final", now=P.plus_seconds(t, 86400)) == []


def test_erro_stale_nao_reexecuta(tmp_path):
    """A ação já foi aplicada: reexecutar seria a escrita duplicada."""
    with Storage(str(tmp_path / "stale.db")) as store:
        q = LaneQueue(store)
        q.enqueue(LANE, "wi-s", url="https://x/1", now=T0)
        item = q.claim(LANE, "w1", now=T0)[0]

        res = q.mark_stale("wi-s", "w1", item["lease_version"],
                           reason="already executed (idempotent)", now=T0)
        assert res["status"] == P.ST_STALE
        assert q.claim(LANE, "w2", now=P.plus_seconds(T0, 86400)) == []


def test_erro_terminal_sai_da_fila_para_sempre(tmp_path):
    """404/410 permanentes não voltam todo ciclo para a fila normal."""
    with Storage(str(tmp_path / "term.db")) as store:
        q = LaneQueue(store)
        q.enqueue(P.LANE_DEAD_URL, "dead-1", url="https://x/post-1/", now=T0)
        item = q.claim(P.LANE_DEAD_URL, "w1", now=T0)[0]

        res = q.fail("dead-1", "w1", item["lease_version"], "gone 410",
                     error_class=P.ERR_TERMINAL, now=T0)
        assert res["status"] == P.ST_TERMINAL
        assert q.claim(P.LANE_DEAD_URL, "w2", now=P.plus_seconds(T0, 86400)) == []
        assert q.enqueue(P.LANE_DEAD_URL, "dead-1", now=T_LATE) is False


def test_classifica_erros_e_backoff_e_deterministico():
    from hermes_seo_agent.executor.executor import StaleActionError

    assert P.classify_error(StaleActionError("mudou")) == P.ERR_STALE
    assert P.classify_error("ReadTimeout: timed out") == P.ERR_RETRYABLE
    assert P.classify_error("HTTPError: 503 unavailable") == P.ERR_RETRYABLE
    assert P.classify_error("unauthorized 401") == P.ERR_MANUAL_REVIEW
    assert P.classify_error("boom desconhecido") == P.ERR_RETRYABLE

    # determinístico e crescente, limitado pelo teto
    assert P.backoff_seconds(1, seed="x") == P.backoff_seconds(1, seed="x")
    assert P.backoff_seconds(2, seed="x") > P.backoff_seconds(1, seed="x")
    assert P.backoff_seconds(20, seed="x") <= P.RETRY_MAX_SECONDS


# --- 5. isolamento entre lanes ----------------------------------------------

def test_falha_de_uma_lane_nao_para_as_outras(tmp_path):
    """Aceitação: dead_url falha -> title continua; title falha -> audit continua."""
    with Storage(str(tmp_path / "iso.db")) as store:
        q = LaneQueue(store)

        q.enqueue(P.LANE_DEAD_URL, "dead-1", url="https://x/morto", now=T0)
        for i in range(3):
            q.enqueue(LANE, f"tit-{i}", url=f"https://x/{i}", now=T0)
        q.enqueue(P.LANE_AUDIT, "aud-1", url="https://x/1", now=T0)

        # o worker de dead_url explode
        d = q.claim(P.LANE_DEAD_URL, "w-dead", now=T0)[0]
        q.fail("dead-1", "w-dead", d["lease_version"], "HTTPError: 500", now=T0)

        # title segue intocada e elegível
        assert q.pending_count(LANE, now=T0) == 3
        titulos = q.claim(LANE, "w-title", limit=10, now=T0)
        assert len(titulos) == 3

        # o worker de title também explode
        q.fail(titulos[0]["work_item_id"], "w-title", titulos[0]["lease_version"],
               "boom 502", now=T0)

        # audit continua elegível — nenhuma lane espera a outra
        assert q.pending_count(P.LANE_AUDIT, now=T0) == 1
        assert len(q.claim(P.LANE_AUDIT, "w-audit", now=T0)) == 1

        # e o snapshot separa as lanes
        snap = q.stats_all(now=T0)
        assert snap[P.LANE_AUDIT]["claimed"] == 1
        assert snap[P.LANE_DEAD_URL]["retry"] == 1
        assert snap[LANE]["retry"] == 1


def test_falha_de_um_item_nao_interrompe_o_lote(tmp_path):
    """Aceitação: URL 1 falha -> URL 2, 3 e 4 continuam."""
    with Storage(str(tmp_path / "batch.db")) as store:
        q = LaneQueue(store)
        for i in range(4):
            q.enqueue(LANE, f"wi-{i}", url=f"https://x/{i}", now=T0)

        batch = q.claim(LANE, "w1", limit=4, now=T0)
        assert len(batch) == 4

        concluidos, falhados = 0, 0
        for item in batch:
            if item["url"].endswith("/0"):
                q.fail(item["work_item_id"], "w1", item["lease_version"],
                       "HTTPError: 503", now=T0)
                falhados += 1
            else:
                assert q.complete(item["work_item_id"], "w1",
                                  item["lease_version"], now=T0) is True
                concluidos += 1

        assert (concluidos, falhados) == (3, 1)
        assert q.get("wi-0")["status"] == P.ST_RETRY      # só ele voltou
        assert [q.get(f"wi-{i}")["status"] for i in (1, 2, 3)] == [P.ST_DONE] * 3


# --- 6. observabilidade ------------------------------------------------------

def test_stats_expoe_oldest_pending_age_e_leases_expirados(tmp_path):
    """A métrica que denuncia deadlock novo: idade do pendente mais antigo."""
    with Storage(str(tmp_path / "stats.db")) as store:
        q = LaneQueue(store)
        q.enqueue(LANE, "wi-old", url="https://x/1", now=T0)

        snap = q.stats(lane=LANE, now=T_LATE)
        assert snap["pending"] == 1
        assert snap["oldest_pending_age_seconds"] == 600
        assert snap["expired_leases"] == 0

        q.claim(LANE, "w1", now=T_LATE, lease_seconds=LEASE)
        snap2 = q.stats(lane=LANE, now=P.plus_seconds(T_LATE, 400))
        assert snap2["claimed"] == 1
        assert snap2["expired_leases"] == 1, "lease vencido é sinal de worker morto"
        assert snap2["oldest_pending_age_seconds"] is None
        assert snap2["oldest_claimed_age_seconds"] == 400


def test_lane_limit_e_configuravel_por_lane():
    """Backpressure independente: ajustar uma lane não mexe nas outras."""
    class _Cfg:
        lane_limits = {P.LANE_TITLE_EXECUTION: 7}
        lane_limit_audit = 3

    assert P.lane_limit(P.LANE_TITLE_EXECUTION, _Cfg()) == 7
    assert P.lane_limit(P.LANE_AUDIT, _Cfg()) == 3
    # sem configuração, cai no default próprio da lane
    assert P.lane_limit(P.LANE_MEASUREMENT, None) == \
        P.DEFAULT_LANE_LIMITS[P.LANE_MEASUREMENT]
    assert P.lane_limit(P.LANE_AUDIT, None) == 200
