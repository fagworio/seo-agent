"""FASE 11–14 — Histórico de intervenções, tipos separados e calibração real.

Misturar as ``title_integrity_repair`` (títulos truncados restaurados) com as
``seo_title_optimization`` (título escolhido POR DEMANDA) contamina a
calibração: o ganho de uma restauração não diz nada sobre o peso do score. Aqui
cada intervenção declara o que é, e só o que foi escolhido por demanda entra na
calibração de pesos do motor de título.

A calibração é um ciclo FECHADO e versionado:

    outcomes -> calibration -> pesos persistidos -> novo ciclo -> outcomes

Nunca altera pesos com amostra insuficiente e nunca dá um salto grande de uma
vez (variação relativa máxima por ciclo). Determinístico: zero LLM.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from .calibration import improved  # mesma definição de "melhorou" já usada no M8
from .title_engine import MODEL_VERSION, TITLE_WEIGHTS

# ---------------------------------------------------------------------------
# FASE 12 — Tipos de intervenção (separação obrigatória)
# ---------------------------------------------------------------------------

INTERVENTION_TYPES: tuple[str, ...] = (
    "seo_title_optimization",
    "title_integrity_repair",
    "manual_editorial_change",
    "brand_cleanup",
    "technical_title_fix",
    "rollback",
)

# Só a otimização dirigida por demanda alimenta a calibração de título.
_OPTIMIZATION_DRIVEN = frozenset({"seo_title_optimization"})

# Origem -> tipo. Determinístico: a origem declarada decide, nunca a heurística
# do título resultante.
_SOURCE_TO_TYPE: dict[str, str] = {
    "title_engine": "seo_title_optimization",
    "title_opportunities": "seo_title_optimization",
    "title_shortener": "title_integrity_repair",
    "title_integrity": "title_integrity_repair",
    "restore_truncated": "title_integrity_repair",
    "truncated_restore": "title_integrity_repair",
    "brand_cleanup": "brand_cleanup",
    "technical_title_fix": "technical_title_fix",
    "set_title_cli": "manual_editorial_change",
    "manual": "manual_editorial_change",
    "editorial": "manual_editorial_change",
    "rollback": "rollback",
}


def classify_intervention(*, source: str = "", intervention_type: str = "",
                          optimization_driven: bool | None = None,
                          window: str = "") -> dict[str, Any]:
    """Classifica a intervenção — e diz se ela pode calibrar o motor de título.

    As restaurações dos títulos truncados NÃO foram escolhidas por demanda SEO:
    entram como ``title_integrity_repair`` e ficam FORA da calibração.
    """
    kind = (intervention_type or "").strip() or _SOURCE_TO_TYPE.get(
        (source or "").strip().lower(), "")
    if kind not in INTERVENTION_TYPES:
        kind = "manual_editorial_change"
    driven = kind in _OPTIMIZATION_DRIVEN if optimization_driven is None \
        else bool(optimization_driven)
    eligible = bool(driven and kind in _OPTIMIZATION_DRIVEN)
    if kind in _OPTIMIZATION_DRIVEN:
        reason = ("título escolhido por demanda observada (famílias + baseline + "
                  "evidência): elegível para calibrar o motor")
    elif kind == "title_integrity_repair":
        reason = ("integridade editorial (ex.: restauração de título truncado): "
                  "não foi escolha de demanda — fora da calibração de título")
    else:
        reason = f"{kind}: fora da calibração de título"
    return {
        "intervention_type": kind,
        "optimization_driven": driven,
        "eligible_for_title_calibration": eligible,
        "window": window,
        "reason": reason,
        "model_version": MODEL_VERSION,
    }


# ---------------------------------------------------------------------------
# FASE 11 — Registro de outcome (before / features / after 7-28-56-90d)
# ---------------------------------------------------------------------------

CANDIDATE_FEATURES: tuple[str, ...] = (
    "demand_coverage_before", "demand_coverage_after", "primary_intent",
    "secondary_intent", "query_rankability", "baseline_percentile",
    "position_before", "ctr_before", "family_share", "title_score", "confidence",
    # os SETE fatores que produziram o score (fonte da calibração) + confiança
    # numérica: sem eles a calibração não aprenderia os eixos que o score declara
    "score_factors", "confidence_score",
)

# Eixo do SCORE -> features que o representam no outcome registrado. O caminho
# canônico é `candidate_features["score_factors"]` (os SETE valores que
# produziram o score). Sem este mapa a calibração olharia nomes que não existem
# no case (e não ajustaria nada, silenciosamente).
# `historical_success` NÃO usa `title_score` como proxy: o score final depende
# dele (referência circular) — a calibração mediria a si mesma.
FACTOR_FEATURES: dict[str, tuple[str, ...]] = {
    "demand_coverage": ("demand_coverage", "demand_coverage_after"),
    "intent_fit": ("intent_fit",),
    "rankability": ("rankability", "query_rankability"),
    "headroom": ("headroom",),
    "historical_success": ("historical_success",),
    "trend": ("trend",),
    "confidence": ("confidence", "confidence_score"),
}

# Rótulos legados de confiança -> valor numérico (linhas antigas do store).
CONFIDENCE_LABEL_SCORES: dict[str, float] = {"high": 0.85, "medium": 0.6, "low": 0.35}


def score_factors_from_features(features: dict[str, Any] | None) -> dict[str, float]:
    """Os SETE fatores do score, como persistidos para a calibração."""
    source = features or {}
    out: dict[str, float] = {}
    for key in TITLE_WEIGHTS:
        value = source.get(key)
        if isinstance(value, bool) or value is None:
            continue
        try:
            out[key] = round(float(value), 4)
        except (TypeError, ValueError):
            continue
    return out


def outcome_record(*, url: str = "", intervention: dict[str, Any] | None = None,
                   before: dict[str, Any] | None = None,
                   candidate_features: dict[str, Any] | None = None,
                   factors: dict[str, Any] | None = None,
                   confidence_score: float | None = None,
                   after: dict[str, Any] | None = None,
                   extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Estrutura canônica de outcome de uma alteração de título.

    ``after``: {"7d": {...}, "28d": {...}, "56d": {...}, "90d": {...}} (parcial é
    normal — a medição chega em ondas). Janela ausente fica ``None``: nunca zero.

    ``factors``/``candidate_features["score_factors"]``: os SETE valores que
    produziram o score. É deles que a calibração aprende — sem eles, o eixo
    declarado no score não tem como ser validado empiricamente.
    """
    kind = intervention or classify_intervention(source="title_engine")
    after = after or {}
    given = dict(candidate_features or {})
    stored = {key: given.get(key) for key in CANDIDATE_FEATURES}
    score_factors = score_factors_from_features(
        factors or given.get("score_factors") or given)
    if score_factors:
        stored["score_factors"] = score_factors
    numeric_confidence = confidence_score
    if numeric_confidence is None:
        value = given.get("confidence_score")
        if value is not None and not isinstance(value, bool):
            try:
                numeric_confidence = float(value)
            except (TypeError, ValueError):
                numeric_confidence = None
    if numeric_confidence is not None:
        stored["confidence_score"] = round(float(numeric_confidence), 4)
    record: dict[str, Any] = {
        "url": url,
        "intervention_type": kind.get("intervention_type"),
        "optimization_driven": bool(kind.get("optimization_driven")),
        "eligible_for_title_calibration": bool(kind.get("eligible_for_title_calibration")),
        "before": dict(before or {}),
        "candidate_features": stored,
        "model_version": kind.get("model_version", MODEL_VERSION),
    }
    for window in ("7d", "28d", "56d", "90d"):
        record[f"after_{window}"] = after.get(window)
    record.update(extra or {})
    return record


def calibration_sample(outcomes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Só os outcomes ELEGÍVEIS (otimização por demanda) — FASE 12."""
    return [o for o in outcomes if o.get("eligible_for_title_calibration")]


def persist_case(storage: Any, case: dict[str, Any], *, keyword: str = "",
                 implemented_at: str = "") -> int:
    """Persiste o case no MESMO store de outcomes (opportunity_outcomes).

    O case inteiro vai em ``evidence``: assim a calibração do motor de título lê
    as features que ela mesma mediu, sem inventar schema paralelo.
    """
    candidate = case.get("candidate_features") or {}
    return storage.save_opportunity_outcome(
        keyword=(keyword or str(candidate.get("primary_intent") or "")
                 or case.get("url") or ""),
        opportunity_type=case.get("intervention_type") or "seo_title_optimization",
        decision=str(case.get("decision") or ""),
        evidence=case,
        candidate_score=(float(candidate["title_score"])
                         if isinstance(candidate.get("title_score"), (int, float))
                         else None),
        url=case.get("url", ""),
        implemented_at=implemented_at,
    )


def load_cases(storage: Any, *, limit: int = 2000) -> list[dict[str, Any]]:
    """Cases de intervenção já persistidos (formato do motor de título).

    Linhas do store que não são do motor (evidence sem o formato de outcome) são
    ignoradas — nunca contaminam a calibração.
    """
    out: list[dict[str, Any]] = []
    try:
        rows = storage.list_opportunity_outcomes(limit=limit)
    except Exception:  # noqa: BLE001 - ausência de store nunca quebra o ciclo
        return out
    for row in rows:
        evidence = row.get("evidence")
        if not isinstance(evidence, dict):
            continue
        if "eligible_for_title_calibration" not in evidence:
            continue
        case = dict(evidence)
        case.setdefault("url", row.get("url") or "")
        if row.get("verdict"):
            case["verdict"] = row["verdict"]
        results = row.get("results") or {}
        case["results"] = {w: r for w, r in results.items() if r}
        for window, result in (results or {}).items():
            if result and not case.get(f"after_{window}"):
                case[f"after_{window}"] = result
        out.append(case)
    return out


# ---------------------------------------------------------------------------
# FASE 13 — Calibração persistente e versionada
# ---------------------------------------------------------------------------

MIN_SAMPLE_DEFAULT = 30        # < 30 -> pesos padrão, sem ajuste
MIN_SAMPLE_PROGRESSIVE = 100   # 30..100 -> limitada; > 100 -> progressiva
LIMITED_RELATIVE_SHIFT = 0.05  # ±5% relativo por ciclo (calibração limitada)
MAX_RELATIVE_SHIFT = 0.10      # ±10% relativo por ciclo (teto absoluto)


def _feature_value(outcome: dict[str, Any], key: str) -> float | None:
    """Valor medido do eixo do score (aceita o nome do fator ou o da feature).

    Ordem: (1) ``candidate_features["score_factors"]`` — os sete valores EXATOS
    que produziram o score; (2) nomes legados; (3) rótulo de confiança antigo,
    convertido para número.
    """
    features = outcome.get("candidate_features") or {}
    factors = features.get("score_factors") if isinstance(features, dict) else None
    if isinstance(factors, dict):
        value = factors.get(key)
        if value is not None and not isinstance(value, bool):
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    for name in FACTOR_FEATURES.get(key, (key,)):
        value = features.get(name) if isinstance(features, dict) else None
        if value is None:
            value = outcome.get(name)
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str) and value.strip().lower() in CONFIDENCE_LABEL_SCORES:
            return CONFIDENCE_LABEL_SCORES[value.strip().lower()]
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def predictability(outcomes: Sequence[dict[str, Any]]) -> dict[str, float]:
    """O quanto cada eixo separa 'melhorou' de 'não melhorou' (determinístico).

    Média do fator nos casos com melhoria MENOS a média nos casos sem melhoria.
    Positivo = o eixo aponta para melhoria; ausência de um dos grupos = 0.
    """
    judged = [(o, improved(o)) for o in outcomes]
    judged = [(o, state) for o, state in judged if state is not None]
    yes = [o for o, state in judged if state]
    no = [o for o, state in judged if not state]
    out: dict[str, float] = {}
    for key in TITLE_WEIGHTS:
        a = [_feature_value(o, key) for o in yes]
        b = [_feature_value(o, key) for o in no]
        a = [v for v in a if v is not None]
        b = [v for v in b if v is not None]
        if not a or not b:
            out[key] = 0.0
            continue
        out[key] = round(sum(a) / len(a) - sum(b) / len(b), 4)
    return out


def title_calibration(outcomes: Sequence[dict[str, Any]], *,
                      base_weights: dict[str, float] | None = None,
                      previous: dict[str, Any] | None = None,
                      calibrated_at: str = "") -> dict[str, Any]:
    """Ciclo fechado: outcomes -> pesos -> persistência versionada.

    Regras de amostra (FASE 13):
      * < 30 outcomes  -> pesos PADRÃO (nenhum ajuste)
      * 30..100        -> calibração LIMITADA (máx ±5% relativo por ciclo)
      * > 100          -> ajuste progressivo (máx ±10% relativo por ciclo)
    """
    base = dict(base_weights or TITLE_WEIGHTS)
    sample = calibration_sample(outcomes)
    judged = [o for o in sample if improved(o) is not None]
    previous = previous or {}
    version = int(previous.get("weights_version") or 0)

    if len(judged) < MIN_SAMPLE_DEFAULT:
        return {
            "weights": base,
            "weights_version": version,          # NÃO versiona sem amostra
            "model_version": MODEL_VERSION,
            "sample_count": len(judged),
            "eligible_sample": len(sample),
            "stage": "insufficient_sample",
            "max_relative_shift": 0.0,
            "predictability": {},
            "calibrated_at": calibrated_at,
            "note": (f"{len(judged)} outcomes elegíveis < {MIN_SAMPLE_DEFAULT}: "
                     "pesos padrão mantidos (nunca calibrar com amostra insuficiente)"),
        }

    limited = len(judged) <= MIN_SAMPLE_PROGRESSIVE
    shift_cap = LIMITED_RELATIVE_SHIFT if limited else MAX_RELATIVE_SHIFT
    pred = predictability(judged)
    weights: dict[str, float] = {}
    for key, weight in base.items():
        delta = max(min(pred.get(key, 0.0), shift_cap), -shift_cap)
        weights[key] = max(weight * (1.0 + delta), 0.01)
    total = sum(weights.values()) or 1.0
    weights = {k: v / total for k, v in weights.items()}
    return {
        "weights": weights,
        "weights_version": version + 1,
        "model_version": MODEL_VERSION,
        "sample_count": len(judged),
        "eligible_sample": len(sample),
        "stage": "limited" if limited else "progressive",
        "max_relative_shift": shift_cap,
        "predictability": pred,
        "calibrated_at": calibrated_at,
        "note": (f"{len(judged)} outcomes elegíveis -> "
                 f"{'calibração limitada' if limited else 'ajuste progressivo'} "
                 f"(movimento relativo máx {shift_cap:.0%} por ciclo)"),
    }


# ---------------------------------------------------------------------------
# FASE 14 — Historical Success Factor
# ---------------------------------------------------------------------------

MIN_HISTORY_SAMPLE = 10
POSITION_BANDS: tuple[tuple[float, float, str], ...] = (
    (1, 5, "1-5"), (5, 10, "5-10"), (10, 20, "10-20"), (20, 1e9, "20+"),
)


def position_band(position: Any) -> str:
    try:
        value = float(position)
    except (TypeError, ValueError):
        return "unknown"
    for lo, hi, label in POSITION_BANDS:
        if lo <= value < hi:
            return label
    return POSITION_BANDS[-1][2]


def _rate(cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    states = [improved(c) for c in cases]
    decided = [s for s in states if s is not None]
    if not decided:
        return {"value": None, "sample": 0, "improved": 0, "sufficient": False}
    rate = sum(1 for s in decided if s) / len(decided)
    return {"value": round(rate, 3), "sample": len(decided),
            "improved": sum(1 for s in decided if s), "sufficient": len(decided) >= MIN_HISTORY_SAMPLE}


def case_segment(case: dict[str, Any]) -> dict[str, Any]:
    features = case.get("candidate_features") or {}
    before = case.get("before") or {}
    intents = [i for i in (features.get("primary_intent"), features.get("secondary_intent")) if i]
    return {
        "position_band": position_band(features.get("position_before", before.get("position"))),
        "intents_count": len(intents) or None,
        "primary_intent": features.get("primary_intent"),
        "coverage_before": features.get("demand_coverage_before"),
        "coverage_after": features.get("demand_coverage_after"),
    }


def historical_success_factor(cases: Sequence[dict[str, Any]], *,
                              position: Any = None, intents_count: int | None = None,
                              primary_intent: str | None = None) -> dict[str, Any]:
    """Fator EMPÍRICO para o score (FASE 14) — neutro sem amostra suficiente.

    Só usa outcomes elegíveis (otimização por demanda). Sem 10 casos medidos no
    segmento, devolve ``value=None`` e o score usa o neutro (0.5): ausência de
    evidência nunca vira confiança.
    """
    sample = [c for c in calibration_sample(cases) if improved(c) is not None]
    band = position_band(position) if position is not None else None
    matched = []
    for case in sample:
        seg = case_segment(case)
        if band and seg["position_band"] != band:
            continue
        if intents_count is not None and seg["intents_count"] != intents_count:
            continue
        if primary_intent and seg["primary_intent"] != primary_intent:
            continue
        matched.append(case)
    stats = _rate(matched)
    if not matched:
        stats = _rate(sample)
        scope = "global"
    else:
        scope = "segmento"
    if not stats["sufficient"]:
        return {"value": None, "sample": stats["sample"], "scope": scope,
                "sufficient": False,
                "note": (f"histórico insuficiente (n={stats['sample']} < "
                         f"{MIN_HISTORY_SAMPLE}): fator neutro"),
                "segment": {"position_band": band, "intents_count": intents_count,
                            "primary_intent": primary_intent}}
    return {"value": stats["value"], "sample": stats["sample"], "scope": scope,
            "sufficient": True,
            "note": (f"{stats['improved']}/{stats['sample']} alterações comparáveis "
                     f"melhoraram ({stats['value']:.0%})"),
            "segment": {"position_band": band, "intents_count": intents_count,
                        "primary_intent": primary_intent}}


def historical_questions(cases: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Respostas EMPÍRICAS às perguntas da FASE 14 (ou 'amostra insuficiente')."""
    sample = [c for c in calibration_sample(cases) if improved(c) is not None]
    out: list[dict[str, Any]] = []
    for lo, hi, label in POSITION_BANDS[:-1]:
        subset = [c for c in sample if case_segment(c)["position_band"] == label]
        second_intent = [c for c in subset if (case_segment(c)["intents_count"] or 0) >= 2]
        out.append({
            "question": f"páginas na posição {label}: adicionar segunda intenção melhora?",
            "answer": _rate(second_intent),
        })
    trios = [c for c in sample if (case_segment(c)["intents_count"] or 0) >= 3]
    pairs = [c for c in sample if (case_segment(c)["intents_count"] or 0) == 2]
    out.append({"question": "duas intenções performam melhor que três?",
                "answer": {"two_intents": _rate(pairs), "three_intents": _rate(trios)}})
    for intent in ("onde_assistir", "idade", "poderes"):
        subset = [c for c in sample if case_segment(c)["primary_intent"] == intent]
        out.append({"question": f"intenção '{intent}' responde a título dedicado?",
                    "answer": _rate(subset)})
    gains = [c for c in sample
             if any(_feature_value(c, k) is not None
                    for k in ("demand_coverage_before", "demand_coverage_after"))]
    out.append({"question": "subir a cobertura de demanda melhora o CTR?",
                "answer": _rate(gains)})
    return out
