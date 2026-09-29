"""TitleDecision -> SafeAction (roadmap Fase 2: decisao e execucao separadas).

O `title_engine` permanece PURO (entrada -> decisao): nada aqui faz chamada de
rede nem escreve em disco. Este modulo apenas converte o contrato de decisao em
uma `SafeAction` executavel pelo `Executor.apply_safe_actions()` — o MESMO
executor usado por `apply`/`set-title`. Nao existe segundo executor.

Regras do roadmap aplicadas aqui:

- Fase 9 (fechar o pipeline): soh `decision == "review_title"` com confianca
  medium/high e candidato valido vira acao; `low` retorna MANUAL_REVIEW.
- Fase 15 (idempotencia real): a fix carrega `before` + o novo valor; o
  fingerprint do Executor passa a distinguir propostas diferentes para a mesma
  URL (era o furo descrito no comentario de `_fingerprint`).
- Fase 16 (revalidar antes da escrita): se `live_title` (lido AO VIVO do
  WordPress) for diferente do `before` da decisao, a acao vira STALE e NAO
  sobrescreve — protege alteracao manual ou de outro agente.

Nenhuma excecao escapa: uma URL problematica devolve um motivo e o chamador
segue para a proxima (regra principal: nada para as outras URLs).
"""

from __future__ import annotations

from typing import Any

# Confiancas que autorizam escrita automatica (roadmap Fase 9).
AUTO_CONFIDENCES: tuple[str, ...] = ("high", "medium")

# Motivos de recusa. Sao dados de observabilidade, nunca erro fatal.
SKIP_DECISION = "decision_not_review_title"
SKIP_CONFIDENCE = "confidence_low_manual_review"
SKIP_NO_CANDIDATE = "sem_candidato_valido"
SKIP_NO_POST_ID = "post_id_ausente"
SKIP_STALE = "stale_titulo_mudou_apos_decisao"
SKIP_NOOP = "titulo_proposto_igual_ao_atual"

_REASON_TEXT: dict[str, str] = {
    SKIP_DECISION: "a decisao do motor nao eh review_title",
    SKIP_CONFIDENCE: "confianca baixa: vai para revisao humana (MANUAL_REVIEW)",
    SKIP_NO_CANDIDATE: "nenhum candidato valido no contrato",
    SKIP_NO_POST_ID: "contrato sem post_id: impossivel montar a acao",
    SKIP_STALE: "o titulo vivo mudou depois da decisao: acao descartada (STALE)",
    SKIP_NOOP: "o titulo proposto eh igual ao atual: nada a escrever",
}


def _candidate_title(contract: dict[str, Any]) -> str:
    """Melhor candidato valido do contrato, na ordem de preferencia do motor.

    Aceita as formas que o motor ja produz hoje (`suggested_titles` no caminho
    antigo, `candidates[]`/`candidate.title` no caminho novo) para nao acoplar
    este modulo ao formato interno do engine.
    """
    for key in ("suggested_titles", "candidates"):
        for item in contract.get(key) or []:
            if isinstance(item, str) and item.strip():
                return item.strip()
            if isinstance(item, dict):
                if item.get("discarded"):
                    continue
                for field in ("title", "phrase", "text", "suggested_title"):
                    value = str(item.get(field) or "").strip()
                    if value:
                        return value
    candidate = contract.get("candidate") or {}
    if isinstance(candidate, dict):
        for field in ("title", "suggested_title", "phrase", "text"):
            value = str(candidate.get(field) or "").strip()
            if value:
                return value
    return str(contract.get("proposed_title") or "").strip()


def _current_title(contract: dict[str, Any]) -> str:
    """Titulo atual registrado na decisao (o `before`)."""
    current = contract.get("current_title")
    if isinstance(current, dict):
        for field in ("title", "rank_math_title", "text"):
            value = str(current.get(field) or "").strip()
            if value:
                return value
        return ""
    return str(current or "").strip()


def decision_to_action(contract: dict[str, Any], *, live_title: str | None = None,
                       max_len: int = 65) -> dict[str, Any]:
    """Converte um contrato do motor em SafeAction (ou num motivo de recusa).

    Devolve sempre um dict:

        {"ok": True,  "action": {...SafeAction...}}
        {"ok": False, "skip": "<motivo>", "detail": "<texto>"}

    `live_title` (opcional) eh o `rank_math_title` lido AO VIVO do WordPress
    imediatamente antes da escrita. Quando informado, ativa a checagem de STALE
    da Fase 16. Quando ausente, a decisao usa o `before` do proprio contrato.
    """
    decision = str(contract.get("decision") or "").strip()
    if decision != "review_title":
        return {"ok": False, "skip": SKIP_DECISION,
                "detail": _REASON_TEXT[SKIP_DECISION], "decision": decision}

    confidence = str(contract.get("confidence") or "low").strip().lower()
    if confidence not in AUTO_CONFIDENCES:
        return {"ok": False, "skip": SKIP_CONFIDENCE,
                "detail": _REASON_TEXT[SKIP_CONFIDENCE], "confidence": confidence}

    title = _candidate_title(contract)
    if not title:
        return {"ok": False, "skip": SKIP_NO_CANDIDATE,
                "detail": _REASON_TEXT[SKIP_NO_CANDIDATE]}
    if len(title) > max_len:
        title = title[:max_len].rstrip()

    post_id = contract.get("post_id") or (contract.get("page") or {}).get("post_id")
    try:
        post_id = int(post_id) if post_id is not None else 0
    except (TypeError, ValueError):
        post_id = 0
    if post_id <= 0:
        return {"ok": False, "skip": SKIP_NO_POST_ID,
                "detail": _REASON_TEXT[SKIP_NO_POST_ID]}

    before = _current_title(contract)

    # Fase 16 — STALE: o site mudou entre a decisao e a escrita.
    if live_title is not None:
        live = str(live_title or "").strip()
        if before and live and live != before:
            return {"ok": False, "skip": SKIP_STALE,
                    "detail": _REASON_TEXT[SKIP_STALE],
                    "before": before, "live": live}

    # Nada a fazer quando a proposta repete o valor atual.
    if before and before.strip() == title:
        return {"ok": False, "skip": SKIP_NOOP,
                "detail": _REASON_TEXT[SKIP_NOOP]}

    url = str(contract.get("url") or "")
    action = {
        "rule_id": "title_engine",
        "url": url,
        "detail": f"title_engine: titulo reescrito ({len(title)} chars)",
        "before": {"rank_math_title": before},
        "fix": {
            "type": "wp_post_meta",
            "post_id": post_id,
            "meta": {"rank_math_title": title},
        },
        "confidence": confidence,
        "source": "title_engine",
    }
    return {"ok": True, "action": action}


def decisions_to_actions(contracts: list[dict[str, Any]], *,
                         live_titles: dict[str, str] | None = None,
                         max_len: int = 65) -> dict[str, Any]:
    """Converte varios contratos, isolando falhas (regra principal do roadmap).

    Uma URL que recusa nunca impede as outras: cada contrato vira acao ou um
    motivo de recusa no relatorio. `live_titles` mapeia url -> titulo vivo para
    a checagem de STALE.
    """
    live_titles = live_titles or {}
    actions: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for contract in contracts or []:
        # Regra principal do roadmap: um item estranho nunca derruba o lote.
        if not isinstance(contract, dict):
            skipped.append({"url": "", "skip": "contrato_invalido",
                            "detail": f"contrato nao-dict: {type(contract).__name__}"})
            continue
        url = str(contract.get("url") or "")
        try:
            outcome = decision_to_action(contract, live_title=live_titles.get(url),
                                         max_len=max_len)
        except Exception as exc:  # nunca derrubar o lote por um contrato estranho
            skipped.append({"url": url, "skip": "erro_inesperado",
                            "detail": f"{type(exc).__name__}: {exc}"})
            continue
        if outcome.get("ok"):
            actions.append(outcome["action"])
        else:
            skipped.append({"url": url, "skip": outcome.get("skip", ""),
                            "detail": outcome.get("detail", "")})
    return {"actions": actions, "skipped": skipped,
            "counts": {"built": len(actions), "skipped": len(skipped)}}
