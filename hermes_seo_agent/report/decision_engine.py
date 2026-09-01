"""M6 — Opportunity Decision Engine.

Decide a melhor ação editorial para uma intenção com ÁRVORE DETERMINÍSTICA:

  Demanda suficiente?  não → sinal fraco / monitorar
  Relevante aos clusters?  não → descartar
  Conteúdo compatível?
    ├─ não → new_content / supporting_post
    └─ sim
        ├─ atende → monitorar / interlink
        ├─ cobertura insuficiente → expand_existing / refresh
        └─ várias URLs competindo → cannibalization_review

Dois scores SEPARADOS:
  * CandidateScore = demanda × topical_fit × rankability × tendência × confiança
    (vale a pena estudar a intenção?)
  * ActionScore    = impacto × confiança × facilidade
    (vale a pena EXECUTAR a ação?)

Tipos padronizados: title_meta, refresh, expand_existing, new_content,
supporting_post, hub_page, internal_link, cannibalization_review,
engagement_opportunity, lost_ranking.
"""

from __future__ import annotations

from typing import Any

OPPORTUNITY_TYPES = (
    "title_meta", "refresh", "expand_existing", "new_content",
    "supporting_post", "hub_page", "internal_link", "cannibalization_review",
    "engagement_opportunity", "lost_ranking",
)

# decisões possíveis da árvore
DECISIONS = ("new_content", "supporting_post", "expand_existing", "refresh",
             "internal_link", "monitor", "cannibalization_review", "discard",
             "weak_signal")


def decide(intent: dict[str, Any]) -> dict[str, Any]:
    """Árvore de decisão M6 para uma intenção (dict com os sinais).

    Campos esperados (todos opcionais; ausência = não mensurável):
      demand_score (0..1), relevant (bool), corpus_covers (bool),
      coverage_sufficient (bool), competing_urls (int), is_question (bool),
      rankability_score (0..1), trend (str), confidence (0..1),
      demand_source (str), demand_evidence (dict)
    """
    demand = intent.get("demand_score")
    if demand is None or demand < 0.5:
        return _outcome("weak_signal", intent,
                        reason="demanda insuficiente ou não mensurável — monitorar")

    if not intent.get("relevant", False):
        return _outcome("discard", intent,
                        reason="intenção fora do território editorial (clusters)")

    if not intent.get("corpus_covers", False):
        decision = "new_content"
        if intent.get("is_question"):
            decision = "supporting_post"
        return _outcome(decision, intent,
                        reason="nenhum conteúdo compatível no corpus")

    # existe conteúdo compatível
    if intent.get("competing_urls", 0) >= 2:
        return _outcome("cannibalization_review", intent,
                        reason=f"{intent.get('competing_urls')} URLs competem pela intenção")

    if intent.get("coverage_sufficient", False):
        return _outcome("internal_link", intent,
                        reason="conteúdo atende à intenção — apenas interligar")

    if intent.get("stale", False):
        return _outcome("refresh", intent,
                        reason="conteúdo existe mas está desatualizado")

    return _outcome("expand_existing", intent,
                    reason="conteúdo existe mas cobertura é insuficiente")


def _outcome(decision: str, intent: dict[str, Any], *, reason: str) -> dict[str, Any]:
    return {
        "decision": decision,
        "opportunity_type": _type_for(decision),
        "reason": reason,
        "candidate_score": candidate_score(intent),
        "action_score": action_score(intent),
        "intent": intent,
    }


def _type_for(decision: str) -> str:
    mapping = {
        "new_content": "new_content",
        "supporting_post": "supporting_post",
        "expand_existing": "expand_existing",
        "refresh": "refresh",
        "internal_link": "internal_link",
        "cannibalization_review": "cannibalization_review",
        "monitor": "engagement_opportunity",
        "weak_signal": "engagement_opportunity",
        "discard": "new_content",  # descartado; tipo só p/ contexto
    }
    return mapping.get(decision, "new_content")


def candidate_score(intent: dict[str, Any]) -> dict[str, Any]:
    """CandidateScore = demanda × topical_fit × rankability × tendência × confiança."""
    demand = _v(intent.get("demand_score"), 0.5)
    topical = _v(intent.get("topical_fit"), 0.5)
    rankability = _v(intent.get("rankability_score"), 0.3)
    trend = _trend_factor(intent.get("trend"))
    confidence = _v(intent.get("confidence"), 0.3)
    score = round(demand * topical * rankability * trend * confidence, 3)
    return {
        "score": score,
        "factors": {
            "demanda": demand,
            "topical_fit": topical,
            "rankability": rankability,
            "tendencia": trend,
            "confianca": confidence,
        },
        "formula": "demanda × topical_fit × rankability × tendência × confiança",
    }


def action_score(intent: dict[str, Any]) -> dict[str, Any]:
    """ActionScore = impacto × confiança × facilidade (mesmo do checklist)."""
    from .scoring import score_factors
    impact = _v(intent.get("impact_clicks"), None)
    confidence = _v(intent.get("confidence"), 0.3)
    item = intent.get("opportunity_type", "new_content")
    factors = score_factors(item=item, gain_clicks=impact,
                            evidence_quality=confidence)
    return {
        "score": factors["score"],
        "factors": factors["score_breakdown"],
        "formula": "impacto × confiança × facilidade",
    }


def _v(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return min(max(float(value), 0.0), 1.0)
    except (TypeError, ValueError):
        return default


def _trend_factor(trend: str | None) -> float:
    if trend == "growing":
        return 1.0
    if trend == "declining":
        return 0.3
    return 0.7  # stable/unknown
