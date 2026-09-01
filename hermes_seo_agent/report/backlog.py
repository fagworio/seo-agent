"""Editorial E3 — evidence-backed, non-duplicative backlog generation."""

from __future__ import annotations

import re
from typing import Any

_HUB_TITLE_WORDS = ("melhores", "guia", "tudo sobre", "lista", "melhor", "top")
_STOP = {"o", "a", "os", "as", "de", "da", "do", "das", "dos", "e", "em", "no", "na", "para", "com", "um", "uma", "que", "por", "sobre", "como", "qual", "quais", "quanto", "quando", "onde", "quem", "tem", "anos"}


def _terms(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-zà-ú]{3,}", (text or "").lower()) if word not in _STOP}


def _working_title(query: str) -> str:
    words = re.findall(r"[a-zà-ú]{3,}", (query or "").lower())
    return " ".join(word for word in words if word not in _STOP)[:80].capitalize() or query


def _coverage(query: str, page: dict[str, Any]) -> float:
    """Conservative lexical coverage of an intent by an existing page."""
    query_terms = _terms(query)
    if not query_terms:
        return 0.0
    headings = " ".join([page.get("title", ""), page.get("h1", ""), *page.get("h2s", [])])
    heading_terms = _terms(headings)
    body_terms = _terms(page.get("body_text", ""))
    return (len(query_terms & heading_terms) * 2 + len(query_terms & body_terms)) / (len(query_terms) * 3)


def _covered_pages(query: str, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches = [(round(_coverage(query, page), 2), page) for page in pages]
    return [{"url": page.get("url", ""), "coverage": score} for score, page in matches if score >= 0.55]


def generate_pautas(*, cannibalization: list[dict[str, Any]], briefs: list[dict[str, Any]],
                    top_demand: list[dict[str, Any]], category_urls: dict[str, list[str]],
                    category_titles: dict[str, list[str]], existing_pages: list[dict[str, Any]] | None = None,
                    demand_trends: dict[str, str] | None = None,
                    max_per_type: int = 10) -> list[dict[str, Any]]:
    """Generate only ideas whose intent is not already adequately covered.

    demand_trends: query -> 'growing'|'stable'|'declining'. Declining demand
    never becomes a new post (it suggests review, not new content).
    """
    pages = existing_pages or []
    demand_trends = demand_trends or {}
    pautas: list[dict[str, Any]] = []
    for cand in cannibalization[:max_per_type]:
        pautas.append({"pauta_type": "cannibalization_review", "title": f"Revisar canibalização: '{cand['query']}'", "intent": "revisão", "evidence": f"query compartilhada por {cand['urls']} URLs ({cand['total_impressions']} impressões)", "related_urls": [], "scope": "decidir URL primária, diferenciar ângulos ou consolidar", "duplication_risk": "alto (URLs concorrem pela mesma demanda)", "score": round(min(cand["total_impressions"], 5000) / 5000 * 5, 2)})
    for brief in briefs[:max_per_type]:
        gap_names = {gap["gap"] for gap in brief["gaps"]}
        pautas.append({"pauta_type": "expand_existing", "title": f"Expandir: {brief['title'][:50]}", "intent": brief["intent"], "evidence": f"lacunas: {', '.join(sorted(gap_names))}", "related_urls": [brief["url"]], "scope": brief["action"], "duplication_risk": "baixo (URL já é a candidata para a intenção)", "score": brief["priority"]})
    for item in top_demand[:max_per_type]:
        if item.get("intent") not in {"question", "informational"} or float(item.get("impressions", 0)) < 200:
            continue
        if demand_trends.get(item["query"]) == "declining":
            continue  # demanda em queda sugere revisão, não conteúdo novo
        if _covered_pages(item["query"], pages):
            continue
        related = [page.get("url", "") for page in pages if _coverage(item["query"], page) >= 0.25][:3]
        pautas.append({"pauta_type": "supporting_post", "title": f"Post de apoio: {_working_title(item['query'])}", "intent": item.get("intent", ""), "evidence": f"'{item['query']}' com {item['impressions']:.0f} impressões (pos {item['position']}); nenhuma URL teve cobertura suficiente", "related_urls": related, "scope": "cobrir o ângulo específico da query com resposta direta e seções próprias; diferenciar-se das URLs comparadas", "duplication_risk": "baixo após comparação com o inventário editorial", "score": round(min(float(item.get("impressions", 0)), 5000) / 5000 * 4, 2)})
    for category, urls in category_urls.items():
        if len(urls) < 5:
            continue
        titles = category_titles.get(category, [])
        if any(any(word in (title or "").lower() for word in _HUB_TITLE_WORDS) for title in titles):
            continue
        pautas.append({"pauta_type": "hub_page", "title": f"Hub: guia de {category}", "intent": "navegação/cluster", "evidence": f"{len(urls)} posts na categoria '{category}' sem página-guia", "related_urls": urls[:8], "scope": "página-guia conectando os posts da categoria", "duplication_risk": "baixo (não há hub detectado)", "score": 3.0})
    pautas.sort(key=lambda pauta: pauta["score"], reverse=True)
    return pautas
