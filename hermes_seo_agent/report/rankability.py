"""M5 — Perfil de rankability e autoridade temática por cluster.

Estimativa CALIBRÁVEL (não "probabilidade de rankear") de quão forte o site
está para competir em um tema. Cada fator é explicável (positivo/negativo):

  * cobertura do acervo (posts no cluster);
  * visibilidade GSC (impressões/cliques);
  * frequência de Top 3 / Top 10;
  * posição mediana;
  * crescimento (duas janelas);
  * interlinks (interno e recebido no cluster);
  * frescor (crawl/build recente);
  * engajamento orgânico GA4;
  * dificuldade/SERP externa (opcional, quando o provedor M4 existir).

rankability_score ∈ [0, 1], composto por fatores com pesos default e
explicação por fator — sem IA, sem "probabilidade".
"""

from __future__ import annotations

from typing import Any

# Pesos default (calibráveis): soma = 1.0
WEIGHTS = {
    "coverage": 0.20,
    "visibility": 0.20,
    "top_frequency": 0.15,
    "median_position": 0.10,
    "growth": 0.10,
    "interlinks": 0.10,
    "freshness": 0.05,
    "engagement": 0.10,
}

# limites para saturação de cada fator (determinísticos)
_CAPS = {
    "coverage": 10,            # 10+ posts no cluster = 1.0
    "visibility": 10_000,      # impressões
    "top_frequency": 0.5,      # fração de queries Top 10
    "median_position": 10,     # posição mediana (pior = menor score)
    "growth": 0.5,             # +50% entre janelas = 1.0
    "interlinks": 20,          # links dentro do cluster
    "freshness": 90,           # dias desde a última atualização (menos = melhor)
    "engagement": 0.5,         # taxa de engajamento GA4
}


def _coverage_score(posts: int) -> tuple[float, str]:
    if posts <= 0:
        return 0.0, "sem posts no cluster (cobertura nula)"
    s = min(posts / _CAPS["coverage"], 1.0)
    return round(s, 2), f"{posts} posts no cluster (satura em {_CAPS['coverage']})"


def _visibility_score(impressions: float) -> tuple[float, str]:
    if impressions <= 0:
        return 0.0, "sem impressões GSC no cluster"
    s = min(impressions / _CAPS["visibility"], 1.0)
    return round(s, 2), f"{impressions:.0f} impressões (satura em {_CAPS['visibility']})"


def _top_frequency_score(top10_queries: int, total_queries: int) -> tuple[float, str]:
    if total_queries <= 0:
        return 0.0, "sem queries GSC para medir Top 10"
    frac = top10_queries / total_queries
    s = min(frac / _CAPS["top_frequency"], 1.0)
    return round(s, 2), f"{top10_queries}/{total_queries} queries no Top 10"


def _median_position_score(positions: list[float]) -> tuple[float, str]:
    if not positions:
        return 0.0, "sem posições para calcular mediana"
    import statistics
    med = statistics.median(positions)
    # posição 1 = 1.0; posição 10+ = 0.0 (linear entre 1 e cap)
    s = max(0.0, 1.0 - (med - 1) / (_CAPS["median_position"] - 1))
    return round(s, 2), f"posição mediana {med:.1f} (1.0 = rank 1)"


def _growth_score(delta_pct: float | None) -> tuple[float, str]:
    if delta_pct is None:
        return 0.0, "crescimento não mensurável (uma janela apenas)"
    if delta_pct >= 0:
        s = min(delta_pct / (_CAPS["growth"] * 100), 1.0)
        return round(s, 2), f"crescimento de +{delta_pct:.0f}% entre janelas"
    return 0.0, f"declínio de {delta_pct:.0f}% entre janelas (fator zero)"


def _interlinks_score(links: int) -> tuple[float, str]:
    s = min(links / _CAPS["interlinks"], 1.0)
    return round(s, 2), f"{links} links internos no cluster (satura em {_CAPS['interlinks']})"


def _freshness_score(days_since: int | None) -> tuple[float, str]:
    if days_since is None:
        return 0.0, "frescor não mensurável"
    s = max(0.0, 1.0 - days_since / _CAPS["freshness"])
    return round(s, 2), f"última atualização há {days_since}d"


def _engagement_score(rate: float | None, status: str) -> tuple[float, str]:
    if rate is None or status != "available":
        return 0.0, "sem engajamento GA4 disponível"
    s = min(rate / _CAPS["engagement"], 1.0)
    return round(s, 2), f"taxa de engajamento GA4 {rate:.0%}"


def rankability_profile(cluster: dict[str, Any], *, growth_delta_pct: float | None = None,
                        external_difficulty: float | None = None) -> dict[str, Any]:
    """Calcula o perfil de rankability de um cluster (dict do M3)."""
    positions = cluster.get("positions", [])
    total_queries = cluster.get("total_queries", 0)
    days_since = cluster.get("days_since_update")
    rate = cluster.get("ga4_engagement_rate")
    ga4_status = cluster.get("ga4_status", "missing")

    factors: dict[str, Any] = {}
    explanations: dict[str, str] = {}
    for name, func in (
        ("coverage", lambda: _coverage_score(cluster.get("posts", 0))),
        ("visibility", lambda: _visibility_score(cluster.get("impressions", 0))),
        ("top_frequency", lambda: _top_frequency_score(
            cluster.get("top10_queries", 0), total_queries)),
        ("median_position", lambda: _median_position_score(positions)),
        ("growth", lambda: _growth_score(growth_delta_pct)),
        ("interlinks", lambda: _interlinks_score(cluster.get("internal_links", 0))),
        ("freshness", lambda: _freshness_score(days_since)),
        ("engagement", lambda: _engagement_score(rate, ga4_status)),
    ):
        score, why = func()
        factors[name] = {"score": score, "weight": WEIGHTS[name],
                         "explanation": why}
        explanations[name] = why

    # dificuldade externa (M4, opcional): penaliza o score se o mercado é difícil
    external_note = ""
    external_penalty = 0.0
    if external_difficulty is not None:
        external_penalty = min(max(external_difficulty, 0.0), 1.0) * 0.10
        factors["external_difficulty"] = {
            "score": round(1 - external_penalty, 2), "weight": 0.0,
            "explanation": (f"dificuldade externa {external_difficulty:.0%} "
                            f"(penaliza {external_penalty:.0%} do total)"),
        }
        external_note = factors["external_difficulty"]["explanation"]

    total = sum(f["score"] * f["weight"] for f in factors.values() if f["weight"])
    total = max(total - external_penalty, 0.0)
    score = round(min(total, 1.0), 3)

    # rótulo qualitativo — NUNCA "probabilidade de rankear"
    label = "forte" if score >= 0.7 else ("média" if score >= 0.4 else "fraca")
    return {
        "rankability_score": score,
        "label": f"autoridade {label} no tópico (score calibrável, não probabilidade)",
        "factors": factors,
        "explanations": explanations,
        "external_difficulty": external_difficulty,
        "external_note": external_note,
        "caveat": "score calibrável por resultados medidos (M8); não é probabilidade de rankear",
    }
