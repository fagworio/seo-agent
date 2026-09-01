"""Explainable editorial scoring: impacto × confiança × facilidade (point 4).

Pure deterministic scoring. Every recommendation carries the three factors and
how they were derived, so an editor can see WHY an item ranks where it does —
and rejections can feed back into confidence later.
"""

from __future__ import annotations

from typing import Any

# Effort by intervention type (3 = quickest, 1 = heaviest).
EFFORT: dict[str, int] = {
    "title_meta": 3, "intent": 3, "query_title_alignment": 3,
    "question_gap": 2, "query_content_coverage": 2, "content_depth": 2,
    "content_structure": 2, "internal_linking": 2, "thin_content": 2,
    "stale": 2, "lost_traffic": 2, "rank": 2, "expand_existing": 2,
    "supporting_post": 1, "hub_page": 1, "cannibalization_review": 2,
    "possible_cannibalization": 2, "title_opportunity": 3,
}
_DEFAULT_EFFORT = 2
_GAIN_CAP = 200.0  # cliques/mês que saturam o fator impacto


def effort(item: str) -> int:
    return EFFORT.get(item, _DEFAULT_EFFORT)


def score_factors(*, item: str, gain_clicks: float | None,
                  evidence_quality: float = 0.5, stable: bool | None = None) -> dict[str, Any]:
    """impacto × confiança × facilidade, com os fatores detalhados.

    - impacto: ganho projetado de cliques normalizado (cap 200/mês). Quando o
      ganho é DESCONHECIDO (None) — não inexistente — usa-se uma base
      conservadora (0.3) para que sugestões úteis sem projeção não fiquem com
      score 0. Ganho 0 conhecido continua sendo 0.
    - confianca: qualidade da evidência (0..1).
    - facilidade: 1/esforço normalizado (3 = mais fácil, 1 = mais pesado).
    """
    if gain_clicks is None:
        impacto = 0.3  # ganho desconhecido, mas potencialmente útil
    else:
        impacto = min(max(gain_clicks, 0.0) / _GAIN_CAP, 1.0)
    if stable is True:
        evidence_quality = min(evidence_quality + 0.15, 1.0)
    elif stable is False:
        evidence_quality = max(evidence_quality - 0.2, 0.0)

    eff = effort(item)
    facilidade = round(eff / 3.0, 3)  # 3 -> 1.0 (fácil), 1 -> 0.333 (pesado)

    total = round(impacto * evidence_quality * facilidade, 3)
    return {
        "score": total,
        "score_breakdown": {
            "impacto": round(impacto, 3),
            "confianca": round(evidence_quality, 3),
            "facilidade": facilidade,
            "effort": eff,
            "formula": "impacto × confiança × facilidade",
        },
    }


def confidence_for(*, has_queries: bool, impressions: float, word_count: int | None) -> float:
    """Deterministic evidence-quality estimate (0..1)."""
    conf = 0.3
    if has_queries:
        conf += 0.3
    if impressions >= 500:
        conf += 0.2
    elif impressions >= 100:
        conf += 0.1
    if word_count is not None and word_count > 0:
        conf += 0.1
    return min(conf, 1.0)
