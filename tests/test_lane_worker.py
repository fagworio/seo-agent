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
        # limit=0 (ilimitado) + max_items=5: o teto do chamador manda
        run = LaneWorker(store, LANE, worker_id="w", handler=lambda i: {"ok": 1},
                         heartbeat=False, recover_first=False,
                         limit=0, max_items=5).run()
    assert run.claimed == 5
    with Storage(db) as store:
        assert LaneQueue(store).stats(lane=LANE)["pending"] == 5


def test_teto_da_lane_limita_a_rodada(tmp_path):
    """O teto da lane e o "por ciclo" do backpressure: limita a RODADA inteira.

    Se fosse por lote, o worker em loop levaria a lane toda e o teto nao valeria.
    """
    db = str(tmp_path / "tetolane.db")
    _povoar(db, LANE, 10)
    with Storage(db) as store:
        run = LaneWorker(store, LANE, worker_id="w", handler=lambda i: {"ok": 1},
                         heartbeat=False, recover_first=False,
                         limit=3).run()
        st = LaneQueue(store).stats(lane=LANE)
    assert run.claimed == 3, "10 itens com teto 3 => apenas 3 nesta rodada"
    assert st["pending"] == 7


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


# ---------------------------------------------------------------------------
# 5. correcoes da revisao (P1.1, P1.2, P1.3, P1.4, P2)
# ---------------------------------------------------------------------------

class _Cfg:
    """Config minima: o worker le `lane_limits` / `lane_limit_<lane>`."""
    def __init__(self, **kw):
        self.lane_limits = kw.pop("lane_limits", {})
        for k, v in kw.items():
            setattr(self, k, v)


def test_p11_lane_limit_vem_da_config(tmp_path):
    """P1.1 — o teto por lane tem de sair da CONFIG, nao do default do mapa."""
    db = str(tmp_path / "cfg.db")
    _povoar(db, LANE, 5)
    with Storage(db) as store:
        # default do mapa para `technical` e 50
        w_default = LaneWorker(store, LANE, handler=lambda i: None)
        assert w_default.limit == 50, "sem config, cai no default do mapa"

        # `lane_limits[lane]` tem precedencia
        cfg = _Cfg(lane_limits={LANE: 2})
        assert LaneWorker(store, LANE, handler=lambda i: None,
                          config=cfg).limit == 2

        # `lane_limit_<lane>` tambem e respeitado
        cfg2 = _Cfg(lane_limit_technical=7)
        assert LaneWorker(store, LANE, handler=lambda i: None,
                          config=cfg2).limit == 7

        # limite explicito continua mandando sobre a config
        assert LaneWorker(store, LANE, handler=lambda i: None, limit=3,
                          config=cfg).limit == 3

        # e o teto da config LIMITA o claim de verdade
        w = LaneWorker(store, LANE, handler=lambda i: {"ok": 1}, config=cfg,
                       heartbeat=False, recover_first=False)
        run = w.run()
        assert run.claimed == 2, "o teto da config tem de valer no claim"
        assert LaneQueue(store).stats(lane=LANE)["pending"] == 3


def test_p12_limit_zero_com_max_items_respeita_o_teto(tmp_path):
    """P1.2 — `limit=0` (ilimitado) + `max_items=5` nao pode levar a fila inteira.

    `min(0, 5) = 0` -> normalizado vira "sem LIMIT" -> levaria os 20.
    """
    db = str(tmp_path / "tetozero.db")
    _povoar(db, LANE, 20)
    with Storage(db) as store:
        run = LaneWorker(store, LANE, worker_id="w", handler=lambda i: {"ok": 1},
                         heartbeat=False, recover_first=False,
                         limit=0, max_items=5).run()
        st = LaneQueue(store).stats(lane=LANE)
    assert run.claimed == 5, "max_items tem de vencer o ilimitado"
    assert st["pending"] == 15, "15 tem de continuar na fila"
    assert st["done"] == 5


def test_p12_teto_composto(tmp_path):
    """O helper `teto()` cobre a composicao sem precisar de banco."""
    db = str(tmp_path / "lote2.db")
    with Storage(db) as store:
        w = LaneWorker(store, LANE, handler=lambda i: None, limit=0)
        assert w.teto(0) is None, "0 = ilimitado quando nao ha max_items"
        w1 = LaneWorker(store, LANE, handler=lambda i: None, limit=0, max_items=5)
        assert w1.teto(0) == 5, "sem limite de lane, max_items manda"
        assert w1.teto(3) == 2, "ja claimados descontam do teto"
        assert w1.teto(5) == 0, "atingiu o teto: nada a fazer"
        assert w1.teto(9) == 0, "nunca negativo"
        w2 = LaneWorker(store, LANE, handler=lambda i: None, limit=3)
        assert w2.teto(0) == 3
        assert w2.teto(1) == 2
        assert w2.teto(3) == 0
        w3 = LaneWorker(store, LANE, handler=lambda i: None, limit=10, max_items=4)
        assert w3.teto(0) == 4, "o menor teto vence"


def test_p13_primeira_renovacao_e_sincronizada(tmp_path):
    """P1.3 — `start()` so libera o handler apos a 1a renovacao CONFIRMADA."""
    from hermes_seo_agent.lanes.worker import _Heartbeat

    # banco inalcancavel: a thread nao consegue renovar -> start() tem de recusar
    hb = _Heartbeat("/proc/nao-existe-dir/x.db", "wi", "w", 1, 2)
    assert hb.start() is False, "sem 1a renovacao confirmada, nao pode liberar"
    assert hb.first_ok is False
    assert hb.error, "o motivo tem de ficar visivel (nao engolido)"
    hb.stop()


def test_p13_handler_nao_roda_sem_posse_confirmada(tmp_path):
    """Se a 1a renovacao falha, o handler NAO e executado e o item fica recuperavel."""
    db = str(tmp_path / "hb_nega.db")
    _povoar(db, LANE, 1)
    efeitos: list[int] = []
    with Storage(db) as store:
        w = LaneWorker(store, LANE, worker_id="w", handler=lambda i: efeitos.append(1),
                       heartbeat=True, recover_first=False, lease_seconds=1)
        # aponta o heartbeat para um banco impossivel, mantendo o do worker
        original = w.store.path
        w.store.path = "/proc/nao-existe-dir/x.db"
        run = w.run()
        w.store.path = original
        st = LaneQueue(store).stats(lane=LANE)
    assert efeitos == [], "handler nao pode rodar sem posse confirmada"
    assert run.lost_lease == 1
    assert run.heartbeat_error, "erro do heartbeat tem de aparecer na telemetria"
    assert st["claimed"] + st["executing"] == 1, (
        "o item NAO pode ficar done: seguiu sob lease para recuperacao bounded")


def test_p14_erro_nao_transitorio_nao_tem_retry():
    """P1.4 — so contencao de SQLite justifica retry; o resto nao se engole."""
    import sqlite3

    from hermes_seo_agent.lanes.worker import _transitorio

    assert _transitorio(sqlite3.OperationalError("database is locked")) is True
    assert _transitorio(sqlite3.OperationalError("database table is busy")) is True
    assert _transitorio(sqlite3.OperationalError("no such table: lane_queue")) is False
    assert _transitorio(sqlite3.DatabaseError("file is not a database")) is False
    assert _transitorio(ValueError("programming error")) is False
    assert _transitorio(RuntimeError("erro interno do LaneQueue")) is False


def test_p2_handler_recebe_ctx_com_o_db_path_do_worker(tmp_path):
    """P2 — o handler age no MESMO banco do worker, nunca em outro."""
    db = str(tmp_path / "ctx.db")
    _povoar(db, LANE, 1)
    visto: dict[str, object] = {}

    def handler(item, ctx):
        visto["db_path"] = ctx.db_path
        visto["lane"] = ctx.lane
        visto["work_item_id"] = ctx.work_item_id
        visto["lease_version"] = ctx.lease_version
        return {"ok": True}

    with Storage(db) as store:
        run = LaneWorker(store, LANE, worker_id="w", handler=handler,
                         heartbeat=False, recover_first=False).run()
        assert run.completed == 1
        assert visto["db_path"] == str(store.path), "ctx tem de carregar o db do worker"
    assert visto["lane"] == LANE
    assert visto["work_item_id"] == "wi-0"
    assert visto["lease_version"] == 1


def test_p2_handler_technical_usa_o_ctx(tmp_path, monkeypatch):
    """O handler real honra o ctx (e nao cai no load_config quando ha ctx)."""
    from hermes_seo_agent.lanes.handlers import handler_technical

    db = str(tmp_path / "tech_ctx.db")
    with Storage(db) as store:                      # cria o schema
        LaneQueue(store).stats(lane=LANE)

    class Ctx:
        db_path = db

    # aponte o env para OUTRO banco: se o handler ignorasse o ctx, iria para la
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "outro_banco.db"))
    out = handler_technical({"work_item_id": "t-1", "payload": {"limit": 5}}, Ctx())
    assert out.get("skip") is True, "banco vazio: nada a reconciliar"
    from pathlib import Path
    assert not Path(tmp_path / "outro_banco.db").exists(), (
        "handler nao pode abrir banco diferente do ctx do worker")
