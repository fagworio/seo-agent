"""Veredito MULTIAXIAL de resultado (SEO-INC-012).

Motivação (diagnóstico de 19/09/2026): o veredito antigo tratava cliques/CTR
como decisão central. Em posições altas com CTR ~0 (resultados compostos: AI
Overviews/AI Mode citam a URL, vários links compartilham a posição e o usuário
não clica) isso produzia "worsened" por um clique a menos — e disparava
retriagem de título sem causa real.

Aqui os sinais são agrupados em eixos independentes:

  visibility  — impressões + posição (a página aparece mais/menos?)
  acquisition — cliques + CTR (o usuário clica mais/menos?)
  engagement  — sessões + taxa de engajamento (GA4: quem chegou fica?)

O CTR é UM SINAL do eixo de aquisição, nunca o veredito inteiro. O veredito
composto vira um rótulo explícito:

  regressed | visibility_up | traffic_up | engagement_up |
  no_change | mixed | insufficient_data
"""

from __future__ import annotations

from typing import Any

UP, DOWN, FLAT, UNKNOWN = "up", "down", "flat", "unknown"

# Movimento relativo mínimo para não tratar ruído como mudança.
TOL_REL = 0.05
# Pisos absolutos (evitam "melhorou" por 0,1 clique ou 0,1 p.p. de CTR).
TOL_CTR = 0.002      # 0,2 ponto percentual de CTR
TOL_ENG = 0.05       # 5 p.p. de taxa de engajamento


def axis_of(delta: Any, *, before: Any = None, invert: bool = False,
            tol_rel: float = TOL_REL, abs_tol: float = 0.0) -> str:
    """Classifica um delta em up/down/flat/unknown."""
    if delta is None:
        return UNKNOWN
    try:
        v = float(delta)
    except (TypeError, ValueError):
        return UNKNOWN
    if invert:  # posição menor = melhor
        v = -v
    try:
        ref = abs(float(before)) if before not in (None, "") else 0.0
    except (TypeError, ValueError):
        ref = 0.0
    limite = max(ref * tol_rel, abs_tol)
    if v > limite:
        return UP
    if v < -limite:
        return DOWN
    return FLAT


def _merge(*axes: str) -> str:
    """Combina sinais de um eixo: down domina > up > flat > unknown."""
    if DOWN in axes:
        return DOWN
    if UP in axes:
        return UP
    if FLAT in axes:
        return FLAT
    return UNKNOWN


def axis_verdicts(gsc: dict[str, Any] | None,
                  ga4: dict[str, Any] | None) -> dict[str, str]:
    """Eixos independentes de resultado."""
    g = gsc or {}
    e = ga4 or {}
    vis = _merge(
        axis_of(g.get("impressions_delta"), before=g.get("impressions_before")),
        axis_of(g.get("position_delta"), before=g.get("position_before"), invert=True),
    )
    acq = _merge(
        axis_of(g.get("clicks_delta"), before=g.get("clicks_before")),
        axis_of(g.get("ctr_delta"), before=g.get("ctr_before"), abs_tol=TOL_CTR),
    )
    eng = _merge(
        axis_of(e.get("sessions_delta"), before=e.get("sessions_before")),
        axis_of(e.get("engagement_rate_delta"), before=e.get("engagement_rate_before"),
                abs_tol=TOL_ENG),
    )
    return {"visibility": vis, "acquisition": acq, "engagement": eng}


def multiaxial_verdict(gsc: dict[str, Any] | None,
                       ga4: dict[str, Any] | None) -> tuple[str, dict[str, str]]:
    """Veredito composto + os eixos que o sustentam."""
    axes = axis_verdicts(gsc, ga4)
    vis, acq, eng = axes["visibility"], axes["acquisition"], axes["engagement"]

    if vis == UNKNOWN and acq == UNKNOWN and eng == UNKNOWN:
        return "insufficient_data", axes

    # Piora real (visibilidade ou aquisição) sem NENHUMA melhora -> regrediu.
    if (vis == DOWN or acq == DOWN) and UP not in (vis, acq, eng):
        return "regressed", axes
    if acq == UP:
        return "traffic_up", axes
    # Visibilidade melhora (ou está ótima) sem clique correspondente: NÃO é
    # falha do título — é o padrão de SERP composta. Não retriar.
    if vis == UP and acq != DOWN:
        return "visibility_up", axes
    if eng == UP and vis != DOWN and acq != DOWN:
        return "engagement_up", axes
    if vis == FLAT and acq == FLAT and eng in (FLAT, UNKNOWN):
        return "no_change", axes
    return "mixed", axes
