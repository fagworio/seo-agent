"""R8 — Content Gap Engine (determinístico, sem copiar conteúdo).

Compara o NOSSO topic graph (corpus/GSC) com a cobertura dos concorrentes
(R7) e gera gaps tipados com score/confiança/recomendação:

  missing_topic | missing_subtopic | weak_coverage | outdated_coverage |
  competitor_dominance | cluster_gap | hub_gap | question_gap

`gap_score` ∈ [0,1] (ou 0..100 com ``as_percent``). Nunca probabilidade.
"""
from __future__ import annotations

import datetime
from typing import Any

from ..report.topics import canonical_entity, normalize_entity

HUB_TITLE_WORDS = ("guia", "melhores", "tudo sobre", "top", "lista", "melhor")
QUESTION_WORDS = ("como", "qual", "quais", "quando", "onde", "quanto", "quem",
                  "o que", "por que", "porque", "é", "são", "vale a pena")

# limiares default (calibráveis)
_OUR_MIN = 2            # mínimo de docs nossos p/ considerar "cobertura"
_COMP_MIN = 3           # mínimo de docs do concorrente p/ considerar "cobre"
_STALE_DAYS = 90        # frescor: acima disso em dias = desatualizado
_DOM_RATIO = 3          # dominância: comp >= our * ratio


def _days_since(iso: str) -> int | None:
    if not iso:
        return None
    try:
        dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return (datetime.datetime.now(datetime.timezone.utc) - dt).days


def _comp_in_doc(domain_articles: dict[str, int]) -> dict[str, Any]:
    domains = list(domain_articles)
    return {"competitors_covering": len(domains),
            "competitor_articles": sum(domain_articles.values()),
            "competitor_domains": domains}


def build_gaps(our_meta: dict[str, dict[str, Any]],
               competitor_coverage: dict[str, dict[str, int]],
               *, as_percent: bool = False) -> list[dict[str, Any]]:
    """Gera gaps a partir da cobertura nossa vs concorrentes."""
    gaps: list[dict[str, Any]] = []
    our_keys = set(our_meta)

    for topic in sorted(set(competitor_coverage) | our_keys):
        comp = _comp_in_doc(competitor_coverage.get(topic, {}))
        ours = our_meta.get(topic, {"n": 0, "freshness_days": None, "questions": 0})
        our_n = int(ours.get("n", 0))
        comp_n = comp["competitor_articles"]
        comp_domains = comp["competitors_covering"]
        fresh = ours.get("freshness_days")

        if topic not in our_keys:
            # concorrente cobre algo que NÃO cobrimos
            if comp_n >= _COMP_MIN:
                gaps.append(_gap("missing_topic", topic, comp, ours, "missing_topic",
                                 0.9, "concorrente cobre e nós não temos o tópico", as_percent))
            elif comp_n >= 1:
                gaps.append(_gap("missing_subtopic", topic, comp, ours, "missing_subtopic",
                                 0.6, "concorrente cobre um sub-tópico que não temos", as_percent))
            continue

        # temos o tópico: avaliar fraqueza/dominância/frescor/hub/pergunta
        if our_n < _OUR_MIN and comp_n >= _COMP_MIN:
            gaps.append(_gap("weak_coverage", topic, comp, ours, "weak_coverage",
                             0.6, "cobertura fraca vs concorrentes", as_percent))
        if comp_n >= _OUR_MIN and comp_domains >= 1 and our_n < comp_n / _DOM_RATIO:
            gaps.append(_gap("competitor_dominance", topic, comp, ours,
                             "competitor_dominance", 0.7,
                             "concorrentes dominam o tópico (mais volume)", as_percent))
        if fresh is not None and fresh > _STALE_DAYS:
            gaps.append(_gap("outdated_coverage", topic, comp, ours, "outdated_coverage",
                             0.5, f"nosso conteúdo está desatualizado ({fresh}d)", as_percent))
        if comp_n >= _COMP_MIN and our_n >= 1 and _hub_gap(topic):
            gaps.append(_gap("hub_gap", topic, comp, ours, "hub_gap", 0.55,
                             "concorrente tem página-guia/hub; nós não", as_percent))
        if comp_n >= _COMP_MIN and _question_gap(topic):
            gaps.append(_gap("question_gap", topic, comp, ours, "question_gap", 0.5,
                             "concorrente cobre perguntas que não cobrimos", as_percent))
        # cluster: conjunto de tópicos do mesmo domínio com cobertura fraca
        if comp_n >= _COMP_MIN and our_n < _OUR_MIN:
            gaps.append(_gap("cluster_gap", topic, comp, ours, "cluster_gap", 0.45,
                             "grupo de tópicos relacionados com cobertura baixa", as_percent))
    # dedupe por (type, topic), mantendo o de maior score
    return _dedupe(gaps)


def _hub_gap(topic: str) -> bool:
    any_word = any(w in normalize_entity(topic) for w in HUB_TITLE_WORDS)
    return any_word  # sinal simples: o próprio tópico/URL sugere hub ausente


def _question_gap(topic: str) -> bool:
    norm = normalize_entity(topic)
    return any(q in norm for q in QUESTION_WORDS) or "?" in topic


def _gap(gap_type: str, topic: str, comp: dict[str, Any], ours: dict[str, Any],
         label: str, score: float, recommendation: str, as_percent: bool) -> dict[str, Any]:
    return {
        "type": gap_type,
        "topic": topic,
        **comp,
        "our_coverage": int(ours.get("n", 0)),
        "our_freshness_days": ours.get("freshness_days"),
        "gap_score": round(score * 100, 1) if as_percent else round(score, 3),
        "confidence": _confidence(comp, ours),
        "recommendation": recommendation,
        "label": label,
    }


def _confidence(comp: dict[str, Any], ours: dict[str, Any]) -> str:
    total = comp["competitor_articles"] + int(ours.get("n", 0))
    if total >= 20:
        return "high"
    if total >= 6:
        return "medium"
    return "low"


def _dedupe(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for g in gaps:
        key = (g["type"], g["topic"])
        prev = best.get(key)
        if prev is None or g["gap_score"] > prev["gap_score"]:
            best[key] = g
    return sorted(best.values(), key=lambda g: g["gap_score"], reverse=True)


def content_gaps(storage: Any, *, as_percent: bool = False) -> dict[str, Any]:
    """Orquestra R8: monta our_meta (nosso topic graph + frescor) e cruza com a
    cobertura dos concorrentes (R7)."""
    from ..report.topics import build_topic_graph
    our_graph = build_topic_graph(storage, min_urls=1)
    our_meta: dict[str, dict[str, Any]] = {}
    for cluster in our_graph:
        entity = cluster["entity"]
        urls = cluster.get("urls", [])
        freshest = ""
        for u in urls:
            row = storage.conn.execute(
                "SELECT built_at FROM corpus_documents WHERE url = ?", (u,)).fetchone()
            if row and row[0] and row[0] > freshest:
                freshest = row[0]
        our_meta[entity] = {"n": len(urls),
                            "freshness_days": _days_since(freshest),
                            "questions": 0}
    comp_coverage = storage.competitor_topic_coverage()
    gaps = build_gaps(our_meta, comp_coverage, as_percent=as_percent)
    by_type: dict[str, int] = {}
    for g in gaps:
        by_type[g["type"]] = by_type.get(g["type"], 0) + 1
    return {
        "gaps": gaps,
        "by_type": by_type,
        "total": len(gaps),
        "competitor_topics": len(comp_coverage),
        "our_topics": len(our_meta),
    }
