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
SKIP_ROLLOUT = "rollout_write_not_allowed"
SKIP_OVER_MAX_LEN = "title_over_max_length"

_REASON_TEXT: dict[str, str] = {
    SKIP_DECISION: "a decisao do motor nao eh review_title",
    SKIP_CONFIDENCE: "confianca baixa: vai para revisao humana (MANUAL_REVIEW)",
    SKIP_NO_CANDIDATE: "nenhum candidato valido no contrato",
    SKIP_NO_POST_ID: "contrato sem post_id: impossivel montar a acao",
    SKIP_STALE: "o titulo vivo mudou depois da decisao: acao descartada (STALE)",
    SKIP_NOOP: "o titulo proposto eh igual ao atual: nada a escrever",
    SKIP_ROLLOUT: ("o rollout do contrato nao permite escrita "
                   "(modo observe/approval): nenhuma acao eh criada"),
    SKIP_OVER_MAX_LEN: ("todos os candidatos passam do limite de tamanho: "
                        "recusado sem truncar (candidato validado nao se altera)"),
}


def _all_candidates(contract: dict[str, Any]) -> list[str]:
    """Todos os candidatos validos do contrato, na ordem de preferencia do motor.

    O motor ja validou cada um (semantica/estrutura). Por isso NUNCA se
    modifica um candidato aqui: se o primeiro estourar o limite de tamanho,
    tenta-se o proximo valido (P0.4) — truncar produziria um titulo que passou
    pela validacao sob outra forma.
    """
    out: list[str] = []
    for key in ("suggested_titles", "candidates"):
        for item in contract.get(key) or []:
            value = ""
            if isinstance(item, str):
                value = item.strip()
            elif isinstance(item, dict):
                if item.get("discarded"):
                    continue
                for field in ("title", "phrase", "text", "suggested_title"):
                    value = str(item.get(field) or "").strip()
                    if value:
                        break
            if value and value not in out:
                out.append(value)
    candidate = contract.get("candidate") or {}
    if isinstance(candidate, dict):
        for field in ("title", "suggested_title", "phrase", "text"):
            value = str(candidate.get(field) or "").strip()
            if value and value not in out:
                out.append(value)
                break
    proposed = str(contract.get("proposed_title") or "").strip()
    if proposed and proposed not in out:
        out.append(proposed)
    return out


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

    # P0.1 (Sprint 1.1) — o ROLLOUT manda. `observe` e `approval` NAO escrevem:
    # sem `writes_allowed` nenhuma acao eh criada, por mais alta que seja a
    # confianca. Antes esta checagem nao existia e o modo `approval` escrevia
    # automaticamente — o scheduler passava write=True nele e nada aqui barrava.
    rollout = contract.get("rollout") or {}
    if not rollout.get("writes_allowed"):
        return {"ok": False, "skip": SKIP_ROLLOUT,
                "detail": _REASON_TEXT[SKIP_ROLLOUT],
                "rollout_mode": rollout.get("mode")}

    confidence = str(contract.get("confidence") or "low").strip().lower()
    if confidence not in AUTO_CONFIDENCES:
        return {"ok": False, "skip": SKIP_CONFIDENCE,
                "detail": _REASON_TEXT[SKIP_CONFIDENCE], "confidence": confidence}

    # P0.4 (Sprint 1.1) — candidato acima do limite eh RECUSADO, nunca truncado:
    # truncar publicaria um texto que nunca passou pela validacao do motor.
    # Tenta-se o proximo candidato valido.
    candidates = _all_candidates(contract)
    if not candidates:
        return {"ok": False, "skip": SKIP_NO_CANDIDATE,
                "detail": _REASON_TEXT[SKIP_NO_CANDIDATE]}
    title = next((c for c in candidates if len(c) <= max_len), "")
    if not title:
        return {"ok": False, "skip": SKIP_OVER_MAX_LEN,
                "detail": _REASON_TEXT[SKIP_OVER_MAX_LEN],
                "refused_titles": [c[:80] for c in candidates[:5]]}

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
            # P0.2 (Sprint 1.1) — precondicao atomica: o Executor rele o post
            # IMEDIATAMENTE antes do update e aborta se o valor atual divergir do
            # `before` desta decisao (editor humano, outro agente). A garantia
            # fica no executor (perto da escrita), valendo para QUALQUER usuario
            # dele — nao so o title-engine.
            "precondition": ({"meta": {"rank_math_title": before}} if before else {}),
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
