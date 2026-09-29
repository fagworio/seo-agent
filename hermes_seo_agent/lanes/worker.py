"""Sprint 2 (item 5) — workers REAIS por lane.

Um `LaneWorker` consome UMA lane:

    claim -> mark_executing -> [handler] -> complete | fail

Regras que a fundação (Sprint 2.0.1) provou obrigatórias em produção:

1. **Heartbeat periódico, em conexão própria.** Um heartbeat único não sustenta
   trabalho mais longo que o lease: medido em produção, um único heartbeat no meio
   de um `hold` de 6s com lease de 5s fez o lease vencer antes do `complete` — e o
   `complete` foi (corretamente) recusado. O intervalo aqui é `lease/3` e o
   heartbeat roda em THREAD com conexão SQLite SÉPARA: duas threads sobre a mesma
   `Connection` arriscam um commit cruzado (o mesmo defeito do P0.9, que não
   commitava nada).
2. **Fencing a cada passo.** Se `mark_executing`, `heartbeat` ou `complete`
   recusarem, a posse foi perdida (recuperada, roubada ou lease vencido) e o
   worker PARA imediatamente — nunca conclui nem registra sucesso. É essa checagem
   que impede escrita externa depois de perder o lease (Sprint 2, cenário 3).
3. **Worker morto não deixa `executing` eterno**: cada rodada começa com
   `recover_expired` (bounded) — devolve à fila só o que esteve abandonado.
4. **Um item ruim não para o lote**: falha vira `fail` classificado
   (`retryable`/`terminal`/`stale`/`manual_review`) e o loop segue no próximo.
5. **Nenhuma lane espera a outra**: o worker opera só na sua lane; a independência
   vem de serem processos/rodadas separadas.
6. **Falha de infraestrutura não queima o item**: quem sobe `attempt_count` é o
   `fail` do item, não a recuperação de lease (o `recover_expired` consome apenas
   `recoveries`, com teto `MAX_RECOVERIES`).

Não publica nem edita nada por si: o efeito é do `handler` registrado na lane.
Sem handler registrado, o worker RECUSA rodar (não improvisa).
"""
from __future__ import annotations

import os
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from hermes_seo_agent.lanes import policy as P
from hermes_seo_agent.lanes.queue import LaneQueue

__all__ = [
    "Handler", "SkipItem", "LaneRun", "LaneWorker", "HANDLERS",
    "register_handler", "get_handler", "registered_lanes", "default_worker_id",
    "run_lane",
]

Handler = Callable[[dict[str, Any]], Any]


class SkipItem(Exception):
    """O handler avaliou o item e não havia nada a fazer.

    Diferente de falha: o item foi PROCESSADO com sucesso, apenas sem efeito.
    Vira `done` (o worker cumpriu o trabalho: verificar). Uma falha de verdade
    deve ser levantada como exceção normal, para ser classificada.
    """


# lane -> handler. Uma lane sem handler não roda: melhor recusar que improvisar.
HANDLERS: dict[str, Handler] = {}


def register_handler(lane: str, fn: Handler | None = None):
    """Registra o handler de uma lane. Uso como decorator ou chamada direta."""
    def _registrar(f: Handler) -> Handler:
        HANDLERS[lane] = f
        return f
    return _registrar(fn) if fn is not None else _registrar


def get_handler(lane: str) -> Handler | None:
    return HANDLERS.get(lane)


def registered_lanes() -> list[str]:
    return sorted(HANDLERS)


def default_worker_id(lane: str) -> str:
    """Identidade estável o bastante para auditoria: lane + host + pid."""
    return f"{lane}@{socket.gethostname()}:{os.getpid()}"


class _Heartbeat:
    """Renova o lease em thread, com a SUA PRÓPRIA conexão SQLite.

    `lost` vira `True` na primeira renovação recusada (posse perdida): a partir
    daí o worker não pode concluir o item.
    """

    def __init__(self, db_path: str, work_item_id: str, worker_id: str,
                 lease_version: int, lease_seconds: int) -> None:
        self.db_path = db_path
        self.work_item_id = work_item_id
        self.worker_id = worker_id
        self.lease_version = lease_version
        self.lease_seconds = lease_seconds
        # Regra derivada do teste de produção: renovar em <= lease/3.
        self.interval = max(1.0, lease_seconds / 3.0)
        self.lost = False
        self.renovacoes = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _loop(self) -> None:
        from hermes_seo_agent.storage.db import Storage
        try:
            store = Storage(self.db_path)
        except Exception:                                          # noqa: BLE001
            self.lost = True
            return
        try:
            q = LaneQueue(store)
            # Renova IMEDIATAMENTE, antes de rodar o handler. O lease concedido no
            # claim/mark_executing vale `lease_seconds` e a primeira renovação
            # agendada só viria em `lease/3`: sob carga (suite cheia), a thread
            # atrasou mais que isso, o lease venceu e o worker perdeu o item —
            # medido, não teórico. Renovar no t=0 dobra a margem.
            while not self._stop.is_set():
                try:
                    if not q.heartbeat(self.work_item_id, self.worker_id,
                                       self.lease_version,
                                       lease_seconds=self.lease_seconds):
                        self.lost = True
                        return
                    self.renovacoes += 1
                except Exception:                                  # noqa: BLE001
                    # Lock momentâneo: espera o intervalo (não vira busy loop) e
                    # tenta de novo — a próxima janela ainda tem folga de lease/3.
                    if self._stop.wait(self.interval):
                        return
                    continue
                if self._stop.wait(self.interval):
                    return
        finally:
            try:
                store.close()
            except Exception:                                      # noqa: BLE001
                pass

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, name=f"hb-{self.work_item_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(5.0, self.interval * 2))


@dataclass
class LaneRun:
    """Telemetria de uma rodada — inclui `oldest_pending_age_seconds`, a métrica
    principal para detectar deadlock (Sprint 2, observabilidade obrigatória)."""
    lane: str
    worker_id: str
    recovered: int = 0
    claimed: int = 0
    completed: int = 0
    skipped: int = 0
    failed: int = 0
    lost_lease: int = 0
    items_com_erro: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    stats: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "lane": self.lane, "worker_id": self.worker_id,
            "recovered": self.recovered, "claimed": self.claimed,
            "completed": self.completed, "skipped": self.skipped,
            "failed": self.failed, "lost_lease": self.lost_lease,
            "items_com_erro": self.items_com_erro[:20],
            "duration_s": self.duration_s, "stats": self.stats,
        }


class LaneWorker:
    """Consome uma lane até esvaziar (ou até `max_items`)."""

    def __init__(self, store: Any, lane: str, *, worker_id: str | None = None,
                 handler: Handler | None = None, lease_seconds: int = 300,
                 limit: int | None = None, max_items: int | None = None,
                 retry_in: int | None = None, recover_first: bool = True,
                 recover_limit: int = 200, heartbeat: bool = True) -> None:
        self.store = store
        self.lane = lane
        self.worker_id = worker_id or default_worker_id(lane)
        self.handler = handler or get_handler(lane)
        self.lease_seconds = int(lease_seconds)
        # Teto por lane (Sprint 2: audit 200, title_execution 10, ...). O teto é
        # lido da config no CLI; aqui o default é conservador.
        self.limit = P.lane_limit(lane) if limit is None else limit
        self.max_items = max_items
        self.retry_in = retry_in
        self.recover_first = recover_first
        self.recover_limit = recover_limit
        self.heartbeat_enabled = heartbeat
        self.queue = LaneQueue(store)

    # -- API ---------------------------------------------------------------

    def run(self) -> LaneRun:
        if self.handler is None:
            raise RuntimeError(
                f"lane '{self.lane}' sem handler registrado: nada a executar "
                f"(registre com register_handler antes de rodar). "
                f"Lanes com handler: {registered_lanes() or 'nenhuma'}")
        run = LaneRun(lane=self.lane, worker_id=self.worker_id)
        t0 = time.monotonic()
        if self.recover_first:
            run.recovered = len(self.queue.recover_expired(
                lane=self.lane, limit=self.recover_limit))
        while True:
            restante = None
            if self.max_items is not None:
                restante = self.max_items - run.claimed
                if restante <= 0:
                    break
            lote = self.limit if restante is None else min(self.limit, restante)
            itens = self.queue.claim(self.lane, self.worker_id, limit=lote,
                                     lease_seconds=self.lease_seconds)
            if not itens:
                break
            for item in itens:
                run.claimed += 1
                self._processar(item, run)
        run.duration_s = round(time.monotonic() - t0, 3)
        run.stats = self.queue.stats(lane=self.lane)
        return run

    def _processar(self, item: dict[str, Any], run: LaneRun) -> None:
        wid, v = item["work_item_id"], item["lease_version"]
        # Fencing ANTES de qualquer efeito: sem posse, o handler não roda.
        if not self.queue.mark_executing(wid, self.worker_id, v,
                                         lease_seconds=self.lease_seconds):
            run.lost_lease += 1
            run.items_com_erro.append(f"{wid}: posse perdida antes de executar")
            return
        hb = None
        if self.heartbeat_enabled:
            hb = _Heartbeat(str(self.store.path), wid, self.worker_id, v,
                            self.lease_seconds)
            hb.start()
        handler = self.handler
        if handler is None:                    # validado em run(); guarda aqui
            raise RuntimeError(f"lane '{self.lane}' sem handler registrado")
        try:
            resultado = handler(item)
            if hb is not None and hb.lost:
                # Trabalhou sem posse: NÃO conclui. O item é de outro worker
                # (ou será recuperado) — e nada foi registrado como sucesso.
                run.lost_lease += 1
                run.items_com_erro.append(f"{wid}: lease perdido durante o handler")
                return
            if isinstance(resultado, dict) and resultado.get("skip") is True:
                raise SkipItem(str(resultado.get("motivo") or "sem mudanca"))
            if self.queue.complete(wid, self.worker_id, v):
                run.completed += 1
            else:
                run.lost_lease += 1
                run.items_com_erro.append(f"{wid}: complete recusado (fencing)")
        except SkipItem as exc:
            if self.queue.complete(wid, self.worker_id, v):
                run.skipped += 1
            else:
                run.lost_lease += 1
            run.items_com_erro.append(f"{wid}: skip ({exc})")
        except Exception as exc:                                    # noqa: BLE001
            res = self.queue.fail(wid, self.worker_id, v, exc,
                                  retry_in=self.retry_in)
            if res.get("ok"):
                run.failed += 1
                run.items_com_erro.append(
                    f"{wid}: {res.get('error_class')} -> {res.get('status')} "
                    f"({type(exc).__name__}: {exc})"[:400])
            else:
                # Posse perdida: NADA foi gravado (o item é de outro worker).
                run.lost_lease += 1
                run.items_com_erro.append(f"{wid}: fail recusado (fencing)")
        finally:
            if hb is not None:
                hb.stop()


def run_lane(db_path: str, lane: str, *, worker_id: str | None = None,
             handler: Handler | None = None, lease_seconds: int = 300,
             limit: int | None = None, max_items: int | None = None,
             recover_limit: int = 200, heartbeat: bool = True) -> dict[str, Any]:
    """Conveniência para o CLI: abre um `Storage`, roda e devolve a telemetria."""
    from hermes_seo_agent.storage.db import Storage
    with Storage(db_path) as store:
        worker = LaneWorker(store, lane, worker_id=worker_id, handler=handler,
                            lease_seconds=lease_seconds, limit=limit,
                            max_items=max_items, recover_limit=recover_limit,
                            heartbeat=heartbeat)
        return worker.run().as_dict()
