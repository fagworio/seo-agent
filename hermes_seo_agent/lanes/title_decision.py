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
NOT_EXEC_MISSING_CONFIDENCE = "missing_confidence"
NOT_EXEC_REVIEW = "requires_review"
NOT_EXEC_ROLLOUT = "rollout_blocks_write"
NOT_EXEC_EMPTY_AFTER = "after_vazio"
NOT_EXEC_SAME_AS_BEFORE = "after_igual_ao_before"
NOT_EXEC_TOO_LONG = "after_acima_do_limite"
NOT_EXEC_NO_POST_ID = "sem_post_id"
NOT_EXEC_BEFORE_UNKNOWN = "before_desconhecido"


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
    # Distingue "observei o meta e ele estava VAZIO" (estado real, pode executar) de
    # "nao consegui ler o meta" (sem precondicao possivel => nunca executa).
    before_known: bool = True
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
            "requires_review": self.requires_review,
            "before_known": self.before_known, "decided_at": self.decided_at,
        }


def title_action_fingerprint(*, post_id: int | None, before: str, after: str,
                             field: str = DEFAULT_FIELD,
                             action_version: int = ACTION_VERSION) -> str:
    """Identidade da ACAO decidida (nao da URL).

    `post_id + field + before + after + versao da acao`. A URL fica de fora de
    proposito: ela nao muda a acao. Ja' os titulos mudam — trocar o `after` e'
    outra acao e precisa gerar outro item.

    SEM `strip()` nos titulos: o `before` e' a PRECONDITION conferida contra o
    WordPress (gate 4), entao `"Titulo"` e `" Titulo "` sao estados diferentes.
    Normalizar aqui faria duas decisoes distintas colidirem no mesmo `decision_id`,
    e o UPSERT sobrescreveria o `before` da tabela enquanto o item ja' enfileirado
    continuava com o payload antigo — fila e decisao divergindo em silencio.
    """
    parts = [str(post_id if post_id is not None else ""), str(field),
             before or "", after or "", str(action_version)]
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
                  before_known: bool = True,
                  field: str = DEFAULT_FIELD,
                  decision_version: int = DECISION_VERSION,
                  decided_at: str | None = None) -> TitleDecision:
    """Monta a decisao (sem persistir). O `before` e' gravado COMO OBSERVADO.

    Sem normalizacao de espaco/caixa aqui: o `before` e' a precondicao conferida
    contra o WordPress na execucao (gate 4). Normalizar faria a conferencia
    comparar um valor que nunca existiu no banco.
    """
    if not before_known and not str(before or "").strip():
        # Sem leitura confiavel do meta nao ha precondicao. A decisao ate' pode
        # existir (observabilidade), mas nunca executa: `production_ready` barra.
        raise ValueError(
            "before desconhecido: sem leitura confiavel do meta nao ha precondicao")
    if post_id is None:
        raise ValueError("post_id obrigatorio: sem ele nao ha alvo para escrever")
    fp = title_action_fingerprint(post_id=post_id, before=before, after=after,
                                  field=field)
    return TitleDecision(
        url=url, post_id=int(post_id), before=before, after=after, field=field,
        action_fingerprint=fp, decision_version=int(decision_version),
        evidence=dict(evidence or {}), rollout=dict(rollout or {}),
        confidence=confidence, requires_review=bool(requires_review),
        before_known=bool(before_known), decided_at=decided_at or _now())


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
        bknown = d.before_known
    else:
        after, before, conf = d.get("after"), d.get("before"), d.get("confidence")
        review, rollout, post_id = (bool(d.get("requires_review")),
                                    d.get("rollout") or {}, d.get("post_id"))
        bknown = bool(d.get("before_known", True))

    if not str(after or "").strip():
        return False, NOT_EXEC_EMPTY_AFTER
    if str(after).strip() == str(before or "").strip():
        return False, NOT_EXEC_SAME_AS_BEFORE
    if len(str(after).strip()) > MAX_TITLE_LEN:
        return False, NOT_EXEC_TOO_LONG
    if post_id is None:
        return False, NOT_EXEC_NO_POST_ID
    if not bknown:
        # FAIL-CLOSED: sem o valor bruto observado nao ha como conferir a
        # precondicao — executar seria escrever sobre um estado desconhecido.
        # `before=""` COM leitura confiavel passa: meta vazio e' estado real.
        return False, NOT_EXEC_BEFORE_UNKNOWN
    if review:
        return False, NOT_EXEC_REVIEW
    if conf is None:
        # FAIL-CLOSED: confianca ausente NAO libera escrita automatica. A integracao
        # com o motor ainda nao existe — exatamente onde um mapeamento faltando
        # produziria None e passaria batido para producao.
        return False, NOT_EXEC_MISSING_CONFIDENCE
    if float(conf) < MIN_CONFIDENCE:
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
    # `writes_allowed` PRIMEIRO: e' a chave que o contrato real do motor entrega
    # (`report/shadow_mode.py` -> {"mode": ..., "writes_allowed": ...}). Sem ela na
    # lista, TODA decisao vinda do motor cairia em `rollout_blocks_write` — o gate
    # funcionaria ao contrario do pretendido e nada executaria em silencio.
    for chave in ("writes_allowed", "write_allowed", "allows_write",
                  "write_enabled"):
        if chave in rollout:
            return bool(rollout.get(chave))
    # `mode`/`stage`/`phase` como fallback para rollout sem chave booleana.
    fase = str(rollout.get("mode") or rollout.get("stage")
               or rollout.get("phase") or "").lower()
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
        before_known=d.before_known,
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
    if criado:
        store.mark_title_decision_enqueued(dd["decision_id"], status="enqueued")
        return {"enfileirado": True, "motivo": None, "ja_existia": False,
                "decision_id": dd["decision_id"]}

    # O item JA' existia. `enqueue` e' no-op tambem para item finalizado, entao
    # marcar `enqueued` as cegas faria a decisao REGREDIR de `executed` para
    # `enqueued` — a maquina de estados passaria a mentir depois do 7B. So'
    # confirmamos enquanto o item ainda pode progredir.
    item = q.get_by_work_item("title_execution", dd["decision_id"])
    st = (item or {}).get("status")
    if st in LaneQueue.LIVE_STATUSES:
        store.mark_title_decision_enqueued(dd["decision_id"], status="enqueued")
        return {"enfileirado": False, "motivo": None, "ja_existia": True,
                "decision_id": dd["decision_id"], "item_status": st,
                "status_confirmado": True}
    return {"enfileirado": False, "motivo": None, "ja_existia": True,
            "decision_id": dd["decision_id"], "item_status": st,
            "status_confirmado": False, "nao_regrediu": True,
            "detalhe": f"item terminal ({st}): status da decisao preservado"}


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


def _numeric_confidence(action: dict[str, Any],
                        contract: dict[str, Any]) -> float | None:
    """Score NUMERICO da confianca. Rotulo textual nunca vira score.

    `decision_to_action` grava `confidence` como ROTULO ("high"/"medium") na acao,
    enquanto o numero real vive em `contract["confidence_detail"]["score"]`.
    Sem esta separacao, o primeiro `review_title` real estourava em
    `production_ready` -> `float("high")` -> ValueError. Rotulo desconhecido
    resolve para `None`, que o gate trata como `missing_confidence` (fail-closed).
    """
    for fonte in (contract.get("confidence_detail"),
                  action.get("confidence_detail")):
        if isinstance(fonte, dict) and fonte.get("score") is not None:
            try:
                return float(fonte["score"])
            except (TypeError, ValueError):
                pass
    for fonte in (contract.get("confidence"), action.get("confidence")):
        if isinstance(fonte, bool) or fonte is None:
            continue
        if isinstance(fonte, (int, float)):
            return float(fonte)
        if isinstance(fonte, str):
            try:
                return float(fonte)
            except ValueError:
                continue  # rotulo ("high"/"low") NAO e' score
    return None


def decision_from_action(action: dict[str, Any], *,
                         contract: dict[str, Any] | None = None,
                         live_title: str | None = None) -> TitleDecision:
    """Traduz a `SafeAction` do motor (e o contrato que a originou) em decisao.

    O `before` e' o titulo VIVO no WordPress quando ele foi lido; senao, o `before`
    da propria acao (que o motor tirou do `rank_math_title` observado). Nenhuma
    normalizacao aqui: e' esse valor que o gate 4 confere contra o banco.
    """
    contract = contract or {}
    fix = action.get("fix") or {}
    post_id = fix.get("post_id")
    if post_id is None:
        post_id = contract.get("post_id")
    # `live_title` e' o meta BRUTO lido do WP: `""` significa OBSERVADO VAZIO (estado
    # real, o post nao tem `rank_math_title` definido) e `None` significa que a
    # leitura NAO aconteceu. A distincao vira `before_known` e e' ela que decide se a
    # decisao pode executar — sem isso, um fallback silencioso para o `<title>`
    # renderizado passaria como se fosse o meta real.
    before_known = live_title is not None
    before = live_title
    if before is None:
        before = (action.get("before") or {}).get("rank_math_title")
    after = (fix.get("meta") or {}).get("rank_math_title") or ""
    # Score NUMERICO (de `confidence_detail`); o rotulo textual vai para evidence.
    conf = _numeric_confidence(action, contract)
    rotulo = None
    for fonte in (contract.get("confidence"), action.get("confidence")):
        if isinstance(fonte, str):
            rotulo = fonte
            break
    # `requires_review`: o motor e' quem sabe se a URL precisa de revisao humana.
    # Os contratos que chegam aqui ja' passaram pelo filtro `review_title`, entao o
    # default e' False (pode executar) e a barreira so' aparece se o contrato a
    # declarar — nunca por omissao, para nao bloquear tudo em silencio.
    review = bool(contract.get("requires_review")
                  or contract.get("approval_required"))
    return make_decision(
        url=str(action.get("url") or contract.get("url") or ""),
        post_id=(int(post_id) if post_id is not None else None),
        before=str(before or ""), after=str(after),
        confidence=conf, rollout=contract.get("rollout") or {},
        requires_review=review, before_known=before_known,
        evidence={"decision": contract.get("decision"),
                  "confidence_label": rotulo,
                  "page": contract.get("page"),
                  "baseline": contract.get("baseline"),
                  "signal_window": contract.get("signal_window"),
                  "source": "title_engine"})


def persist_actions(store: Any, actions: list[dict[str, Any]], *,
                    contracts_by_url: dict[str, dict[str, Any]] | None = None,
                    live_titles: dict[str, str] | None = None,
                    enqueue: bool = True) -> dict[str, Any]:
    """Persiste cada acao como decisao e enfileira o que for executavel.

    Ordem deliberada (gate 8): `persist_decision` ANTES de `enqueue_execution`. Se
    o processo morrer entre os dois, a decisao existe e `reconcile_pending_enqueue`
    fecha o buraco; a ordem inversa perderia a decisao.

    Uma URL que estoura nunca derruba o lote: vira linha em `erros`.
    """
    by_url = contracts_by_url or {}
    lives = live_titles or {}
    criadas: list[str] = []
    executaveis: list[str] = []
    sem_execucao: list[dict[str, Any]] = []
    erros: list[dict[str, Any]] = []
    for action in actions or []:
        # A leitura do `url` fica DENTRO da protecao: um item nao-dict nao pode
        # derrubar o lote (regra principal do roadmap). Com o `url` fora do try, um
        # unico item estranho estourava antes do `except` e levava o ciclo todo.
        url = (str(action.get("url") or "")
               if isinstance(action, dict) else "")
        try:
            d = decision_from_action(action, contract=by_url.get(url),
                                     live_title=lives.get(url))
            r = persist_decision(store, d)
            criadas.append(d.decision_id)
            if r.get("executavel"):
                if enqueue:
                    enqueue_execution(store, d)
                executaveis.append(d.decision_id)
            else:
                sem_execucao.append({"decision_id": d.decision_id,
                                     "motivo": r.get("motivo")})
        except Exception as exc:  # nunca derrubar o lote por uma URL estranha
            erros.append({"url": url,
                          "erro": f"{type(exc).__name__}: {exc}"})
    return {"criadas": criadas, "executaveis": executaveis,
            "sem_execucao": sem_execucao, "erros": erros,
            "counts": {"criadas": len(criadas), "executaveis": len(executaveis),
                       "sem_execucao": len(sem_execucao), "erros": len(erros)}}


def stats(store: Any) -> dict[str, Any]:
    """Observabilidade do 7A: status + quantas decisoes estao sem execucao."""
    return store.title_decision_stats()
