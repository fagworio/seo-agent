"""GA4 A5 — medição integrada de intervenções (GSC + GA4, sem causalidade).

Ao marcar um item como concluído, o baseline salva GSC E GA4. Ao medir:

  * aquisição orgânica: impressões, cliques, CTR, posição (GSC);
  * engajamento: sessões orgânicas, engaged sessions, taxa (GA4);
  * verdict: improved | neutral | worsened | insufficient_data.

Nunca declara causalidade: compara antes/depois em períodos equivalentes e
expõe a qualidade da amostra (measurement_status e ausência de dados).
"""

from __future__ import annotations

from typing import Any

_ENGAGEMENT_METRICS = ("sessions", "engaged_sessions", "engagement_rate")


def engagement_deltas(before: dict[str, Any] | None,
                      after: dict[str, Any] | None) -> dict[str, Any]:
    """Deltas de engajamento GA4 entre duas janelas (float | None)."""
    deltas: dict[str, Any] = {}
    if not before or not after:
        deltas["verdict"] = "insufficient_data"
        deltas["data_quality"] = "missing_before_or_after"
        return deltas
    status = after.get("measurement_status")
    for key in _ENGAGEMENT_METRICS:
        b = before.get(key)
        a = after.get(key)
        if b is None or a is None:
            deltas[f"{key}_delta"] = None
            deltas[f"{key}_pct"] = None
            continue
        b, a = float(b), float(a)
        deltas[f"{key}_delta"] = round(a - b, 2)
        deltas[f"{key}_pct"] = round(((a - b) / b * 100), 1) if b else None
    if status != "available":
        deltas["data_quality"] = f"measurement_status={status}"
        deltas["verdict"] = "insufficient_data"
        return deltas
    deltas["data_quality"] = "available"
    deltas["verdict"] = engagement_verdict(deltas)
    return deltas


def engagement_verdict(d: dict[str, Any]) -> str:
    """Sessões subiram = improved; caíram = worsened; taxa sobe ajuda."""
    sessions = d.get("sessions_delta")
    rate = d.get("engagement_rate_delta")
    improved = False
    worsened = False
    if sessions is not None:
        improved |= sessions > 0
        worsened |= sessions < 0
    if rate is not None:
        improved |= rate > 0.0
        worsened |= rate < 0.0
    if improved and not worsened:
        return "improved"
    if worsened and not improved:
        return "worsened"
    if improved and worsened:
        return "mixed"
    return "neutral"


def combined_verdict(gsc: dict[str, Any], ga4: dict[str, Any]) -> str:
    """Verdict integrado: piora em qualquer dimensão domina; melhoras somam.

    Ordem de severidade: worsened > improved > mixed > neutral.
    """
    g = gsc.get("verdict", "neutral")
    e = ga4.get("verdict", "neutral")
    if "insufficient_data" in (g, e):
        return "insufficient_data"
    # piora em qualquer uma das duas dimensões é o sinal mais forte
    if g == "worsened" or e == "worsened":
        return "worsened"
    if g == "improved" or e == "improved":
        return "improved"
    if "mixed" in (g, e):
        return "mixed"
    return "neutral"


def baseline_gsc(before: dict[str, Any] | None) -> dict[str, Any] | None:
    """Slice GSC do baseline persistido (antes: dict plano; agora: {gsc, ga4})."""
    if not before:
        return None
    if isinstance(before.get("gsc"), dict):
        return before["gsc"]
    # compatibilidade: baseline legado sem aninhamento
    return before


def baseline_ga4(before: dict[str, Any] | None) -> dict[str, Any] | None:
    if not before or not isinstance(before.get("ga4"), dict):
        return None
    return before["ga4"]
