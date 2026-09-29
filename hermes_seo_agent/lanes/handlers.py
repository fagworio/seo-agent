"""Sprint 2 (item 5) — handlers REAIS das lanes.

Um handler é o EFEITO de uma lane. O `LaneWorker` executa apenas o que estiver
registrado aqui: sem handler, ele recusa rodar (não improvisa) — foi assim que o
`ignore_pending_review=True` virou gambiarra no motor de títulos.

Registrados hoje
----------------
`technical` — reconciliação dos outcomes EXECUTED_UNMEASURED (Sprint 1.2):
    ações JÁ executadas no WordPress que ficaram sem medição porque o processo caiu
    entre a escrita confirmada e o outcome. Fecha o loop sem reescrever nada no
    WordPress, e é idempotente: após reconciliar, o item sai do conjunto derivado.

Ainda NÃO registrados (dependem dos itens 6/7): `dead_url`, `title_decision`,
`title_execution`, `measurement` por ação, `audit`. Um handler de lane só entra
quando o efeito dele for reversível/seguro o bastante para rodar sem humano.
"""
from __future__ import annotations

from typing import Any, Callable

from hermes_seo_agent.lanes import policy as P
from hermes_seo_agent.lanes.worker import register_handler

__all__ = ["handler_technical", "register_default_handlers", "HANDLERS_REGISTRADOS"]

# Nome lógico -> função, para o CLI poder listar/diagnosticar.
HANDLERS_REGISTRADOS: dict[str, str] = {}


def _db_path() -> str:
    """Caminho do banco REAL (mesmo que o CLI e o serve usam)."""
    from hermes_seo_agent.config import load_config
    return load_config().sqlite_path


def handler_technical(item: dict[str, Any]) -> dict[str, Any]:
    """Fecha o loop de ações executadas sem outcome (idempotente, sem WordPress).

    O item carrega o teto em `payload["limit"]` (default 50). O que importa não é
    o item isolado — é o tick: cada rodada recupera até `limit` ações executadas
    que ficaram sem medição e fecha a Caixa delas.
    """
    from hermes_seo_agent.storage.db import Storage

    payload = item.get("payload") or {}
    limite = int(payload.get("limit", 50)) if isinstance(payload, dict) else 50
    limite = P.normalize_limit(limite) or 50

    with Storage(_db_path()) as store:
        pendentes_antes = len(store.executed_without_outcome(limit=limite))
        if pendentes_antes == 0:
            # Nada a reconciliar: trabalho cumprido, sem efeito (vira `done`).
            return {"skip": True, "motivo": "nenhuma acao executada sem outcome"}
        resumo = store.reconcile_executed_outcomes(limit=limite,
                                                   close_checklist=True)
        pendentes_depois = len(store.executed_without_outcome(limit=limite))
    return {
        "reconciliados": resumo.get("reconciled", resumo),
        "pendentes_antes": pendentes_antes,
        "pendentes_depois": pendentes_depois,
        "item": item.get("work_item_id"),
    }


def register_default_handlers() -> dict[str, str]:
    """Registra os handlers seguros. Idempotente (chamar 2x não duplica efeito)."""
    register_handler(P.LANE_TECHNICAL, handler_technical)
    HANDLERS_REGISTRADOS[P.LANE_TECHNICAL] = "handler_technical"
    return dict(HANDLERS_REGISTRADOS)


def registrados() -> dict[str, str]:
    return dict(HANDLERS_REGISTRADOS)


_registrar: Callable[[], dict[str, str]] = register_default_handlers
