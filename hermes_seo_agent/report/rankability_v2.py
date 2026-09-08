"""M5-V2 — Rankability V2 e Opportunity Engine V2 (roadmap R1–R5).

Separa os conceitos que hoje estavam misturados:

  * TOPIC AUTHORITY  — o site é forte no assunto? (cobertura, visibilidade,
    força de ranking, autoridade interna, engajamento relativo, momentum,
    saúde técnica).
  * QUERY RANKABILITY — uma página/cluster consegue competir por ESTA
    intenção? (fit semântico, tração da query, autoridade histórica em queries
    semelhantes, dificuldade observada).
  * HEADROOM — quanto de chance de cliques ainda há (posição × CTR).
  * CONFIDENCE — quão confiável é a medição (amostra, janelas, fontes).

100% determinístico, sem LLM nem API externa (sem DataForSEO/Keyword Planner).
O Opportunity Engine V2 usa SCORE PONDERADO + GATES (não multiplica tudo).

Semântica de score: cada fator em [0,1]; score final em [0,1] (ou 0..100 quando
``as_percent=True``). Nunca "probabilidade de rankear": é um índice calibrável
por resultados medidos (M8).
"""

from __future__ import annotations

from typing import Any, Iterable

# R1 — pesos do Topic Authority (soma = 1.0)
TOPIC_WEIGHTS = {
    "coverage": 0.20,
    "visibility": 0.20,
    "ranking_strength": 0.15,
    "internal_authority": 0.15,
    "engagement": 0.10,
    "momentum": 0.10,
    "technical_health": 0.10,
}

# R1 — pesos do Query Rankability (soma = 1.0)
QUERY_WEIGHTS = {
    "semantic_fit": 0.35,
    "query_traction": 0.30,
    "related_authority": 0.25,
    "observed_difficulty": 0.10,
}

# R5 — pesos do Opportunity Engine V2 (soma = 1.0)
OPPORTUNITY_WEIGHTS = {
    "rankability": 0.30,
    "demand": 0.25,
    "headroom": 0.20,
    "momentum": 0.15,
    "strategic_fit": 0.10,
}

# R5 — gates (problemas graves anulam; não são "saltos" de peso)
GATES = {
    "relevant": 1.0,          # fora do território -> descarta
    "indexable": 1.0,         # noindex/404/robots -> 0
    "confidence": 0.25,       # abaixo disso -> insufficient_data (gate, não score)
}


# --------------------------------------------------------------------------
# R2 — distribuição de rankings (queries por faixa Top3/10/20/50)
# --------------------------------------------------------------------------

def query_distribution(positions: list[float]) -> dict[str, Any]:
    """Agrega posições em faixas Top3/Top10/Top20/Top50 + mediana/média.

    ``positions``: lista de posições (1..N) das queries do cluster/página.
    """
    total = len(positions)
    buckets = {
        "top3": sum(1 for p in positions if p <= 3),
        "top10": sum(1 for p in positions if p <= 10),
        "top20": sum(1 for p in positions if p <= 20),
        "top50": sum(1 for p in positions if p <= 50),
    }
    shares = {k: round(v / total, 4) if total else 0.0 for k, v in buckets.items()}
    import statistics
    med = statistics.median(positions) if total else None
    avg = round(sum(positions) / total, 2) if total else None
    return {
        "total": total,
        "counts": buckets,
        "shares": shares,
        "median_position": med,
        "avg_position": avg,
    }


def ranking_strength(dist: dict[str, Any]) -> tuple[float, str]:
    """R1 — força de ranking a partir da distribuição ponderada."""
    shares = dist.get("shares", {})
    strength = (
        shares.get("top3", 0.0) * 1.00
        + shares.get("top10", 0.0) * 0.75
        + shares.get("top20", 0.0) * 0.40
        + shares.get("top50", 0.0) * 0.10
    )
    strength = min(strength, 1.0)
    c = dist.get("counts", {})
    why = (f"ranking: {c.get('top3', 0)} T3 · {c.get('top10', 0)} T10 · "
           f"{c.get('top20', 0)} T20 · {c.get('top50', 0)} T50")
    return round(strength, 3), why


def historical_visibility(cluster: dict[str, Any]) -> tuple[float, str]:
    """R1 — visibilidade observada (impressões, cliques, share de Top10)."""
    impressions = float(cluster.get("impressions", 0) or 0)
    if impressions <= 0:
        return 0.0, "sem impressões GSC no cluster"
    vis = min(impressions / 10_000, 1.0)  # satura em 10k impressões
    return round(vis, 3), f"{impressions:.0f} impressões no cluster"


# --------------------------------------------------------------------------
# R1 — Topic Authority
# --------------------------------------------------------------------------

def _coverage_depth(cluster: dict[str, Any]) -> tuple[float, str]:
    """R1 — profundidade de cobertura: posts + subtópicos + entidades + perguntas."""
    posts = int(cluster.get("posts", 0) or 0)
    entities = int(cluster.get("entities", 0) or 0)
    sections = int(cluster.get("sections", 0) or 0)
    questions = int(cluster.get("questions", 0) or 0)
    # satura posts em 20, entidades em 12, seções em 60, perguntas em 10
    components = {
        "posts": min(posts / 20, 1.0),
        "entities": min(entities / 12, 1.0),
        "sections": min(sections / 60, 1.0),
        "questions": min(questions / 10, 1.0),
    }
    score = (components["posts"] * 0.4 + components["entities"] * 0.25
             + components["sections"] * 0.25 + components["questions"] * 0.10)
    why = (f"{posts} posts · {entities} entidades · {sections} seções · "
           f"{questions} perguntas")
    return round(score, 3), why


def _technical_health(cluster: dict[str, Any]) -> tuple[float, str]:
    """R1 — saúde técnica: indexável, HTTP 200, canonical, robôs, sitemap, CWV.

    ``None`` = desconhecido (não bloqueia — só True/FALSE explicitamente
    bloqueiam), para não zerar o score quando o dado não foi coletado.
    """
    checks = {
        "indexable": cluster.get("indexable"),
        "http_ok": cluster.get("http_ok"),
        "canonical_ok": cluster.get("canonical_ok"),
        "in_sitemap": cluster.get("in_sitemap"),
        "indexed": cluster.get("google_indexed"),
        "cwv_ok": cluster.get("cwv_ok"),
    }
    # falhas duras apenas quando EXPLÍCITAMENTE False; None/True não bloqueiam.
    blocking = [k for k, v in checks.items() if k != "cwv_ok" and v is False]
    if blocking:
        return 0.0, f"bloqueio técnico: {', '.join(blocking)}"
    score = 1.0
    if checks["cwv_ok"] is False:
        score = 0.85
        return round(score, 3), "CWV abaixo do ideal (penalidade leve)"
    if checks["cwv_ok"] is None:
        score = 0.9
        return round(score, 3), "CWV desconhecido (sem penalidade dura)"
    return 1.0, "técnica saudável (indexável, HTTP 200, canonical, sitemap, indexado)"


def _relative_engagement(cluster: dict[str, Any]) -> tuple[float, str]:
    """R1 — engajamento RELATIVO (vs média do site/categoria), não bruto."""
    rate = cluster.get("ga4_engagement_rate")
    baseline = cluster.get("site_engagement_rate")
    category = cluster.get("category_engagement_rate")
    if rate is None:
        return 0.0, "sem engajamento GA4 disponível"
    base = category if category is not None else baseline
    if base is None:
        score = 0.5
        return round(score, 3), f"engajamento {rate:.0%} sem baseline de comparação"
    # relativo: 60% em relação à base = score neutro (0.5); 120% = 1.0
    relative = rate / base if base else 0.0
    score = max(0.0, min((relative - 0.6) / 0.6, 1.0))
    return round(score, 3), f"engajamento {rate:.0%} vs base {base:.0%} (rel. {relative:.0%})"


def topic_authority(cluster: dict[str, Any], /, *, as_percent: bool = False) -> dict[str, Any]:
    """R1 — Topic Authority Score (site é forte no assunto?)."""
    dist = query_distribution(cluster.get("positions", []))
    strength, strength_why = ranking_strength(dist)
    factors: dict[str, dict[str, Any]] = {
        "coverage": _factor(_coverage_depth(cluster), TOPIC_WEIGHTS["coverage"]),
        "visibility": _factor(historical_visibility(cluster), TOPIC_WEIGHTS["visibility"]),
        "ranking_strength": _factor((strength, strength_why), TOPIC_WEIGHTS["ranking_strength"]),
        "internal_authority": _factor(_internal_authority(cluster), TOPIC_WEIGHTS["internal_authority"]),
        "engagement": _factor(_relative_engagement(cluster), TOPIC_WEIGHTS["engagement"]),
        "momentum": _factor(_momentum(cluster), TOPIC_WEIGHTS["momentum"]),
        "technical_health": _factor(_technical_health(cluster), TOPIC_WEIGHTS["technical_health"]),
    }
    score = sum(f["score"] * f["weight"] for f in factors.values())
    _gate_out(factors, cluster, hard_keys=("technical_health",))
    score = round(sum(f["score"] * f["weight"] for f in factors.values()), 3)
    label = "forte" if score >= 0.7 else ("média" if score >= 0.4 else "fraca")
    return _pack(score, label, factors, {
        "distribution": dist,
        "caveat": "Topic Authority = força geral do site NO ASSUNTO; "
                  "não é rankability de uma keyword específica",
    }, as_percent)


# --------------------------------------------------------------------------
# R1 — Query Rankability
# --------------------------------------------------------------------------

def semantic_fit(signals: dict[str, Any]) -> tuple[float, str]:
    """R4 — fit semântico da query na página/cluster.

    Componentes (0..1): entity, title, h1, heading, body, question, related.
    """
    parts = {
        "entity": _sat(signals.get("entity_fit")),
        "title": _sat(signals.get("title_fit")),
        "h1": _sat(signals.get("h1_fit")),
        "heading": _sat(signals.get("heading_fit")),
        "body": _sat(signals.get("body_fit")),
        "question": _sat(signals.get("question_fit")),
        "related": _sat(signals.get("related_entity_fit")),
    }
    weights = {"entity": 0.25, "title": 0.15, "h1": 0.15, "heading": 0.15,
               "body": 0.15, "question": 0.05, "related": 0.10}
    score = sum((parts[k] or 0.0) * weights[k] for k in weights)
    why = " · ".join(f"{k}={v:.0%}" for k, v in parts.items() if v is not None)
    return round(score, 3), why or "sem sinais semânticos"


def query_traction(query_signals: dict[str, Any]) -> tuple[float, str]:
    """R1 — tração observada da query (impressões, cliques, CTR, posição)."""
    impressions = float(query_signals.get("impressions", 0) or 0)
    clicks = float(query_signals.get("clicks", 0) or 0)
    position = query_signals.get("position")
    if impressions <= 0:
        return 0.0, "sem impressões para esta query"
    trac = min(impressions / 20_000, 1.0)  # satura em 20k
    note = f"{impressions:.0f} impressões, {clicks:.0f} cliques, pos {position}"
    return round(trac, 3), note


def related_authority(cluster: dict[str, Any], dist: dict[str, Any]) -> tuple[float, str]:
    """R1 — autoridade histórica em queries SEMELHANTES (não só a exata)."""
    top10_share = dist.get("shares", {}).get("top10", 0.0)
    related = int(cluster.get("related_top10_queries", 0) or 0)
    total = int(cluster.get("related_queries", 0) or 0)
    # combina share Top10 do cluster com o volume absoluto de queries semelhantes
    score = min(top10_share * 0.6 + min(related / 40, 1.0) * 0.4, 1.0)
    why = (f"{related}/{total} queries semelhantes no Top10 · "
           f"share Top10 {top10_share:.0%}")
    return round(score, 3), why


def observed_difficulty(query_signals: dict[str, Any]) -> tuple[float, str]:
    """R1 — dificuldade observada PARA O NOSSO SITE (não KD de mercado)."""
    # quanto mais sinais de autoridade/tração, MENOR a dificuldade relativa.
    score = 1.0 - min(
        (float(query_signals.get("topic_authority", 0) or 0)) * 0.6
        + (float(query_signals.get("related_top10_share", 0) or 0)) * 0.4,
        1.0,
    )
    return round(score, 3), "dificuldade relativa ao nosso histórico (0 = fácil p/ nós)"


def query_rankability(query: dict[str, Any], cluster: dict[str, Any],
                      dist: dict[str, Any], /, *, as_percent: bool = False) -> dict[str, Any]:
    """R1 — Query Rankability (a página compete por ESTA intenção?)."""
    semantic = query.get("semantic", {})
    factors: dict[str, dict[str, Any]] = {
        "semantic_fit": _factor(semantic_fit(semantic), QUERY_WEIGHTS["semantic_fit"]),
        "query_traction": _factor(query_traction(query), QUERY_WEIGHTS["query_traction"]),
        "related_authority": _factor(
            related_authority(cluster, dist), QUERY_WEIGHTS["related_authority"]),
        "observed_difficulty": _factor(
            observed_difficulty(query), QUERY_WEIGHTS["observed_difficulty"]),
    }
    score = round(sum(f["score"] * f["weight"] for f in factors.values()), 3)
    # gate: sem fit semântico relevante -> rankability zerada
    if factors["semantic_fit"]["score"] < 0.2:
        score = 0.0
    label = "competitiva" if score >= 0.7 else ("media" if score >= 0.4 else "baixa")
    return _pack(score, label, factors, {
        "query": query.get("keyword", ""),
        "caveat": "Query Rankability é específica da intenção; Topic Authority é do assunto",
    }, as_percent)


# --------------------------------------------------------------------------
# R1 — Headroom + Confidence V2
# --------------------------------------------------------------------------

def headroom(position: float | None, ctr: float | None,
             expected_ctr: float | None) -> tuple[float, str]:
    """R1 — Headroom: ainda há chance de cliques? (posição × CTR vs esperado).

    Aliado a position 1 e CTR alto → headroom baixo (pouco a ganhar).
    Aliado a position ~12 e CTR baixo → headroom alto (muito a ganhar).
    """
    if position is None:
        return 0.0, "sem posição para medir headroom"
    # posição 1 = 0, posição 20+ = 1 (mais longe do topo = mais headroom)
    pos_gap = max(0.0, min((position - 1) / 19.0, 1.0))
    # CTR abaixo do esperado = cabe melhorar (headroom); acima = pouco a ganhar
    ctr_gap = 1.0 if (ctr is None or expected_ctr is None) else \
        max(0.0, min((expected_ctr - ctr) / expected_ctr, 1.0)) if expected_ctr else 0.5
    score = round(pos_gap * 0.6 + ctr_gap * 0.4, 3)
    why = (f"posição {position} · CTR {ctr if ctr is None else f'{ctr:.1%}'}"
           f" vs esperado {expected_ctr if expected_ctr is None else f'{expected_ctr:.1%}'}")
    return score, why


def confidence_v2(signals: dict[str, Any]) -> dict[str, Any]:
    """R1 — Confidence V2 (separado): amostra, janelas, fontes, estabilidade."""
    checks = {
        "gsc_sample": _sat(signals.get("gsc_sample")),
        "windows": _sat(signals.get("windows")),
        "ga4_available": _sat(signals.get("ga4_available")),
        "corpus_available": _sat(signals.get("corpus_available")),
        "semantic_evidence": _sat(signals.get("semantic_evidence")),
        "query_stability": _sat(signals.get("query_stability")),
        "technical_known": _sat(signals.get("technical_known")),
    }
    weights = {"gsc_sample": 0.22, "windows": 0.18, "ga4_available": 0.12,
               "corpus_available": 0.12, "semantic_evidence": 0.14,
               "query_stability": 0.12, "technical_known": 0.10}
    score = sum((checks[k] or 0.0) * weights[k] for k in weights)
    if score < GATES["confidence"]:
        label = "insufficient_data"
    elif score >= 0.75:
        label = "high"
    elif score >= 0.5:
        label = "medium"
    else:
        label = "low"
    return {"score": round(score, 3), "label": label, "checks": checks}


# --------------------------------------------------------------------------
# R5 — Opportunity Engine V2 (score ponderado + gates)
# --------------------------------------------------------------------------

def opportunity_engine(signals: dict[str, Any], /, *, as_percent: bool = False) -> dict[str, Any]:
    """R5 — OpportunityScore ponderado + GATES + Confidence separado.

    Substitui a multiplicação (que deixava um fator 0.2 destruir o resultado).
    Gates: problemas graves zeram; confidence baixa vira insufficient_data.
    """
    gates = {}
    if not signals.get("relevant", True):
        gates["relevant"] = False
    if not signals.get("indexable", True):
        gates["indexable"] = False
    blocked = [k for k, v in gates.items() if v is False]
    if blocked:
        return _pack(0.0, "blocked", {}, {"gates": blocked,
                                          "reason": "bloqueio duro: " + ", ".join(blocked)}, as_percent)

    factors: dict[str, dict[str, Any]] = {
        "rankability": _factor((_v(signals.get("query_rankability")), "rankability da intenção"),
                               OPPORTUNITY_WEIGHTS["rankability"]),
        "demand": _factor((_v(signals.get("demand")), "demanda da intenção"),
                          OPPORTUNITY_WEIGHTS["demand"]),
        "headroom": _factor((_v(signals.get("headroom")), "headroom de cliques"),
                            OPPORTUNITY_WEIGHTS["headroom"]),
        "momentum": _factor((_v(signals.get("momentum")), "momento da demanda"),
                            OPPORTUNITY_WEIGHTS["momentum"]),
        "strategic_fit": _factor((_v(signals.get("strategic_fit")), "ajuste estratégico"),
                                 OPPORTUNITY_WEIGHTS["strategic_fit"]),
    }
    score = round(sum(f["score"] * f["weight"] for f in factors.values()), 3)
    conf = confidence_v2(signals.get("confidence", {}) or {})
    if conf["label"] == "insufficient_data":
        score = score * 0.5  # atenua (não zera) quando dados são insuficientes
    label = "forte" if score >= 0.7 else ("média" if score >= 0.4 else "fraca")
    return _pack(score, label, factors, {
        "confidence": conf,
        "gates": {"passed": not blocked},
        "formula": "+".join(f"{k}={OPPORTUNITY_WEIGHTS[k]:.0%}" for k in OPPORTUNITY_WEIGHTS),
    }, as_percent)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _v(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return min(max(float(value), 0.0), 1.0)
    except (TypeError, ValueError):
        return 0.0


def _sat(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return min(max(float(value), 0.0), 1.0)
    except (TypeError, ValueError):
        return None


def _factor(pair: tuple[float, str], weight: float) -> dict[str, Any]:
    score, why = pair
    return {"score": round(float(score), 3), "weight": weight, "explanation": why}


def _internal_authority(cluster: dict[str, Any]) -> tuple[float, str]:
    """R1/R3 — autoridade interna do cluster (PageRank local, 0..1)."""
    edges = cluster.get("internal_page_edges")
    urls = cluster.get("urls")
    if edges and urls:
        per_url, aggregate = internal_page_authority(urls, edges)
        return (round(aggregate, 3),
                f"autoridade interna do cluster {aggregate:.2f} ({len(urls)} páginas)")
    internal = float(cluster.get("internal_authority", 0) or 0)
    s = min(internal / 0.8, 1.0)  # fallback: agregado já normalizado
    return round(s, 3), f"autoridade interna do cluster {internal:.2f}"


def internal_page_authority(urls: list[str], edges: list[tuple[str, str]],
                            *, damping: float = 0.85, iters: int = 12) -> tuple[dict[str, float], float]:
    """R3 — PageRank interno sobre o link graph local (zero API externa).

    ``edges``: pares (src, tgt) de URLs do site. Retorna (por-URL normalizado
    0..1, agregado do cluster = média dos nós do cluster).
    """
    urls = list(dict.fromkeys(urls or []))
    if not urls or not edges:
        return ({u: 0.0 for u in urls}, 0.0)
    n = len(urls)
    # grau de saída por nó
    out_deg: dict[str, int] = {}
    for src, _tgt in edges:
        out_deg[src] = out_deg.get(src, 0) + 1
    # PR inicial uniforme
    pr = {u: 1.0 / n for u in urls}
    for _ in range(iters):
        new = {u: (1 - damping) / n for u in urls}
        dangling = sum(v for u, v in pr.items() if out_deg.get(u, 0) == 0)
        dangling_share = dangling * damping / n if n else 0.0
        for src, tgt in edges:
            if src in pr and tgt in pr and out_deg.get(src, 0) > 0:
                new[tgt] += damping * pr[src] / out_deg[src]
        for u in urls:
            new[u] += dangling_share
        pr = new
    mx = max(pr.values()) or 1.0
    per_url = {u: round(pr[u] / mx, 4) for u in urls}
    aggregate = round(sum(pr[u] for u in urls) / n, 4) if n else 0.0
    return per_url, aggregate


def _momentum(cluster: dict[str, Any]) -> tuple[float, str]:
    delta = cluster.get("momentum_delta_pct")
    if delta is None:
        return 0.5, "momento não mensurável (uma janela)"
    if delta >= 0:
        return round(min(delta / 50, 1.0), 3), f"crescimento de +{delta:.0f}% entre janelas"
    return round(max(0.0, 1.0 + delta / 100), 3), f"declínio de {delta:.0f}% entre janelas"


def _gate_out(factors: dict[str, dict[str, Any]], signals: dict[str, Any],
              *, hard_keys: Iterable[str]) -> None:
    """Zera TODO o score quando há falha dura (ex.: não-indexável → rankability 0)."""
    reasons = {k: factors[k]["explanation"] for k in hard_keys
               if factors.get(k, {}).get("score", 1.0) == 0.0}
    if reasons:
        for f in factors.values():
            f["score"] = 0.0
        factors["_blocked"] = {
            "score": 0.0, "weight": 0.0,
            "explanation": "bloqueio técnico: " + ", ".join(reasons),
        }


def _pack(score: float, label: str, factors: dict[str, Any], extra: dict[str, Any],
          as_percent: bool) -> dict[str, Any]:
    result = {
        "score": round(score * 100, 1) if as_percent else round(score, 3),
        "label": label,
        "factors": factors,
        "explanations": {k: v.get("explanation", "") for k, v in factors.items()
                         if isinstance(v, dict) and "explanation" in v},
        **extra,
    }
    return result
