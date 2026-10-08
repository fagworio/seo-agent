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

`title_execution` — aplica uma decisão já persistida, com precondição, limite,
idempotência e releitura REST pós-write. Não reanalisa GSC/GA4 nem cria novo
título; apenas executa o payload fechado pela lane de decisão.

Ainda NÃO registrados: `title_decision`, `measurement` por ação, `audit`. Um
handler de lane só entra quando o efeito dele for reversível/seguro o bastante
para rodar sem humano.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Callable

from hermes_seo_agent.lanes import policy as P
from hermes_seo_agent.lanes.worker import SkipItem, register_handler

__all__ = ["handler_technical", "handler_dead_url", "handler_title_execution",
           "register_default_handlers",
           "HANDLERS_REGISTRADOS"]

# Nome lógico -> função, para o CLI poder listar/diagnosticar.
HANDLERS_REGISTRADOS: dict[str, str] = {}


def _db_path() -> str:
    """Caminho do banco REAL (mesmo que o CLI e o serve usam)."""
    from hermes_seo_agent.config import load_config
    return load_config().sqlite_path


def handler_technical(item: dict[str, Any], ctx: Any = None) -> dict[str, Any]:
    """Fecha o loop de ações executadas sem outcome (idempotente, sem WordPress).

    O item carrega o teto em `payload["limit"]` (default 50). O que importa não é
    o item isolado — é o tick: cada rodada recupera até `limit` ações executadas
    que ficaram sem medição e fecha a Caixa delas.

    Usa o `ctx.db_path` quando disponível: o efeito tem de cair no MESMO banco que
    o worker claimou. Só cai no `load_config()` para chamadas fora do worker.
    """
    from hermes_seo_agent.storage.db import Storage

    payload = item.get("payload") or {}
    limite = int(payload.get("limit", 50)) if isinstance(payload, dict) else 50
    limite = P.normalize_limit(limite) or 50
    db_path = getattr(ctx, "db_path", None) or _db_path()

    with Storage(db_path) as store:
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


def handler_dead_url(item: dict[str, Any], ctx: Any = None) -> dict[str, Any]:
    """Aplica a classificacao JA' DECIDIDA pelo produtor. Nunca reclassifica.

    A decisao viaja no payload junto com a evidencia, pelo mesmo motivo do item 7:
    reanalisar no momento da escrita e' o que produz resultado nao reproduzivel.
    Aqui o trabalho e' so' aplicar:

    1. registra a classificacao (persistente e idempotente por URL);
    2. aplica o efeito no `url_audit_state`.

    `transient` volta ao audit com backoff; as demais saem do ciclo.
    `redirect_candidate` NAO redireciona nada: registra o candidato e espera
    evidencia de que o destino e' o mesmo conteudo.
    """
    from hermes_seo_agent.lanes.dead_url import backoff_seconds
    from hermes_seo_agent.storage.db import Storage

    payload = item.get("payload") or {}
    url = str(payload.get("url") or item.get("url") or "")
    dec = payload.get("decision") or {}
    if not url or not dec.get("category"):
        raise SkipItem("dead_url sem url/decisao no payload")
    category = str(dec["category"])
    evid = dec.get("evidence") or {}
    failure_count = int(evid.get("failure_count") or 0)
    db_path = getattr(ctx, "db_path", None) or _db_path()

    nxt = None
    if category == "transient":
        import datetime as _dt
        nxt = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(
            seconds=backoff_seconds(failure_count))).isoformat()

    with Storage(db_path) as store:
        reg = store.record_dead_url(
            url=url, category=category, reason=str(dec.get("reason") or ""),
            evidence=evid, status_code=evid.get("status_code"),
            failure_count=failure_count, in_sitemap=bool(evid.get("in_sitemap")),
            redirect_target=dec.get("redirect_target"), next_check_at=nxt)
        estado = store.apply_dead_url_outcome(
            url=url, category=category, failure_count=failure_count)
    return {"url": url, "category": category, "registro": reg["acao"],
            "estado_audit": estado, "redirect_target": dec.get("redirect_target"),
            "reanalisou": False}


def handler_title_execution(item: dict[str, Any], ctx: Any = None) -> dict[str, Any]:
    """Executa uma decisão de título sem reabrir o motor de análise.

    A ação só é concluída quando o WordPress confirma o valor por uma segunda
    leitura REST. Divergência de precondição é ``stale`` (terminal e seguro);
    erro de transporte ou confirmação ausente permanece retryable no worker.
    """
    from hermes_seo_agent.config import load_config
    from hermes_seo_agent.connectors.wordpress import WordPressClient
    from hermes_seo_agent.executor.executor import Executor
    from hermes_seo_agent.storage.db import Storage

    payload = item.get("payload") or {}
    decision_id = str(payload.get("decision_id") or item.get("work_item_id") or "")
    url = str(payload.get("url") or item.get("url") or "")
    post_id = payload.get("post_id")
    field = str(payload.get("field") or "rank_math_title")
    before = str(payload.get("before") or "")
    after = str(payload.get("after") or "")
    if not decision_id or not url or post_id is None or not after:
        raise ValueError("title_execution sem payload completo")
    if field != "rank_math_title":
        raise ValueError(f"campo de título não suportado: {field}")

    config = load_config()
    if config.dry_run:
        raise RuntimeError("TITLE_ENGINE_MODE=auto incompatível com DRY_RUN")
    db_path = getattr(ctx, "db_path", None) or config.sqlite_path
    action = {
        "rule_id": "title_engine",
        "url": url,
        "detail": f"title_decision:{decision_id}",
        "work_item_id": decision_id,
        "fix": {
            "type": "wp_post_meta", "post_id": int(post_id),
            "meta": {field: after},
            "precondition": {"meta": {field: before}},
        },
    }

    with Storage(db_path) as store, WordPressClient(config) as wp:
        executor = Executor(config, wp, store)

        def verify(fix: dict[str, Any], _after: Any) -> bool:
            fresh = wp.get_post(int(fix["post_id"]))
            return ((fresh.get("meta") or {}).get(field) or "") == after

        outcome = executor.apply_safe_actions(
            [action], cycle_id=f"title-worker-{decision_id}",
            max_actions=1, verify=verify)
        executed_action = (outcome.get("executed") or [None])[0]
        if executed_action is None and outcome.get("skipped"):
            # O WordPress pode ter sido escrito antes de o worker perder o lease
            # ou a confirmação. Recupera o registro durável em vez de reescrever.
            executed_action = store.executed_action_for_work_item(decision_id)
        if executed_action is not None:
            action_fingerprint = str(executed_action.get("fingerprint") or "")
            implemented_at = str(
                executed_action.get("executed_at")
                or _dt.datetime.now(_dt.timezone.utc).isoformat()
            )
            evidence = payload.get("evidence") or {}
            page = evidence.get("page") or {}
            base = evidence.get("baseline") or {}
            signal_window = evidence.get("signal_window") or {}
            gsc = {k: page[k] for k in ("impressions", "clicks", "ctr", "position")
                   if page.get(k) is not None}
            gsc["_meta"] = {
                "window_start": base.get("window_start") or signal_window.get("window_start"),
                "window_end": base.get("window_end") or signal_window.get("window_end"),
                "source": "title_execution_decision",
            }
            before_value = (executed_action.get("before") or {}).get(field, before)
            after_value = (executed_action.get("after") or {}).get(field, after)
            # A escrita confirmada, seu outcome e o estado da decisão fecham em
            # uma única transação. Reprocessamentos só reutilizam o outcome.
            with store.transaction():
                if action_fingerprint and not store.outcome_for_action(action_fingerprint):
                    store.record_implemented_outcome(
                        url=url, action_type="title_engine",
                        implemented_action=after_value,
                        before={field: before_value}, after={field: after_value},
                        implemented_at=implemented_at,
                        work_item_id=decision_id,
                        gsc_baseline=gsc,
                        ga4_baseline=evidence.get("ga4"),
                        action_fingerprint=action_fingerprint,
                        commit=False,
                    )
                store.mark_title_decision_outcome(
                    decision_id, status="executed", commit=False)
                store.close_title_checklist(
                    [url], status="done",
                    when=implemented_at,
                    commit=False)
            return {"decision_id": decision_id, "status": "executed",
                    "url": url, "outcome": "reconciled"}
        if outcome.get("stale"):
            reason = str((outcome["stale"][0] or {}).get("reason") or "stale")
            store.mark_title_decision_outcome(
                decision_id, status="stale", reason=reason[:300])
            return {"motivo": reason, "status": "stale"}
        if outcome.get("unverified"):
            raise RuntimeError(str((outcome["unverified"][0] or {}).get(
                "reason") or "pós-write não confirmado"))
        skipped = outcome.get("skipped") or []
        if skipped:
            reason = str((skipped[0] or {}).get("reason") or "execução recusada")
            if "already executed" in reason:
                store.mark_title_decision_outcome(decision_id, status="executed")
                return {"skip": True, "motivo": reason, "status": "executed"}
            raise RuntimeError(reason)
    raise RuntimeError("title_execution terminou sem desfecho")


def register_default_handlers() -> dict[str, str]:
    """Registra os handlers seguros. Idempotente (chamar 2x não duplica efeito)."""
    register_handler(P.LANE_TECHNICAL, handler_technical)
    HANDLERS_REGISTRADOS[P.LANE_TECHNICAL] = "handler_technical"
    # item 6: efeito confinado ao `url_audit_state` — nao toca WordPress, entao e'
    # seguro sem humano. `redirect_candidate` fica SO' registrado (nao redireciona).
    register_handler("dead_url", handler_dead_url)
    HANDLERS_REGISTRADOS["dead_url"] = "handler_dead_url"
    register_handler(P.LANE_TITLE_EXECUTION, handler_title_execution)
    HANDLERS_REGISTRADOS[P.LANE_TITLE_EXECUTION] = "handler_title_execution"
    return dict(HANDLERS_REGISTRADOS)


def registrados() -> dict[str, str]:
    return dict(HANDLERS_REGISTRADOS)


_registrar: Callable[[], dict[str, str]] = register_default_handlers
