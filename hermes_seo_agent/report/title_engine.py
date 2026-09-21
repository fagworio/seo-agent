"""FASE 5–10, 17, 18 — Motor combinatório de título (determinístico).

Fluxo obrigatório (nunca "CTR baixo -> gerar título"):

    GSC -> famílias -> demanda percentual -> baseline -> intenção ->
    rankability -> combinações -> score -> decisão -> título

Este módulo NÃO faz coleta e NÃO chama LLM: recebe a evidência já persistida
(GSC/GA4/Trends) e devolve decisão + evidência citável + explicação. As
fórmulas de rankability/headroom/confiança são as JÁ EXISTENTES em
``rankability_v2`` — reaproveitadas, nunca reimplementadas (FASE 6).

Score é ÍNDICE de decisão, nunca "probabilidade de rankear/melhorar":
reportado como "Title Opportunity Score: 78/100".
"""

from __future__ import annotations

import itertools
from typing import Any, Callable, Iterable, Sequence

from .query_families import (GENERIC_INTENT, INTENT_TITLE_PHRASES,
                             SEMANTIC_EQUIVALENTS, TRANSACTIONAL_INTENTS,
                             INCOMPATIBLE_PAIRS, entity_covered, expand_variants,
                             title_coverage, tokens, INTENT_LABELS, intent_phrases)
from .rankability_v2 import confidence_v2, headroom, query_rankability

MODEL_VERSION = "title-engine/1"

# FASE 7 — pesos do Title Candidate Score (soma = 1.0)
TITLE_WEIGHTS: dict[str, float] = {
    "demand_coverage": 0.35,
    "intent_fit": 0.20,
    "rankability": 0.15,
    "headroom": 0.10,
    "historical_success": 0.10,
    "trend": 0.05,
    "confidence": 0.05,
}

# FASE 5 — limites do combinatório
TOP_FAMILIES = 5
MAX_TITLE_INTENTS = 3
MIN_FAMILY_SHARE = 0.03          # share irrelevante -> fora
MIN_TRIO_SHARE = 0.15            # trio só com demanda material em cada intenção
MAX_SIGNIFICANT_TERMS = 7        # keyword stuffing
DEFAULT_MAX_LEN = 60

# FASE 8 — gates
EVIDENCE_CONFIDENCE_FLOOR = 0.5  # confidence_v2 abaixo disso -> insufficient_data
MIN_COVERAGE_GAIN = 0.05         # ganho mínimo de cobertura observada
MIN_TITLE_SCORE = 55.0           # índice mínimo (0..100) para propor
DEFAULT_MIN_IMPRESSIONS = 100.0
DEFAULT_MIN_FAMILY_IMPRESSIONS = 10.0
DEFAULT_MAX_POSITION = 30.0

# histórico neutro enquanto não há amostra suficiente (FASE 14)
NEUTRAL_HISTORICAL_SUCCESS = 0.5


# ---------------------------------------------------------------------------
# FASE 5 — Candidate Combination Engine
# ---------------------------------------------------------------------------

def _equivalent(a: str, b: str) -> bool:
    return any({a, b} <= group for group in SEMANTIC_EQUIVALENTS)


def _incompatible(a: str, b: str) -> bool:
    return any({a, b} <= pair for pair in INCOMPATIBLE_PAIRS)


def relevant_families(share: dict[str, Any], *, top_n: int = TOP_FAMILIES,
                      min_share: float = MIN_FAMILY_SHARE) -> list[dict[str, Any]]:
    """Top N famílias por observed_query_share (só intenções, não 'geral')."""
    out: list[dict[str, Any]] = []
    for family in (share.get("families") or []):
        if str(family.get("intent") or GENERIC_INTENT) == GENERIC_INTENT:
            continue
        share_value = family.get("share")
        if share_value is None or float(share_value) < min_share:
            continue
        out.append(family)
    out.sort(key=lambda f: (-float(f.get("share") or 0), str(f.get("family"))))
    return out[:max(int(top_n or TOP_FAMILIES), 1)]


def _combination_gate(intents: Sequence[str], families: Sequence[dict[str, Any]],
                      *, min_share: float) -> str | None:
    """Motivo de DESCARTE da combinação (None = válida)."""
    labels = list(intents)
    if len(labels) != len(set(labels)):
        return "duplicacao_semantica"
    for a, b in itertools.combinations(labels, 2):
        if _equivalent(a, b):
            return "duplicacao_semantica"
        if _incompatible(a, b):
            return "intencao_incompativel"
    transactional = [x for x in labels if x in TRANSACTIONAL_INTENTS]
    if len(transactional) > 1:
        return "intencao_incompativel"
    for family in families:
        value = family.get("share")
        if value is None or float(value) < min_share:
            return "share_irrelevante"
    if len(labels) >= 3 and any(float(f.get("share") or 0) < MIN_TRIO_SHARE
                               for f in families):
        return f"trios_exigem_share>={MIN_TRIO_SHARE:.0%}"
    significant = [t for t in tokens(" ".join(_intent_words(l) for l in labels))
                   if t not in ("e", "de", "do", "da")]
    if len(set(significant)) > MAX_SIGNIFICANT_TERMS:
        return "provável_keyword_stuffing"
    return None


def _intent_words(label: str) -> str:
    """Frase de TÍTULO da intenção (mesma tabela usada pela redação)."""
    phrase = INTENT_TITLE_PHRASES.get(label)
    if phrase:
        return phrase
    phrases = [p for p in intent_phrases(label) if " " not in p] or list(intent_phrases(label))
    if not phrases:
        return label.replace("_", " ")
    return min(phrases, key=len)


def _family_phrase(family: dict[str, Any]) -> str:
    return _intent_words(str(family.get("intent") or ""))


def combination_candidates(families: Sequence[dict[str, Any]], *,
                           entity: str = "", max_len: int = DEFAULT_MAX_LEN,
                           max_intents: int = MAX_TITLE_INTENTS,
                           min_share: float = MIN_FAMILY_SHARE,
                           title_terms: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Singles + pares + trios das famílias relevantes (<= 25 candidatos).

    Não gera todas as combinações possíveis: limita às top famílias por share,
    aplica os GATES (share irrelevante, intenção incompatível, duplicação
    semântica, keyword stuffing, entidade perdida, comprimento inviável,
    combinação não natural) e preserva o motivo do descarte para auditoria.
    """
    pool = [f for f in families if str(f.get("intent") or GENERIC_INTENT) != GENERIC_INTENT]
    term_variants = expand_variants(title_terms or [])
    out: list[dict[str, Any]] = []
    for size in range(1, min(int(max_intents), MAX_TITLE_INTENTS) + 1):
        for combo in itertools.combinations(pool, size):
            intents = [str(f.get("intent")) for f in combo]
            coverage = sum(float(f.get("share") or 0) for f in combo)
            reason = _combination_gate(intents, combo, min_share=min_share)
            phrase = " e ".join(_family_phrase(f) for f in combo)
            candidate = {
                "intents": intents,
                "families": [str(f.get("family")) for f in combo],
                "entity": entity,
                "phrase": f"{entity}: {phrase}".strip(": ").strip(),
                "observed_demand_coverage": round(coverage, 4),
                "intent_count": size,
                "discarded": reason,
                "discard_reason": reason,
                # ganho REAL de cobertura: só conta o que ainda não está no título
                "new_terms": [t for t in tokens(phrase)
                              if t not in term_variants and t not in ("e",)],
            }
            # entidade perdida / comprimento inviável / não natural
            if not reason and entity and not entity_covered(
                    entity, candidate["phrase"],
                    expand_variants(tokens(candidate["phrase"])) | term_variants):
                reason = candidate["discard_reason"] = "entidade_perdida"
            if not reason and len(candidate["phrase"]) > max_len:
                reason = candidate["discard_reason"] = "comprimento_inviavel"
            if not reason and size == 3 and phrase.count(" e ") < 2:
                reason = candidate["discard_reason"] = "combinacao_nao_natural"
            if not reason and not candidate["new_terms"]:
                reason = candidate["discard_reason"] = "sem_termo_novo"
            candidate["discarded"] = reason is not None
            out.append(candidate)
    out.sort(key=lambda c: (c["discarded"], -c["observed_demand_coverage"],
                            c["intent_count"]))
    return out


# ---------------------------------------------------------------------------
# FASE 6 — Query Rankability por FAMÍLIA (reaproveita rankability_v2)
# ---------------------------------------------------------------------------

def family_semantic_signals(family: dict[str, Any], *, title: str = "") -> dict[str, Any]:
    """Sinais semânticos MEDIDOS para a família (entradas do rankability).

    Só o que é medível com o dado em mãos: a página É sobre a entidade (as
    queries chegam nela), o título diz ou não diz a intenção/entidade, e a query
    tem forma interrogativa. ``h1``/``heading``/``body``/``related`` ficam
    ``None`` = DESCONHECIDO — o chamador que tem corpus deve passá-los via
    ``build_query_signals`` (rankability_signals). Nunca inventamos 0.5.
    """
    title_variants = expand_variants(tokens(title))
    entity = str(family.get("entity") or "")
    intent = str(family.get("intent") or "")
    intent_ok = any(all(expand_variants(tokens(alias)) & title_variants)
                    for alias in intent_phrases(intent)) if intent else False
    query = str((family.get("queries") or [""])[0]) if family.get("queries") else ""
    interrogative = bool(query) and (
        query.strip().endswith("?") or tokens(query)[:1] and
        str(tokens(query)[0]) in {"como", "qual", "quais", "quantos", "quantas",
                                  "quanto", "quando", "onde", "quem", "porque"})
    return {
        "entity_fit": 1.0 if entity_covered(entity, title, title_variants) else 0.4,
        "title_fit": 1.0 if intent_ok else (0.5 if entity else 0.0),
        "question_fit": 0.6 if interrogative else 0.0,
        "h1_fit": None,
        "heading_fit": None,
        "body_fit": None,
        "related_entity_fit": None,
        "measured": ["entity_fit", "title_fit", "question_fit"],
    }


def family_rankability(family: dict[str, Any], *, query_signals: dict[str, Any] | None = None,
                       cluster_signals: dict[str, Any] | None = None,
                       distribution: dict[str, Any] | None = None,
                       title: str = "", topic_authority: float | None = None,
                       as_percent: bool = False) -> dict[str, Any]:
    """Query Rankability da família (a página consegue competir por ESTA intenção?).

    Reaproveita ``rankability_v2.query_rankability`` — a MESMA fórmula usada por
    rankability-v2/opportunity/title-opportunities. Aqui só montamos os sinais
    (família -> sinais da query) quando o chamador não os traz do banco.
    """
    signals = dict(query_signals or {})
    signals.setdefault("keyword", family.get("family_id") or family.get("family"))
    signals.setdefault("impressions", family.get("impressions"))
    signals.setdefault("clicks", family.get("clicks"))
    signals.setdefault("position", family.get("weighted_position"))
    signals.setdefault("semantic", family_semantic_signals(family, title=title))
    # OBS: `setdefault` NÃO substitui chave existente com valor None — e
    # `build_query_signals()` devolve `topic_authority: None`. Sem este guard o
    # Topic Authority calculado simplesmente não entrava no observed_ease.
    if topic_authority is not None and signals.get("topic_authority") is None:
        signals["topic_authority"] = topic_authority
    dist = distribution or {
        "total": 1,
        "counts": {"top3": 0, "top10": 0, "top20": 0, "top50": 0},
        "shares": {"top3": 0.0, "top10": 0.0, "top20": 0.0, "top50": 0.0},
        "median_position": signals.get("position"),
        "avg_position": signals.get("position"),
    }
    cluster = dict(cluster_signals or {})
    cluster.setdefault("related_queries", 0)
    cluster.setdefault("related_top10_queries", 0)
    result = query_rankability(signals, cluster, dist, as_percent=as_percent)
    return result


# ---------------------------------------------------------------------------
# FASE 9 — Google Trends como ENRIQUECIMENTO por FAMÍLIA (uma vez por família)
# ---------------------------------------------------------------------------

def family_trends(trends_map: dict[str, dict[str, Any]] | None,
                  families: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Trends por FAMÍLIA (nunca por combinação) — reutiliza o cache do run.

    interest = máxima/ponderada das queries da família; momentum = média
    ponderada por impressões. Ausente NÃO é zero: ``interest=None`` e
    ``momentum=0`` com ``available=False``.
    """
    trends_map = trends_map or {}
    out: dict[str, dict[str, Any]] = {}
    for family in families:
        fid = str(family.get("family_id") or family.get("family"))
        weighted = 0.0
        weight = 0.0
        momentum = 0.0
        seen = 0
        for query, payload in _family_query_trends(family, trends_map):
            seen += 1
            interest = payload.get("interest")
            if not isinstance(interest, (int, float)):
                continue
            value = float(interest)
            w = 1.0
            weighted += value * w
            weight += w
            momentum += float(payload.get("momentum") or 0) * w
        out[fid] = {
            "available": seen > 0,
            "interest": round(weighted / weight, 1) if weight else None,
            "momentum": round(momentum / weight, 2) if weight else 0.0,
            "lookups": seen,
        }
    return out


def _family_query_trends(family: dict[str, Any],
                         trends_map: dict[str, dict[str, Any]],
                         ) -> list[tuple[str, dict[str, Any]]]:
    """Pares (query, payload) de Trends JÁ coletados para as queries da família."""
    out: list[tuple[str, dict[str, Any]]] = []
    for query in family.get("queries") or []:
        payload = trends_map.get(query)
        if isinstance(payload, dict):
            out.append((str(query), payload))
    return out


def trend_factor(trend: dict[str, Any] | None) -> float:
    """0..1 — Trends só AJUSTA (5% do score); não cria necessidade."""
    if not trend or not trend.get("available"):
        return 0.5
    base = 0.5
    interest = trend.get("interest")
    if isinstance(interest, (int, float)):
        base += (min(max(float(interest), 0.0), 100.0) / 100.0 - 0.5) * 0.6
    base += 0.1 * float(trend.get("momentum") or 0)
    return round(min(max(base, 0.0), 1.0), 3)


def page_headroom(position: Any, ctr: Any, baseline_verdict: dict[str, Any] | None) -> dict[str, Any]:
    """Headroom contra a referência do PRÓPRIO segmento (nunca um CTR inventado).

    Antes: ``p50 or 0.06`` — (a) transformava um P50 = 0 real em 6%; (b)
    reintroduzia um benchmark externo arbitrário, justamente o que o baseline
    próprio existe para eliminar. Sem P50 utilizável, o headroom é NEUTRO (0.5)
    com status explícito, e isso não vira evidência de oportunidade.
    """
    bucket = (baseline_verdict or {}).get("bucket") or {}
    p50 = bucket.get("p50")
    expected: float | None
    try:
        expected = float(p50) if p50 is not None else None
    except (TypeError, ValueError):
        expected = None
    if expected is None:
        return {"score": 0.5, "status": "unknown", "expected_ctr": None,
                "explanation": ("sem P50 do próprio segmento: headroom neutro "
                                "(nunca um CTR de referência inventado)")}
    if expected <= 0:
        return {"score": 0.5, "status": "degenerate", "expected_ctr": expected,
                "explanation": ("P50 do segmento é 0: não há referência de CTR "
                                "utilizável — headroom neutro")}
    score, why = headroom(position, ctr, expected)
    return {"score": score, "status": "measured", "expected_ctr": expected,
            "explanation": why}


def _headroom_value(value: Any) -> tuple[float, dict[str, Any]]:
    """Aceita tanto o dict de `page_headroom` quanto um escalar (compat)."""
    if isinstance(value, dict):
        return float(value.get("score") or 0.0), value
    return float(value or 0.0), {"score": float(value or 0.0), "status": "given"}


# ---------------------------------------------------------------------------
# FASE 10 — GA4 como sinal PÓS-CLIQUE no nível da página
# ---------------------------------------------------------------------------

GA4_AVAILABLE = "available"
GA4_INSUFFICIENT = "insufficient"
GA4_MISSING = "missing"
MIN_GA4_SESSIONS = 5


def ga4_evidence_status(ga4: dict[str, Any] | None) -> dict[str, Any]:
    """Status da evidência GA4 (nunca uma keyword: é a PÁGINA).

    available | insufficient | missing. GA4 ausente NÃO bloqueia nada — é
    ausência de evidência, e por isso rebaixa a confiança.
    """
    data = ga4 or {}
    try:
        sessions = float(data.get("sessions") or 0)
    except (TypeError, ValueError):
        sessions = 0.0
    if not data:
        status = GA4_MISSING
    elif sessions < MIN_GA4_SESSIONS:
        status = GA4_INSUFFICIENT
    else:
        status = GA4_AVAILABLE
    healthy: bool | None = None
    if status == GA4_AVAILABLE:
        er = data.get("engagement_rate")
        try:
            healthy = float(er) >= 0.30 if er is not None else None
        except (TypeError, ValueError):
            healthy = None
    return {
        "status": status,
        "sessions": sessions or None,
        "engagement_rate": data.get("engagement_rate"),
        "post_click_healthy": healthy,
        "question": "a página satisfaz quem chega do Google? (não: qual keyword)",
        "blocks_decision": False,
    }


def finalize_titles(*, generated: Sequence[dict[str, Any]], candidate: dict[str, Any],
                    families: Sequence[dict[str, Any]],
                    shares: dict[str, float] | None = None,
                    rankability: dict[str, float] | None = None,
                    headroom_value: Any = 0.0,
                    trends: dict[str, dict[str, Any]] | None = None,
                    confidence_score: float = 0.0,
                    historical_success: float | None = None,
                    weights: dict[str, float] | None = None,
                    tolerance: float = 0.02) -> dict[str, Any]:
    """Mede e pontua o TÍTULO final — não a combinação abstrata (FASE 7/15).

    A combinação `idade + poderes` pode cobrir 78%, mas o gerador aceitava
    "Gojo: idade" (só 42%) porque o validador só proibia intenção SEM evidência.
    Aqui cada título gerado é remedido com `title_coverage` (mesmas famílias e
    shares) e só é aceito se cobrir o candidato pontuado (tolerância de 2 p.p.).
    O score devolvido usa a cobertura MEDIDA do texto — a cadeia
    evidência → score → título passa a fechar.
    """
    target = float(candidate.get("observed_demand_coverage") or 0.0)
    hr_score, hr_detail = _headroom_value(headroom_value)
    scored: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in generated or []:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        measured = title_coverage(title, families, shares=shares)
        coverage = measured.get("observed_demand_coverage")
        coverage_value = float(coverage) if coverage is not None else 0.0
        if coverage_value + float(tolerance) < target:
            rejected.append({
                "title": title, "measured_coverage": round(coverage_value, 4),
                "reason": (f"cobertura medida {coverage_value:.0%} < candidato "
                           f"{target:.0%}"),
                "covered_families": measured.get("covered_families"),
            })
            continue
        features = candidate_features(
            candidate=candidate, families=families, rankability=rankability or {},
            headroom_value=hr_score, trends=trends or {},
            confidence_score=confidence_score, historical_success=historical_success)
        features["demand_coverage"] = round(coverage_value, 4)
        scored.append({
            "title": title,
            "template": item.get("template"),
            "source": item.get("source"),
            "intents": item.get("intents"),
            "measured_coverage": round(coverage_value, 4),
            "candidate_coverage": round(target, 4),
            "covered_families": measured.get("covered_families"),
            "uncovered_families": measured.get("uncovered_families"),
            "title_score": weighted_title_score(features, weights),
        })
    scored.sort(key=lambda item: (-float(item["title_score"]["score"]), len(item["title"])))
    return {
        "titles": scored,
        "best": scored[0] if scored else None,
        "rejected": rejected,
        "headroom": hr_detail,
        "measured": "cobertura e score recalculados SOBRE O TÍTULO (não sobre a combinação)",
    }


# ---------------------------------------------------------------------------
# FASE 7 — Title Candidate Score
# ---------------------------------------------------------------------------

def candidate_features(*, candidate: dict[str, Any], families: Sequence[dict[str, Any]],
                       rankability: dict[str, float], headroom_value: float,
                       trends: dict[str, dict[str, Any]],
                       confidence_score: float,
                       historical_success: float | None = None) -> dict[str, float]:
    """Features (0..1) do Title Candidate Score — todas determinísticas."""
    by_id = {str(f.get("family") or f.get("family_id")): f for f in families}
    members = [by_id[fid] for fid in candidate.get("families", []) if fid in by_id]
    fit_parts: list[float] = []
    for family in members:
        intents = [i for i in (family.get("intents") or []) if i != GENERIC_INTENT]
        intent = str(family.get("intent") or GENERIC_INTENT)
        if intent == GENERIC_INTENT:
            fit_parts.append(0.3)
        elif len(intents) <= 1:
            fit_parts.append(1.0)
        else:
            fit_parts.append(0.7)
    rank_parts = [rankability.get(str(f.get("family") or f.get("family_id")), 0.0)
                  for f in members]
    trend_parts = [trend_factor(trends.get(str(f.get("family") or f.get("family_id"))))
                   for f in members]
    return {
        "demand_coverage": min(max(float(candidate.get("observed_demand_coverage") or 0.0), 0.0), 1.0),
        "intent_fit": round(sum(fit_parts) / len(fit_parts), 3) if fit_parts else 0.0,
        "rankability": round(sum(rank_parts) / len(rank_parts), 3) if rank_parts else 0.0,
        "headroom": round(min(max(float(headroom_value or 0.0), 0.0), 1.0), 3),
        "historical_success": round(float(
            NEUTRAL_HISTORICAL_SUCCESS if historical_success is None else historical_success), 3),
        "trend": round(sum(trend_parts) / len(trend_parts), 3) if trend_parts else 0.5,
        "confidence": round(min(max(float(confidence_score or 0.0), 0.0), 1.0), 3),
    }


def weighted_title_score(features: dict[str, float],
                         weights: dict[str, float] | None = None) -> dict[str, Any]:
    """Índice de decisão 0..100 (NUNCA "chance de melhorar")."""
    use = dict(weights or TITLE_WEIGHTS)
    total_weight = sum(use.values()) or 1.0
    score = sum(float(features.get(k) or 0.0) * w for k, w in use.items()) / total_weight
    return {
        "score": round(score * 100, 1),
        "scale": "0-100",
        "label": f"Title Opportunity Score: {round(score * 100, 1)}/100",
        "semantics": "índice determinístico de decisão — não é probabilidade de rankear",
        "weights": {k: round(v, 3) for k, v in use.items()},
        "factors": {k: round(float(features.get(k) or 0.0), 3) for k in use},
        "model_version": MODEL_VERSION,
    }


# ---------------------------------------------------------------------------
# FASE 8 — Gates obrigatórios (score alto NÃO autoriza sozinho)
# ---------------------------------------------------------------------------

def title_gates(*, page: dict[str, Any], families: Sequence[dict[str, Any]],
                baseline_verdict: dict[str, Any] | None, coverage: dict[str, Any],
                candidate: dict[str, Any] | None, ga4: dict[str, Any] | None,
                confidence_score: float,
                entity: str = "",
                min_impressions: float = DEFAULT_MIN_IMPRESSIONS,
                min_family_impressions: float = DEFAULT_MIN_FAMILY_IMPRESSIONS,
                max_position: float = DEFAULT_MAX_POSITION,
                confidence_floor: float = EVIDENCE_CONFIDENCE_FLOOR,
                min_coverage_gain: float = MIN_COVERAGE_GAIN,
                signal_window_aligned: bool | None = None,
                ) -> dict[str, Any]:
    """Gates independentes do `review_title` (FASE 8).

    A ausência de dado NUNCA é lida como zero: gates que dependem de dado
    ausente ficam False com o motivo declarado (`notes`).

    ``signal_window_aligned``: a janela dos sinais persistidos (rankability,
    cluster) é a MESMA janela das páginas/famílias/baseline? Uma decisão = uma
    janela; quando não é, a evidência é temporalmente heterogênea e o gate
    bloqueia o `review_title` (o chamador rebaixa para `investigate_cause`).
    ``None`` = não informado (sem gate: compatível com chamadas antigas).
    """
    position = page.get("position")
    impressions = float(page.get("impressions") or 0)
    demand_family = max((float(f.get("impressions") or 0) for f in families), default=0.0)
    verdict = str((baseline_verdict or {}).get("verdict") or "")
    current_coverage = coverage.get("observed_demand_coverage")
    candidate_coverage = (candidate or {}).get("observed_demand_coverage")
    gain = None
    if candidate_coverage is not None and current_coverage is not None:
        gain = round(float(candidate_coverage) - float(current_coverage), 4)

    gates: dict[str, Any] = {
        "page_impressions_sufficient": impressions >= float(min_impressions),
        "query_family_demand_sufficient": bool(families) and demand_family >= float(min_family_impressions),
        "baseline_anomaly": verdict in {"below_p10", "below_comparable"},
        "title_coverage_gap": bool(gain is not None and gain >= float(min_coverage_gain)),
        "position_actionable": position is not None and float(position) <= float(max_position),
        "entity_preserved": bool(candidate) and entity_covered(
            entity, str((candidate or {}).get("phrase") or ""),
            expand_variants(tokens(str((candidate or {}).get("phrase") or "")))) if entity else bool(candidate),
        "evidence_confidence": float(confidence_score or 0.0) >= float(confidence_floor),
        # None = janela não informada (não é "alinhado" nem "desalinhado")
        "signal_window_aligned": (None if signal_window_aligned is None
                                  else bool(signal_window_aligned)),
    }
    ga4_status = ga4_evidence_status(ga4)
    notes: list[str] = []
    if not families:
        notes.append("sem famílias de query observadas nesta coleta")
    if verdict == "low":
        notes.append("CTR entre P10 e P25 (sinal fraco): investigar, não reescrever título")
    if verdict not in {"below_p10", "below_comparable", "low"}:
        notes.append(f"CTR não é anômalo no próprio segmento (veredicto {verdict or 'n/d'})")
    if position is None:
        notes.append("sem posição: cadeia incompleta (não é acionável)")
    if ga4_status["status"] == GA4_MISSING:
        notes.append("GA4 ausente: não bloqueia, mas rebaixa a confiança")
    if ga4_status["status"] == GA4_INSUFFICIENT:
        notes.append("GA4 com amostra insuficiente: não bloqueia, confiança não sobe")
    if signal_window_aligned is False:
        notes.append("janela dos sinais (rankability/cluster) difere da janela da "
                     "decisão: evidência temporalmente heterogênea — investigar, "
                     "não reescrever título")
    gates["_context"] = {
        "coverage_gain": gain,
        "current_coverage": current_coverage,
        "candidate_coverage": candidate_coverage,
        "family_demand_impressions": round(demand_family, 2),
        "ga4": ga4_status,
        "notes": notes,
    }
    critical = ("page_impressions_sufficient", "query_family_demand_sufficient",
                "baseline_anomaly", "title_coverage_gap", "position_actionable",
                "entity_preserved", "evidence_confidence")
    gates["passed"] = all(gates[k] for k in critical)
    gates["failed"] = [k for k in critical if not gates[k]]
    return gates


# ---------------------------------------------------------------------------
# Decisão (FASE 8) + Evidence Contract (FASE 17) + Explicabilidade (FASE 18)
# ---------------------------------------------------------------------------

def _confidence_label(*, gates: dict[str, Any], ga4_status: dict[str, Any],
                      confidence_score: float) -> str:
    if not gates.get("evidence_confidence"):
        return "low"
    if not gates.get("passed"):
        return "medium"
    # GA4 ausente/insuficiente é AUSÊNCIA DE EVIDÊNCIA: não bloqueia, mas não
    # permite `high` (mesma regra já aplicada em SEO-INC-019b).
    if ga4_status.get("status") == GA4_AVAILABLE and ga4_status.get("post_click_healthy") is False:
        return "medium"
    if ga4_status.get("status") in {GA4_MISSING, GA4_INSUFFICIENT}:
        return "medium"
    return "high"


def decide_title(
    *,
    url: str = "",
    title: str = "",
    page: dict[str, Any],
    baseline_verdict: dict[str, Any] | None,
    families: Sequence[dict[str, Any]],
    coverage: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    rankability: dict[str, float] | None = None,
    headroom_value: Any = 0.0,
    trends: dict[str, dict[str, Any]] | None = None,
    ga4: dict[str, Any] | None = None,
    confidence_score: float | None = None,
    historical_success: float | None = None,
    historical_success_fn: Callable[[int, str | None], dict[str, Any]] | None = None,
    title_evaluator: Callable[..., dict[str, Any]] | None = None,
    observation_ratio: float | None = None,
    observed_impressions: float | None = None,
    corpus_available: bool | None = None,
    semantic_evidence: float | None = None,
    signal_window_aligned: bool | None = None,
    weights: dict[str, float] | None = None,
    model_version: str = MODEL_VERSION,
    weights_version: int = 0,
    min_impressions: float = DEFAULT_MIN_IMPRESSIONS,
    min_family_impressions: float = DEFAULT_MIN_FAMILY_IMPRESSIONS,
    max_position: float = DEFAULT_MAX_POSITION,
    confidence_floor: float = EVIDENCE_CONFIDENCE_FLOOR,
    min_coverage_gain: float = MIN_COVERAGE_GAIN,
    min_title_score: float = MIN_TITLE_SCORE,
) -> dict[str, Any]:
    """Decisão determinística completa + evidência citável + explicação.

    Retorna o EVIDENCE CONTRACT (FASE 17) com:
      decision ∈ {review_title, no_title_change, investigate_cause, gather_more_data}
      confidence ∈ {high, medium, low}
      page, baseline, query_families, current_title, candidate, rankability,
      ga4, trends, checks, reason, explanation.
    """
    ga4_status = ga4_evidence_status(ga4)
    # Impressões OBSERVADAS das queries (não um share!): o chamador pode passar
    # demand["observed_impressions"]; senão somamos as famílias.
    if observed_impressions is None:
        observed_impressions = sum(float(f.get("impressions") or 0) for f in families)
    # Confiança: corpus e evidência semântica têm de vir do que foi REALMENTE
    # medido — ter famílias do GSC não prova corpus nem sinais semânticos.
    if corpus_available is None:
        corpus_available = bool(families)
    if semantic_evidence is None:
        semantic_evidence = 0.7 if families else 0.0
    confidence = confidence_v2({
        "gsc_sample": min(float(page.get("impressions") or 0) / 5000.0, 1.0),
        "windows": confidence_score if confidence_score is not None else 0.6,
        "ga4_available": 1.0 if ga4_status["status"] == GA4_AVAILABLE else 0.0,
        "corpus_available": 1.0 if corpus_available else 0.0,
        "semantic_evidence": float(semantic_evidence),
        "query_stability": 0.6,
        "technical_known": 0.7,
    })
    evidence_conf = float(confidence_score) if confidence_score is not None else float(confidence["score"])

    ranked: list[dict[str, Any]] = []
    evaluated: list[dict[str, Any]] = []
    hr_score, hr_detail = _headroom_value(headroom_value)
    for candidate in candidates:
        # histórico EMPÍRICO por candidato (posição × nº de intenções × intenção):
        # um par e um trio não têm o mesmo histórico de sucesso (FASE 14).
        intents = [str(i) for i in (candidate.get("intents") or [])]
        history: dict[str, Any] | None = None
        hs_value = historical_success
        if callable(historical_success_fn):
            history = historical_success_fn(len(intents), intents[0] if intents else None) or {}
            hs_value = history.get("value")
        features = candidate_features(
            candidate=candidate, families=families,
            rankability=rankability or {}, headroom_value=hr_score,
            trends=trends or {}, confidence_score=evidence_conf,
            historical_success=hs_value)
        scored = weighted_title_score(features, weights)
        item = {**candidate, "features": features, "title_score": scored,
                "history": history}
        evaluated.append(item)
        if not candidate.get("discarded"):
            ranked.append(item)
    ranked.sort(key=lambda c: -float(c["title_score"]["score"]))
    best = ranked[0] if ranked else None

    # FASE 7/15: o objeto PONTUADO final é o título — mede a cobertura do texto
    # gerado e rejeita o candidato que nenhum título consegue representar.
    title_options: dict[str, Any] | None = None
    candidate_failed_reason: str | None = None
    if best is not None and callable(title_evaluator):
        eval_context = {"confidence_score": evidence_conf, "headroom": hr_detail,
                        "observation_ratio": observation_ratio}
        title_options = title_evaluator(best, eval_context) or {}
        chosen = title_options.get("best")
        best = dict(best)
        if chosen:
            best["title"] = chosen.get("title")
            best["observed_demand_coverage"] = chosen.get("measured_coverage")
            best["combination_coverage"] = chosen.get("candidate_coverage")
            best["title_score"] = chosen.get("title_score")
        else:
            candidate_failed_reason = (
                "nenhum título validado atinge a cobertura do candidato pontuado")
            best = None

    gates = title_gates(
        page=page, families=families,
        baseline_verdict=baseline_verdict, coverage=coverage, candidate=best,
        ga4=ga4, confidence_score=evidence_conf, entity=str(page.get("entity") or ""),
        min_impressions=min_impressions,
        min_family_impressions=min_family_impressions, max_position=max_position,
        confidence_floor=confidence_floor, min_coverage_gain=min_coverage_gain,
        signal_window_aligned=signal_window_aligned)

    # ---- decisão (ordem = gravidade da lacuna) ---------------------------
    if not gates["page_impressions_sufficient"] or not gates["query_family_demand_sufficient"]:
        decision = "gather_more_data"
    elif not gates["position_actionable"]:
        decision = "gather_more_data"
    elif not gates["title_coverage_gap"]:
        decision = "no_title_change"
    elif not gates["baseline_anomaly"]:
        decision = "no_title_change"
    elif not gates["entity_preserved"]:
        decision = "no_title_change"
    elif not gates["evidence_confidence"]:
        decision = "investigate_cause"
    elif ga4_status["status"] == GA4_AVAILABLE and ga4_status.get("post_click_healthy") is False:
        decision = "investigate_cause"
    elif signal_window_aligned is False:
        # A cadeia passaria para review_title, mas a evidência de rankability
        # veio de OUTRA janela: os dados existem, só não estão alinhados no tempo
        # -> investigar, nunca publicar título com essa mistura.
        decision = "investigate_cause"
    elif best is None or float(best["title_score"]["score"]) < float(min_title_score):
        decision = "no_title_change"
    else:
        decision = "review_title"

    label = _confidence_label(gates=gates, ga4_status=ga4_status,
                              confidence_score=evidence_conf)
    observed_universe = float((coverage.get("observed_share_universe") or 0) or 0)
    if decision == "gather_more_data":
        # Sem universo observado a cadeia nem começou: confiança baixa (ausência
        # de dado nunca vira certeza).
        label = "medium" if (families and observed_universe > 0) else "low"
    elif decision in {"no_title_change", "investigate_cause"} and label == "high":
        label = "medium"
    # FASE 7/observação: se as queries conhecidas explicam POUCO das impressões
    # da página, os percentuais de família são uma fatia estreita — a confiança
    # não pode ser `high` (não bloqueia; o share continua sendo o medido).
    if (observation_ratio is not None and float(observation_ratio) < 0.2
            and label == "high"):
        label = "medium"
    # Janela desalinhada = evidência temporalmente heterogênea: nunca `high`.
    if signal_window_aligned is False and label == "high":
        label = "medium"

    contract = {
        "decision": decision,
        "confidence": label,
        "url": url,
        "model_version": model_version,
        "weights_version": weights_version,
        "page": dict(page),
        "baseline": {
            "context": (baseline_verdict or {}).get("context", ""),
            "level": (baseline_verdict or {}).get("level", ""),
            "sample_size": (baseline_verdict or {}).get("sample_size", 0),
            "p10": ((baseline_verdict or {}).get("bucket") or {}).get("p10"),
            "p25": ((baseline_verdict or {}).get("bucket") or {}).get("p25"),
            "p50": ((baseline_verdict or {}).get("bucket") or {}).get("p50"),
            "verdict": (baseline_verdict or {}).get("verdict", ""),
            "window_start": (baseline_verdict or {}).get("baseline_window_start", ""),
            "window_end": (baseline_verdict or {}).get("baseline_window", ""),
            "source": (baseline_verdict or {}).get("baseline_source", ""),
        },
        "observation": {
            "observed_impressions": round(float(observed_impressions or 0), 2),
            "page_impressions": page.get("impressions"),
            "query_observation_ratio": observation_ratio,
            "status": ("unknown" if observation_ratio is None else
                       "well_observed" if float(observation_ratio) >= 0.5 else
                       "partial" if float(observation_ratio) >= 0.2 else "thin"),
            "note": ("impressões OBSERVADAS das queries / impressões da página; "
                     "o share das famílias é do universo observado"),
        },
        "headroom": hr_detail,
        "query_families": [
            {"family": f.get("family"), "intent": f.get("intent"),
             "entity": f.get("entity"), "impressions": f.get("impressions"),
             "share": f.get("share"), "queries": f.get("queries")}
            for f in families],
        "current_title": {"title": coverage.get("title") or title,
                          "coverage": coverage.get("observed_demand_coverage"),
                          "covered_families": coverage.get("covered_families"),
                          "uncovered_families": coverage.get("uncovered_families"),
                          "generic_share": coverage.get("generic_share")},
        "candidate": ({
            "intents": best["intents"],
            "families": best["families"],
            "phrase": best["phrase"],
            "title": best.get("title"),
            "observed_demand_coverage": best["observed_demand_coverage"],
            "combination_coverage": best.get("combination_coverage",
                                             best["observed_demand_coverage"]),
            "score": best["title_score"]["score"],
            "score_label": best["title_score"]["label"],
            "factors": best["title_score"]["factors"],
            "weights": best["title_score"]["weights"],
            "history": best.get("history"),
            "title_options": (title_options or {}).get("titles"),
            "titles_rejected": (title_options or {}).get("rejected"),
            "scored_object": "título (cobertura medida no texto gerado)",
        } if best else None),
        "candidate_failed_reason": candidate_failed_reason,
        "candidates_evaluated": [
            {"intents": c["intents"], "coverage": c["observed_demand_coverage"],
             "score": c["title_score"]["score"], "discarded": bool(c.get("discarded")),
             "history": (c.get("history") or {}).get("value"),
             "discard_reason": c.get("discard_reason")} for c in
            sorted(evaluated, key=lambda x: -float(x["title_score"]["score"]))[:10]],
        "rankability": {k: round(float(v), 3) for k, v in (rankability or {}).items()},
        "ga4": ga4_status,
        "trends": {k: v for k, v in (trends or {}).items()},
        "checks": {k: v for k, v in gates.items() if not k.startswith("_")},
        "checks_context": gates.get("_context", {}),
        "confidence_detail": confidence,
        "evidence_meta": {
            "gsc": "search_analytics_query_page (queries principais observadas)",
            "coverage": "partial",
            "note": ("share do universo OBSERVADO; ausência de dado não é zero; "
                     "nenhuma chamada a modelo foi feita nesta análise"),
        },
    }
    contract["reason"] = explain_decision(contract)
    contract["explanation"] = render_explanation(contract)
    return contract


def explain_decision(contract: dict[str, Any]) -> list[str]:
    """Por que esta alteração está sendo proposta? (linhas citáveis)"""
    lines: list[str] = []
    coverage = contract.get("current_title") or {}
    current = coverage.get("coverage")
    if current is not None:
        lines.append(f"Título atual cobre aproximadamente {float(current)*100:.0f}% "
                     f"da demanda observada.")
    families = [f for f in (contract.get("query_families") or [])
                if f.get("intent") and f["intent"] != GENERIC_INTENT]
    uncovered = set(coverage.get("uncovered_families") or [])
    for family in families[:3]:
        share = family.get("share")
        share_txt = f"{float(share)*100:.0f}%" if share is not None else "n/d"
        state = "não está representada no título" if family["family"] in uncovered \
            else "já está coberta"
        lines.append(f"A família \"{family['intent']}\" representa {share_txt} das "
                     f"impressões observadas e {state}.")
    candidate = contract.get("candidate") or {}
    if candidate:
        intents = " + ".join(candidate.get("intents") or [])
        cov = candidate.get("observed_demand_coverage")
        combination = candidate.get("combination_coverage")
        if combination is not None and cov is not None and abs(float(combination) - float(cov)) > 0.005:
            lines.append(f"A combinação {intents} cobria {float(combination)*100:.0f}% e o "
                         f"título proposto cobre {float(cov)*100:.0f}% (cobertura MEDIDA "
                         f"no texto).")
        elif cov is not None:
            lines.append(f"A combinação {intents} cobre aproximadamente "
                         f"{float(cov)*100:.0f}% da demanda observada.")
        if candidate.get("title"):
            lines.append(f"Título proposto: \"{candidate['title']}\".")
        lines.append(str(candidate.get("score_label") or ""))
    if contract.get("candidate_failed_reason"):
        lines.append(contract["candidate_failed_reason"])
    observation = contract.get("observation") or {}
    if observation.get("query_observation_ratio") is not None:
        lines.append(f"As queries observadas explicam {float(observation['query_observation_ratio'])*100:.0f}% "
                     f"das impressões da página ({observation.get('status')}).")
    checks = contract.get("checks") or {}
    if checks.get("signal_window_aligned") is False:
        lines.append("A janela dos sinais de rankability/cluster difere da janela da "
                     "decisão (uma decisão = uma janela): evidência temporalmente "
                     "heterogênea — investigar, não reescrever título.")
    headroom_detail = contract.get("headroom") or {}
    if headroom_detail.get("status") in {"unknown", "degenerate"}:
        lines.append(f"Headroom {headroom_detail.get('status')}: "
                     f"{headroom_detail.get('explanation')}.")
    baseline = contract.get("baseline") or {}
    if baseline.get("verdict") in {"below_p10", "below_comparable"}:
        lines.append(f"CTR atual está abaixo do P10 de "
                     f"{int(baseline.get('sample_size') or 0)} páginas comparáveis "
                     f"do próprio site ({baseline.get('context') or 'n/d'}).")
    elif baseline.get("verdict") == "low":
        lines.append("CTR entre P10 e P25 do segmento (sinal fraco): investigar.")
    elif baseline.get("verdict"):
        lines.append(f"CTR não é anômalo no próprio segmento ({baseline['verdict']}).")
    page = contract.get("page") or {}
    if page.get("position") is not None:
        lines.append(f"Posição média {float(page['position']):.1f} indica "
                     f"{'visibilidade suficiente' if float(page['position']) <= DEFAULT_MAX_POSITION else 'visibilidade ainda insuficiente'}.")
    ga4 = contract.get("ga4") or {}
    if ga4.get("status") == GA4_AVAILABLE:
        if ga4.get("post_click_healthy") is False:
            lines.append("GA4 mostra engajamento pós-clique baixo (investigar causa).")
        else:
            lines.append("GA4 mostra engajamento pós-clique saudável.")
    elif ga4.get("status") == GA4_INSUFFICIENT:
        lines.append("GA4 com amostra insuficiente: confiança não sobe (não bloqueia).")
    else:
        lines.append("GA4 ausente: ausência de evidência, não evidência de problema.")
    for note in (contract.get("checks_context") or {}).get("notes", []):
        lines.append(note)
    lines.append(f"Decisão: {str(contract.get('decision','')).upper().replace('_', ' ')}")
    lines.append(f"Confiança: {str(contract.get('confidence','')).upper()}")
    return [line for line in lines if line]


def render_explanation(contract: dict[str, Any]) -> str:
    """Explicação em texto (interface/CLI) — 'por que esta proposta?'"""
    return "\n".join(contract.get("reason") or explain_decision(contract))
