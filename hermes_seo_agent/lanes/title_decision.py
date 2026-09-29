"""Sprint 2, item 7A — a decisao de titulo PERSISTIDA.

Ultimo lugar onde analise SEO acontece:

    audit / GSC / GA4
            |
      title_decision   <- analisa UMA vez, decide, PERSISTE
            |
      title_decision (tabela)
            |
      enqueue title_execution (payload completo)

`title_execution` (7B) le' o payload daqui e NUNCA reanalisa: sem GSC, sem GA4,
sem motor de titulo. Se o `before` mudou, o resultado e' STALE — nao "vou analisar
de novo e tentar outro titulo".

Identidade da acao
------------------
`action_fingerprint` e' calculado a partir da ACAO DECIDIDA, nao da URL:

    post_id + campo alterado + before + after + ACTION_VERSION

Consequencias que os testes fixam:

- mesma URL com outro titulo  => OUTRA acao (outro fingerprint, outro item);
- mesma decisao repetida      => MESMO fingerprint => enqueue idempotente.

`decision_id` e' derivado do fingerprint, entao a decisao e' uma linha SO' por
decisao (nao por execucao) — e' o que permite reconciliar sem duplicar.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from dataclasses import field as _dc_field
from typing import Any

__all__ = [
    "ACTION_VERSION",
    "DECISION_VERSION",
    "DEFAULT_FIELD",
    "MAX_TITLE_LEN",
    "MIN_CONFIDENCE",
    "NotExecutable",
    "TitleDecision",
    "make_decision",
    "production_ready",
    "persist_decision",
    "execution_item",
    "enqueue_execution",
    "reconcile_pending_enqueue",
    "title_action_fingerprint",
    "decision_id_for",
    "stats",
]

# Versao da SEMANTICA da acao (entra no fingerprint). Bump obrigatorio se o
# significado de "trocar o titulo" mudar: decisoes antigas continuam legiveis.
ACTION_VERSION = 1

# Versao da SEMANTICA da decisao (como interpretar evidence/rollout). Existe desde
# ja' para que uma mudanca futura no algoritmo nao torne decisao antiga ilegivel.
DECISION_VERSION = 1

DEFAULT_FIELD = "rank_math_title"
MAX_TITLE_LEN = 60

# Abaixo disso a decisao e' registrada mas NAO entra na execucao automatica (gate 6).
MIN_CONFIDENCE = 0.35

# Motivos de nao-executabilidade (rastreaveis, nunca genericos).
NOT_EXEC_LOW_CONFIDENCE = "low_confidence"
NOT_EXEC_REVIEW = "requires_review"
NOT_EXEC_ROLLOUT = "rollout_blocks_write"
NOT_EXEC_EMPTY_AFTER = "after_vazio"
NOT_EXEC_SAME_AS_BEFORE = "after_igual_ao_before"
NOT_EXEC_TOO_LONG = "after_acima_do_limite"
NOT_EXEC_NO_POST_ID = "sem_post_id"


class NotExecutable(Exception):
    """A decisao existe e e' valida, mas nao pode gerar execucao automatica."""


@dataclass
class TitleDecision:
    """A decisao completa. Tudo o que a execucao precisa esta aqui."""

    url: str
    post_id: int | None
    before: str
    after: str
    field: str = DEFAULT_FIELD
    action_fingerprint: str = ""
    decision_version: int = DECISION_VERSION
    evidence: dict[str, Any] = _dc_field(default_factory=dict)
    rollout: dict[str, Any] = _dc_field(default_factory=dict)
    confidence: float | None = None
    requires_review: bool = False
    decided_at: str = ""

    @property
    def decision_id(self) -> str:
        return decision_id_for(self.action_fingerprint)

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id, "url": self.url,
            "post_id": self.post_id, "before": self.before, "after": self.after,
            "field": self.field, "action_fingerprint": self.action_fingerprint,
            "decision_version": self.decision_version, "evidence": self.evidence,
            "rollout": self.rollout, "confidence": self.confidence,
            "requires_review": self.requires_review, "decided_at": self.decided_at,
        }


def title_action_fingerprint(*, post_id: int | None, before: str, after: str,
                             field: str = DEFAULT_FIELD,
                             action_version: int = ACTION_VERSION) -> str:
    """Identidade da ACAO decidida (nao da URL).

    `post_id + field + before + after + versao da acao`. A URL fica de fora de
    proposito: ela nao muda a acao. Ja' os titulos mudam — trocar o `after` e'
    outra acao e precisa gerar outro item.
    """
    parts = [str(post_id if post_id is not None else ""), str(field),
             (before or "").strip(), (after or "").strip(), str(action_version)]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:32]


def decision_id_for(action_fingerprint: str) -> str:
    """`decision_id` deterministico: mesma acao => mesma decisao."""
    return f"td:{action_fingerprint}"


def _now() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def make_decision(*, url: str, post_id: int | None, before: str, after: str,
                  evidence: dict[str, Any] | None = None,
                  rollout: dict[str, Any] | None = None,
                  confidence: float | None = None,
                  requires_review: bool = False,
                  field: str = DEFAULT_FIELD,
                  decision_version: int = DECISION_VERSION,
                  decided_at: str | None = None) -> TitleDecision:
    """Monta a decisao (sem persistir). O `before` e' gravado COMO OBSERVADO.

    Sem normalizacao de espaco/caixa aqui: o `before` e' a precondicao conferida
    contra o WordPress na execucao (gate 4). Normalizar faria a conferencia
    comparar um valor que nunca existiu no banco.
    """
    if not str(before or "").strip():
        raise ValueError("before vazio: a precondicao da execucao ficaria indefinida")
    if post_id is None:
        raise ValueError("post_id obrigatorio: sem ele nao ha alvo para escrever")
    fp = title_action_fingerprint(post_id=post_id, before=before, after=after,
                                  field=field)
    return TitleDecision(
        url=url, post_id=int(post_id), before=before, after=after, field=field,
        action_fingerprint=fp, decision_version=int(decision_version),
        evidence=dict(evidence or {}), rollout=dict(rollout or {}),
        confidence=confidence, requires_review=bool(requires_review),
        decided_at=decided_at or _now())


def production_ready(d: TitleDecision | dict[str, Any]) -> tuple[bool, str | None]:
    """Gates 5/6/7 decidem se a decisao pode virar execucao automatica.

    Devolve `(True, None)` ou `(False, motivo)`. O motivo NUNCA e' generico: e' o
    que permite auditar por que uma decisao ficou so' registrada.

    - gate 5: `after` precisa existir, diferir do `before` e caber no limite;
    - gate 6: baixa confianca e `requires_review` nao entram na execucao automatica;
    - gate 7: rollout sem permissao de escrita registra a decisao, mas nao executa.
    """
    if isinstance(d, TitleDecision):
        after, before, conf = d.after, d.before, d.confidence
        review, rollout, post_id = d.requires_review, d.rollout, d.post_id
    else:
        after, before, conf = d.get("after"), d.get("before"), d.get("confidence")
        review, rollout, post_id = (bool(d.get("requires_review")),
                                    d.get("rollout") or {}, d.get("post_id"))

    if not str(after or "").strip():
        return False, NOT_EXEC_EMPTY_AFTER
    if str(after).strip() == str(before or "").strip():
        return False, NOT_EXEC_SAME_AS_BEFORE
    if len(str(after).strip()) > MAX_TITLE_LEN:
        return False, NOT_EXEC_TOO_LONG
    if post_id is None:
        return False, NOT_EXEC_NO_POST_ID
    if review:
        return False, NOT_EXEC_REVIEW
    if conf is not None and float(conf) < MIN_CONFIDENCE:
        return False, NOT_EXEC_LOW_CONFIDENCE
    if not _rollout_allows_write(rollout):
        return False, NOT_EXEC_ROLLOUT
    return True, None


def _rollout_allows_write(rollout: dict[str, Any] | None) -> bool:
    """Rollout autoriza escrita? Ausencia de rollout = NAO autoriza.

    Default negado de proposito: rollout e' permissao explicita. "Nao configurado"
    nao pode significar "pode escrever no WordPress".
    """
    if not rollout:
        return False
    for chave in ("write_allowed", "allows_write", "write_enabled"):
        if chave in rollout:
            return bool(rollout.get(chave))
    fase = str(rollout.get("stage") or rollout.get("phase") or "").lower()
    if fase:
        return fase in ("auto", "write", "full")
    return False


def persist_decision(store: Any, d: TitleDecision) -> dict[str, Any]:
    """Persiste a decisao (idempotente). NAO cria item de fila.

    Persistir primeiro e enfileirar depois e' deliberado: se o processo morrer no
    meio, a decisao JA' esta' gravada e a reconciliacao (gate 8) cria o item que
    falta. A ordem inversa perderia a decisao.
    """
    ok, motivo = production_ready(d)
    res = store.record_title_decision(
        decision_id=d.decision_id, url=d.url, post_id=d.post_id, field=d.field,
        before=d.before, after=d.after, action_fingerprint=d.action_fingerprint,
        decision_version=d.decision_version, evidence=d.evidence,
        rollout=d.rollout, confidence=d.confidence,
        requires_review=d.requires_review,
        not_executable_reason=(None if ok else motivo),
        status="decided", decided_at=d.decided_at)
    return {"decision_id": d.decision_id, "acao": res["acao"],
            "executavel": ok, "motivo": motivo,
            "ja_existia": res["existing"] is not None}


def execution_item(d: TitleDecision | dict[str, Any]) -> dict[str, Any]:
    """GATE 3 — o item de `title_execution`: completo, sem dependencia externa.

    Este payload e' montado do que JA' esta' persistido. A execucao nao precisa de
    GSC, GA4 ou motor de titulo: se algum desses for consultado durante a escrita,
    o desenho esta' errado.
    """
    if isinstance(d, TitleDecision):
        d = d.as_dict()
    return {
        "decision_id": d["decision_id"],
        "url": d["url"],
        "post_id": d["post_id"],
        "field": d.get("field") or DEFAULT_FIELD,
        "before": d["before"],
        "after": d["after"],
        "action_fingerprint": d["action_fingerprint"],
        "decision_version": d.get("decision_version", DECISION_VERSION),
        "decided_at": d.get("decided_at", ""),
        "evidence": d.get("evidence") or {},
        "rollout": d.get("rollout") or {},
        "confidence": d.get("confidence"),
    }


def enqueue_execution(store: Any, d: TitleDecision | dict[str, Any], *,
                      priority: int = 100) -> dict[str, Any]:
    """Cria o item de `title_execution` — SO' se os gates permitirem.

    Idempotente pelo `work_item_id` (= `decision_id`): enfileirar 2x e' no-op.
    A decisao e' marcada com `enqueued_at`, que e' o que fecha o buraco do gate 8.
    """
    from hermes_seo_agent.lanes.queue import LaneQueue

    dd = d.as_dict() if isinstance(d, TitleDecision) else dict(d)
    if isinstance(d, TitleDecision):
        ok, motivo = production_ready(d)
    else:
        ok, motivo = production_ready(dd)
    if not ok:
        # decisao registrada, execucao NAO criada (gates 5/6/7)
        return {"enfileirado": False, "motivo": motivo,
                "decision_id": dd["decision_id"]}

    payload = execution_item(dd)
    q = LaneQueue(store)
    criado = q.enqueue("title_execution", dd["decision_id"], url=dd["url"],
                       payload=payload, priority=priority)
    store.mark_title_decision_enqueued(dd["decision_id"],
                                       status="enqueued")
    return {"enfileirado": bool(criado), "motivo": None,
            "decision_id": dd["decision_id"],
            "ja_existia": not criado}


def reconcile_pending_enqueue(store: Any, *, limit: int = 50) -> dict[str, Any]:
    """GATE 8 — fecha o buraco entre "decisao persistida" e "execution criada".

    Crash depois do `persist_decision` e antes do `enqueue_execution` deixaria uma
    decisao salva e nenhum item para executa-la. Aqui as decisoes sem `enqueued_at`
    que passam nos gates ganham o item que faltou — sem duplicar, porque o
    `work_item_id` e' deterministico.

    Devolve o que foi reconciliado e o que continua barrado (com o motivo).
    """
    pendentes = store.title_decisions_pending_enqueue(limit=limit)
    criados: list[str] = []
    barrados: list[dict[str, Any]] = []
    for dd in pendentes:
        ok, motivo = production_ready(dd)
        if not ok:
            store.record_title_decision(
                decision_id=dd["decision_id"], url=dd["url"],
                post_id=dd.get("post_id"), field=dd.get("field") or DEFAULT_FIELD,
                before=dd["before"], after=dd["after"],
                action_fingerprint=dd["action_fingerprint"],
                decision_version=dd.get("decision_version", DECISION_VERSION),
                evidence=dd.get("evidence") or {}, rollout=dd.get("rollout") or {},
                confidence=dd.get("confidence"),
                requires_review=bool(dd.get("requires_review")),
                not_executable_reason=motivo, status="decided",
                decided_at=dd.get("decided_at"))
            barrados.append({"decision_id": dd["decision_id"], "motivo": motivo})
            continue
        res = enqueue_execution(store, dd)
        if res["enfileirado"] or res.get("ja_existia"):
            criados.append(dd["decision_id"])
    return {"pendentes": len(pendentes), "reconciliados": len(criados),
            "criados": criados, "barrados": barrados}


def stats(store: Any) -> dict[str, Any]:
    """Observabilidade do 7A: status + quantas decisoes estao sem execucao."""
    return store.title_decision_stats()
