"""Sprint 2 (item 5) — testes dos workers por lane.

Cobrem as regras que a fundação provou obrigatórias, inclusive o caso que falhou
em produção (um único heartbeat não sustenta trabalho mais longo que o lease).
"""
from __future__ import annotations

import time

import pytest

from hermes_seo_agent.lanes import policy as P
from hermes_seo_agent.lanes.queue import LaneQueue
from hermes_seo_agent.lanes.worker import (
    HANDLERS, LaneRun, LaneWorker, SkipItem, register_handler, registered_lanes,
    run_lane,
)
from hermes_seo_agent.storage.db import Storage

LANE = P.LANE_TECHNICAL
LANE2 = P.LANE_MEASUREMENT


@pytest.fixture(autouse=True)
def limpar_registry():
    salvos = dict(HANDLERS)
    yield
    HANDLERS.clear()
    HANDLERS.update(salvos)


def _povoar(db, lane, n, prefixo="wi"):
    with Storage(db) as store:
        q = LaneQueue(store)
        base = P.utc_now()
        for i in range(n):
            q.enqueue(lane, f"{prefixo}-{i}", url=f"https://x/{prefixo}-{i}",
                      payload={"i": i}, now=base)


# ---------------------------------------------------------------------------
# 1. heartbeat: o caso que falhou em produção
# ---------------------------------------------------------------------------

def test_heartbeat_sustenta_trabalho_mais_longo_que_o_lease(tmp_path):
    """Lease de 2s e handler trabalhando 3s: só com heartbeat periódico o
    `complete` é aceito. Sem heartbeat o lease vence e o complete é RECUSADO."""
    db = str(tmp_path / "hb_sim.db")
    _povoar(db, LANE, 1)

    def handler_slow(item):
        time.sleep(3.0)
        return {"ok": True}

    with Storage(db) as store:
        run = LaneWorker(store, LANE, worker_id="w-hb", handler=handler_slow,
                         lease_seconds=2, heartbeat=True, recover_first=False).run()
    assert run.completed == 1, "com heartbeat o lease deve sobreviver ao handler"
    assert run.lost_lease == 0

    # mesma situação, SEM heartbeat -> lease vence e o worker não conclui
    db2 = str(tmp_path / "hb_nao.db")
    _povoar(db2, LANE, 1)
    with Storage(db2) as store:
        run2 = LaneWorker(store, LANE, worker_id="w-nohb", handler=handler_slow,
                          lease_seconds=2, heartbeat=False, recover_first=False).run()
    assert run2.completed == 0, "sem heartbeat o lease vence: não pode concluir"
    assert run2.lost_lease == 1
    with Storage(db2) as store:
        # o item NÃO ficou preso: segue reclamável após recuperação (bounded)
        q = LaneQueue(store)
        rec = q.recover_expired(limit=10)
        assert [r["work_item_id"] for r in rec] == ["wi-0"]


# ---------------------------------------------------------------------------
# 2. fencing antes de qualquer efeito
# ---------------------------------------------------------------------------

def test_posse_perdida_antes_do_handler_nao_gera_efeito(tmp_path):
    """Se a posse cai entre o claim e o mark_executing, o handler NÃO roda."""
    db = str(tmp_path / "fence_pre.db")
    _povoar(db, LANE, 1)
    efeitos: list[str] = []

    with Storage(db) as store:
        q = LaneQueue(store)
        itens = q.claim(LANE, "w1", limit=1, lease_seconds=5)
        wid, v = itens[0]["work_item_id"], itens[0]["lease_version"]
        # outro worker recupera (lease vencido do ponto de vista do relogio)
        with Storage(db) as s2:
            LaneQueue(s2).recover_expired(now=P.plus_seconds(P.utc_now(), 10),
                                          limit=10)

        def handler(item):
            efeitos.append(item["work_item_id"])
            return {"ok": True}

        w = LaneWorker(store, LANE, worker_id="w1", handler=handler,
                       heartbeat=False, recover_first=False)
        run = LaneRun(lane=w.lane, worker_id=w.worker_id)
        w._processar({"work_item_id": wid, "lease_version": v}, run)
        assert efeitos == [], "handler nao pode rodar sem posse"
        assert run.lost_lease == 1
        assert run.completed == 0


def test_fencing_durante_o_handler_nao_conclui(tmp_path):
    """Outro worker recupera o item no meio do handler: o complete é recusado."""
    db = str(tmp_path / "fence_dur.db")
    _povoar(db, LANE, 1)
    recuperados = {}

    def handler(item):
        with Storage(db) as s2:
            recuperados["r"] = LaneQueue(s2).recover_expired(
                now=P.plus_seconds(P.utc_now(), 30), limit=10)
        return {"ok": True}

    with Storage(db) as store:
        run = LaneWorker(store, LANE, worker_id="w-antigo", handler=handler,
                         lease_seconds=5, heartbeat=False,
                         recover_first=False).run()
    assert recuperados["r"], "o outro worker precisa ter recuperado o item"
    assert run.completed == 0, "posse perdida: nao pode concluir"
    assert run.lost_lease == 1


# ---------------------------------------------------------------------------
# 3. isolamento entre itens e entre lanes
# ---------------------------------------------------------------------------

def test_item_ruim_nao_para_o_lote(tmp_path):
    db = str(tmp_path / "lote.db")
    _povoar(db, LANE, 3)

    def handler(item):
        if item["payload"]["i"] == 1:
            raise ValueError("quebrou de proposito")
        return {"ok": True}

    with Storage(db) as store:
        run = LaneWorker(store, LANE, worker_id="w", handler=handler,
                         heartbeat=False, recover_first=False).run()
    assert run.claimed == 3
    assert run.completed == 2, "os outros itens tem de seguir"
    assert run.failed == 1
    with Storage(db) as store:
        st = LaneQueue(store).stats(lane=LANE)
    assert st["done"] == 2


def test_falha_classificada_retryable_vira_retry(tmp_path):
    db = str(tmp_path / "cls.db")
    _povoar(db, LANE, 1)

    def handler(item):
        raise TimeoutError("timed out")

    with Storage(db) as store:
        LaneQueue(store)  # garante schema
        run = LaneWorker(store, LANE, worker_id="w", handler=handler,
                         heartbeat=False, recover_first=False,
                         retry_in=600).run()
    assert run.failed == 1
    with Storage(db) as store:
        row = LaneQueue(store).get("wi-0")
    assert row is not None
    assert row["status"] == P.ST_RETRY
    assert row["error_class"] == P.ERR_RETRYABLE
    assert row["next_attempt_at"] is not None


def test_skip_vira_done_sem_efeito(tmp_path):
    db = str(tmp_path / "skip.db")
    _povoar(db, LANE, 1)

    def handler(item):
        raise SkipItem("nada a aplicar")

    with Storage(db) as store:
        run = LaneWorker(store, LANE, worker_id="w", handler=handler,
                         heartbeat=False, recover_first=False).run()
    assert run.skipped == 1
    assert run.failed == 0
    with Storage(db) as store:
        done_row = LaneQueue(store).get("wi-0")
    assert done_row is not None and done_row["status"] == P.ST_DONE


def test_duas_lanes_nao_se_desafiam(tmp_path):
    """Uma lane com item que quebra não impede a outra de concluir."""
    db = str(tmp_path / "twolanes.db")
    _povoar(db, LANE, 1)

    def handler_ruim(item):
        raise RuntimeError("lane ruim")

    def handler_bom(item):
        return {"ok": True}

    with Storage(db) as store:
        r1 = LaneWorker(store, LANE, worker_id="w1", handler=handler_ruim,
                        heartbeat=False, recover_first=False).run()
    _povoar(db, LANE2, 1, prefixo="m")
    with Storage(db) as store:
        r2 = LaneWorker(store, LANE2, worker_id="w2", handler=handler_bom,
                        heartbeat=False, recover_first=False).run()
    assert r1.failed == 1
    assert r2.completed == 1, "a lane boa nao pode depender da ruim"


# ---------------------------------------------------------------------------
# 4. bounded, recovery e recusa sem handler
# ---------------------------------------------------------------------------

def test_max_items_respeita_o_teto(tmp_path):
    db = str(tmp_path / "teto.db")
    _povoar(db, LANE, 10)
    with Storage(db) as store:
        run = LaneWorker(store, LANE, worker_id="w", handler=lambda i: {"ok": 1},
                         heartbeat=False, recover_first=False,
                         limit=3, max_items=5).run()
    assert run.claimed == 5
    with Storage(db) as store:
        assert LaneQueue(store).stats(lane=LANE)["pending"] == 5


def test_recover_first_devolve_lease_abandonado(tmp_path):
    db = str(tmp_path / "rec.db")
    _povoar(db, LANE, 1)
    with Storage(db) as store:
        q = LaneQueue(store)
        # worker "morto": claim e some, com lease ja vencido
        q.claim(LANE, "w-morto", limit=1, lease_seconds=1)
    time.sleep(1.1)
    with Storage(db) as store:
        run = LaneWorker(store, LANE, worker_id="w-novo",
                         handler=lambda i: {"ok": 1}, recover_first=True,
                         heartbeat=False).run()
    assert run.recovered == 1, "lease abandonado tem de voltar para a fila"
    assert run.completed == 1, "e o worker novo tem de assumir"


def test_worker_sem_handler_recusa(tmp_path):
    db = str(tmp_path / "nohandler.db")
    _povoar(db, LANE, 1)
    with Storage(db) as store:
        with pytest.raises(RuntimeError, match="sem handler registrado"):
            LaneWorker(store, LANE, worker_id="w").run()


def test_run_lane_conveniencia_e_telemetria(tmp_path):
    db = str(tmp_path / "conv.db")
    _povoar(db, LANE, 2)
    register_handler(LANE, lambda i: {"ok": True})
    out = run_lane(db, LANE, worker_id="w-cli", heartbeat=False)
    assert out["completed"] == 2
    assert out["lane"] == LANE
    assert "oldest_pending_age_seconds" in out["stats"], (
        "observabilidade obrigatoria: oldest_pending_age na telemetria")
    assert LANE in registered_lanes()
