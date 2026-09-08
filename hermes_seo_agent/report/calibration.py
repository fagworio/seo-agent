"""M8-V2 — Calibração de pesos a partir de resultados medidos (R9).

Sem ML inicial: usa os outcomes históricos (before/after de posição/CTR e
verdict) para medir QUÃO PREDITIVO cada faixa de score foi, e derivar pesos
empiricamente. Determinístico. Guarda o relatório e os pesos ajustados.

Semântica: quanto mais alta a faixa de score e maior a taxa de melhoria
observada, mais o modelo "prediz" — recompensamos esse fator.
"""
from __future__ import annotations

from typing import Any

from .rankability_v2 import OPPORTUNITY_WEIGHTS  # base calibrável

# faixas de score (0..1) -> rótulo
BANDS = (
    (0.80, 1.01, "80-100"),
    (0.60, 0.80, "60-80"),
    (0.40, 0.60, "40-60"),
    (0.00, 0.40, "<40"),
)


def improved(outcome: dict[str, Any]) -> bool | None:
    """A melhoria observada é REAL? (verdict, ou delta de posição/CTR)."""
    verdict = outcome.get("verdict")
    if verdict == "improved":
        return True
    if verdict in ("worsened", "neutral"):
        return False
    # resultados aninhados por janela: usa a janela medida mais recente
    results = outcome.get("results") or {}
    gsc: dict[str, Any] = {}
    for window in ("90d", "56d", "28d", "7d"):
        r = results.get(window)
        if isinstance(r, dict):
            gsc = r.get("gsc_deltas") or {}
            if gsc:
                break
    pos = gsc.get("position")
    ctr = gsc.get("ctr")
    if pos is not None and pos < 0:
        return True
    if ctr is not None and ctr > 0:
        return True
    if pos is not None and pos > 0:
        return False
    if ctr is not None and ctr < 0:
        return False
    return None  # sem evidência de resultado


def _band(score: float | None) -> str | None:
    if score is None:
        return None
    for lo, hi, label in BANDS:
        if lo <= score < hi:
            return label
    return None


def score_of(outcome: dict[str, Any]) -> float | None:
    """Score usado para a calibração: candidate (V2/oportunidade) preferido."""
    cand = outcome.get("candidate_score")
    if cand is not None:
        return float(cand)
    action = outcome.get("action_score")
    if action is not None:
        return float(action)
    return None


def calibration_report(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    """Relatório de calibração: melhoria observada por faixa de score."""
    bands: dict[str, dict[str, Any]] = {
        label: {"n": 0, "improved": 0, "not_improved": 0, "no_evidence": 0}
        for _lo, _hi, label in BANDS
    }
    for o in outcomes:
        label = _band(score_of(o))
        if label is None:
            continue
        bands[label]["n"] += 1
        state = improved(o)
        if state is True:
            bands[label]["improved"] += 1
        elif state is False:
            bands[label]["not_improved"] += 1
        else:
            bands[label]["no_evidence"] += 1
    for label, b in bands.items():
        decided = b["improved"] + b["not_improved"]
        b["improved_rate"] = round(b["improved"] / decided, 3) if decided else None
        b["samples"] = decided
    ordered = [bands[label] for _lo, _hi, label in BANDS]
    # gradiente: taxa de melhoria sobe com o score?
    decided_rate = [b["improved_rate"] for b in ordered if b["improved_rate"] is not None]
    gradient = None
    if len(decided_rate) >= 2 and decided_rate[0] is not None and decided_rate[-1] is not None:
        gradient = round(decided_rate[0] - decided_rate[-1], 3) if ordered[0]["improved_rate"] \
            else None
    return {
        "bands": bands,
        "ordered": ordered,
        "gradient": gradient,  # >0 = faixa alta prevê mais melhoria (bom)
        "n_outcomes": len(outcomes),
    }


def calibrated_output_weights(calibration: dict[str, Any], base: dict[str, float] | None = None,
                              ) -> dict[str, float]:
    """Ajusta OPPORTUNITY_WEIGHTS conforme o gradiente de melhoria observado.

    Sem ML: escala proporcional ao quão preditivo foi o eixo rankability vs
    demanda/headroom. Mantém a soma 1.0.
    """
    base = base or dict(OPPORTUNITY_WEIGHTS)
    gradient = calibration.get("gradient")
    if gradient is None:
        return dict(base)  # sem evidência suficiente -> pesos default
    # recompensa rankability se faixas altas preveem melhoria; penaliza se nem isso
    delta = min(max(gradient, -0.4), 0.4) * 0.5
    weights = dict(base)
    weights["rankability"] = max(0.05, weights["rankability"] + delta)
    # renormaliza (sem arredondar por peso para a soma ficar exatamente 1.0)
    total = sum(weights.values())
    if total <= 0:
        return dict(base)
    return {k: v / total for k, v in weights.items()}
