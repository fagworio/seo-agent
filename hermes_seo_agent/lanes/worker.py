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

import inspect
import os
import socket
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from hermes_seo_agent.lanes import policy as P
from hermes_seo_agent.lanes.queue import LaneQueue

__all__ = [
    "Handler", "HandlerContext", "SkipItem", "LaneRun", "LaneWorker", "HANDLERS",
    "register_handler", "get_handler", "registered_lanes", "default_worker_id",
    "run_lane",
]

Handler = Callable[..., Any]


@dataclass
class HandlerContext:
    """Contexto do item para o handler — inclusive o MESMO banco do claim.

    Sem isto, um handler que abre `load_config().sqlite_path` por conta própria
    pode agir num banco diferente do que o worker claimou/marcou: claim em A,
    efeito em B, `done` em A.
    """
    db_path: str
    lane: str
    worker_id: str
    work_item_id: str
    lease_version: int
    queue: LaneQueue


def _aceita_ctx(handler: Handler) -> bool:
    """O handler quer o `HandlerContext` como 2o argumento?

    Compatibilidade importa: handlers de 1 argumento seguem válidos; quem precisa
    do `db_path` do worker pede o contexto.
    """
    try:
        params = [p for p in inspect.signature(handler).parameters.values()
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD,
                                p.VAR_POSITIONAL)]
    except (TypeError, ValueError):
        return False
    return len(params) >= 2


def _transitorio(exc: BaseException) -> bool:
    """Só erro de SQLite que costuma passar sozinho merece retry.

    `database is locked`/`busy` é contenção; schema quebrado, banco corrompido,
    path inválido e erro de programação NÃO são transitórios e não podem ser
    engolidos (foi engolir exceção que manteve o P0 invisível por 9 dias).
    """
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    msg = str(exc).lower()
    return "locked" in msg or "busy" in msg


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
        self.first_timeout = max(5.0, self.interval * 2)
        self.lost = False
        self.first_ok: bool | None = None
        self.error: str | None = None
        self.renovacoes = 0
        # `ready` = primeira renovação CONFIRMADA (ou falha definitiva). É o que
        # `start()` espera antes de liberar o handler: sem isto, "renovação no
        # t=0" era intenção — a thread podia nem ter escalado.
        self.ready = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _falhar(self, motivo: str) -> None:
        self.lost = True
        self.error = self.error or motivo
        if self.first_ok is None:
            self.first_ok = False
        self.ready.set()

    def _loop(self) -> None:
        from hermes_seo_agent.storage.db import Storage
        try:
            store = Storage(self.db_path)
        except Exception as exc:                                    # noqa: BLE001
            # Path inválido/schema impossível: NÃO é transitório.
            self._falhar(f"abertura do banco: {type(exc).__name__}: {exc}")
            return
        try:
            q = LaneQueue(store)
            # Renova IMEDIATAMENTE, antes de rodar o handler. O lease concedido no
            # claim/mark_executing vale `lease_seconds` e a primeira renovação
            # agendada só viria em `lease/3`: sob carga (suite cheia), a thread
            # atrasou mais que isso, o lease venceu e o worker perdeu o item —
            # medido, não teórico. Renovar no t=0 dobra a margem.
            primeira = True
            while not self._stop.is_set():
                try:
                    ok = q.heartbeat(self.work_item_id, self.worker_id,
                                     self.lease_version,
                                     lease_seconds=self.lease_seconds)
                    if primeira:
                        self.first_ok = ok
                        primeira = False
                        self.ready.set()      # destrava o worker (ok ou não)
                    if not ok:
                        self._falhar("renovacao recusada (fencing/lease vencido)")
                        return
                    self.renovacoes += 1
                except Exception as exc:                            # noqa: BLE001
                    if _transitorio(exc):
                        # Contenção ("database is locked"/"busy"): vale nova
                        # tentativa. Espera aqui dentro para não virar busy loop.
                        if self._stop.wait(self.interval):
                            return
                        continue
                    # NÃO transitório (schema quebrado, path inválido, erro de
                    # programação, erro interno do LaneQueue): perde a posse e
                    # REGISTRA o motivo na telemetria, em vez de engolir.
                    self._falhar(f"{type(exc).__name__}: {exc}")
                    return
                if self._stop.wait(self.interval):
                    return
        finally:
            try:
                store.close()
            except Exception:                                      # noqa: BLE001
                pass

    def start(self) -> bool:
        """Sobe a thread e ESPERA a primeira renovação confirmada.

        Devolve `True` só se a posse foi renovada AGORA. Sem esta espera, o
        handler podia começar antes de a thread sequer escalar.
        """
        self._thread = threading.Thread(
            target=self._loop, name=f"hb-{self.work_item_id}", daemon=True)
        self._thread.start()
        if not self.ready.wait(timeout=self.first_timeout):
            self._falhar(
                f"timeout de {self.first_timeout:.0f}s na 1a renovacao")
        return self.first_ok is True

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
    heartbeat_error: str | None = None
    items_com_erro: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    stats: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "lane": self.lane, "worker_id": self.worker_id,
            "recovered": self.recovered, "claimed": self.claimed,
            "completed": self.completed, "skipped": self.skipped,
            "failed": self.failed, "lost_lease": self.lost_lease,
            "heartbeat_error": self.heartbeat_error,
            "items_com_erro": self.items_com_erro[:20],
            "duration_s": self.duration_s, "stats": self.stats,
        }


class LaneWorker:
    """Consome uma lane até esvaziar (ou até `max_items`)."""

    def __init__(self, store: Any, lane: str, *, worker_id: str | None = None,
                 handler: Handler | None = None, lease_seconds: int = 300,
                 limit: int | None = None, max_items: int | None = None,
                 retry_in: int | None = None, recover_first: bool = True,
                 recover_limit: int = 200, heartbeat: bool = True,
                 config: Any = None) -> None:
        self.store = store
        self.lane = lane
        self.worker_id = worker_id or default_worker_id(lane)
        self.handler = handler or get_handler(lane)
        self._handler_com_ctx = _aceita_ctx(self.handler) if self.handler else False
        self.lease_seconds = int(lease_seconds)
        # Teto por lane: `config.lane_limits[lane]` > `config.lane_limit_<lane>` >
        # default do mapa. O `config` é obrigatório para a config valer: chamar
        # `lane_limit(lane)` sem ele sempre caía no default do mapa e a promessa de
        # backpressure configurável não existia.
        self.limit = P.lane_limit(lane, config) if limit is None else limit
        self.max_items = max_items
        self.retry_in = retry_in
        self.recover_first = recover_first
        self.recover_limit = recover_limit
        self.heartbeat_enabled = heartbeat
        self.config = config
        self.queue = LaneQueue(store)

    # -- API ---------------------------------------------------------------

    def teto(self, claimed: int) -> int | None:
        """Quanto ainda cabe nesta RODADA, compondo `limit` com `max_items`.

        `limit` é o teto da RODADA (o "por ciclo" do backpressure: audit 200,
        title_execution 10, ...), não o tamanho de um lote. Se fosse por lote, um
        worker em loop até esvaziar levaria a lane inteira e o teto não faria
        backpressure — que é o motivo de ele existir.

        `limit=0` = ILIMITADO, então normalizar ANTES de compor: `min(0, 5) = 0`
        viraria "sem LIMIT". Devolve `None` para ilimitado e `0` para "acabou".
        """
        limites: list[int] = []
        base = P.normalize_limit(self.limit)
        if base is not None:
            limites.append(base)
        if self.max_items is not None:
            limites.append(max(0, int(self.max_items)))
        if not limites:
            return None
        return max(0, min(limites) - claimed)

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
            restante = self.teto(run.claimed)
            if restante is not None and restante <= 0:
                break              # teto da rodada atingido: backpressure real
            # `0` no claim significa ILIMITADO — o teto da rodada é quem manda.
            itens = self.queue.claim(self.lane, self.worker_id,
                                     limit=0 if restante is None else restante,
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
            if not hb.start():
                # A posse NÃO foi confirmada: o handler não roda nem escreve. O
                # item volta pela recuperação bounded quando o lease vencer.
                run.lost_lease += 1
                run.heartbeat_error = (hb.error
                                       or "primeira renovacao nao confirmada")
                run.items_com_erro.append(
                    f"{wid}: handler NAO executado ({run.heartbeat_error})")
                hb.stop()
                return
        handler = self.handler
        if handler is None:                    # validado em run(); guarda aqui
            if hb is not None:
                hb.stop()
            raise RuntimeError(f"lane '{self.lane}' sem handler registrado")
        # O handler recebe o MESMO db_path que o worker claimou (nunca outro).
        ctx = HandlerContext(db_path=str(self.store.path), lane=self.lane,
                             worker_id=self.worker_id, work_item_id=wid,
                             lease_version=v, queue=self.queue)
        try:
            resultado = (handler(item, ctx) if self._handler_com_ctx
                         else handler(item))
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
                if hb.error:
                    # Erro de heartbeat sempre visível na telemetria da rodada.
                    run.heartbeat_error = hb.error


def run_lane(db_path: str, lane: str, *, worker_id: str | None = None,
             handler: Handler | None = None, lease_seconds: int = 300,
             limit: int | None = None, max_items: int | None = None,
             recover_limit: int = 200, heartbeat: bool = True,
             config: Any = None) -> dict[str, Any]:
    """Conveniência para o CLI: abre um `Storage`, roda e devolve a telemetria."""
    from hermes_seo_agent.storage.db import Storage
    with Storage(db_path) as store:
        worker = LaneWorker(store, lane, worker_id=worker_id, handler=handler,
                            lease_seconds=lease_seconds, limit=limit,
                            max_items=max_items, recover_limit=recover_limit,
                            heartbeat=heartbeat, config=config)
        return worker.run().as_dict()
