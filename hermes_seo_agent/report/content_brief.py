"""Evidence-backed, read-only content improvement briefs.

This module intentionally makes recommendations only.  It never writes to
WordPress and it does not prescribe keyword stuffing: each suggestion is tied
to a rendered-page signal or to a query that already produced impressions.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from ..connectors.static_site import PageSnapshot


def _normal(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").lower()).strip()


def _words(value: str) -> int:
    return len(re.findall(r"\b[\wÀ-ÿ'-]+\b", value or ""))


def _question(query: str) -> bool:
    return bool(re.match(r"^(como|qual|quais|quando|onde|por que|porque|quem|quanto|quantos|o que)\b", _normal(query)))


def _internal_links(page: PageSnapshot) -> list[str]:
    host = urlparse(page.url).netloc
    links: list[str] = []
    for href in page.links:
        resolved = urljoin(page.url, href)
        parsed = urlparse(resolved)
        if parsed.netloc == host and parsed.path and not parsed.fragment:
            links.append(resolved)
    return links


def build_content_brief(page: PageSnapshot, queries: list[dict[str, Any]]) -> dict[str, Any]:
    """Return signals and editorial recommendations for one published page."""
    body = _normal(page.body_text)
    title = _normal(page.title)
    h1 = _normal(" ".join(page.h1))
    headings = [_normal(h) for h in page.h2s if h.strip()]
    query_rows = [
        {
            "query": (row.get("keys") or [""])[0],
            "impressions": float(row.get("impressions", 0)),
            "clicks": float(row.get("clicks", 0)),
            "position": float(row.get("position", 0)),
        }
        for row in queries if (row.get("keys") or [""])[0]
    ]
    query_rows.sort(key=lambda q: (-q["impressions"], q["position"]))
    suggestions: list[dict[str, Any]] = []

    for query in query_rows[:5]:
        phrase = _normal(query["query"])
        if len(phrase) < 3:
            continue
        in_title = phrase in title or phrase in h1
        in_body = phrase in body
        query_evidence = {
            "supporting_query": query["query"],
            "query_impressions": query["impressions"],
            "query_position": query["position"],
        }
        if not in_title:
            suggestions.append({
                "item": "query_title_alignment",
                "priority": "high",
                "evidence": f"query '{query['query']}' teve {query['impressions']:.0f} impressões, mas não aparece no title/H1",
                "action": "Avaliar incluir a intenção da query no título ou H1, preservando clareza e diferenciação editorial.",
                **query_evidence,
            })
        elif not in_body:
            suggestions.append({
                "item": "query_content_coverage",
                "priority": "medium",
                "evidence": f"query '{query['query']}' aparece no snippet, mas não no texto principal renderizado",
                "action": "Adicionar uma resposta objetiva ou seção que cubra a intenção da query, se ela for pertinente ao escopo da página.",
                **query_evidence,
            })
        if _question(query["query"]) and not any(phrase in heading for heading in headings):
            suggestions.append({
                "item": "question_gap",
                "priority": "medium",
                "evidence": f"query em formato de pergunta: '{query['query']}' ({query['impressions']:.0f} impressões)",
                "action": "Considerar um subtítulo com resposta direta à pergunta; usar FAQ apenas se a pergunta for realmente respondida na página.",
                **query_evidence,
            })

    words = _words(page.body_text)
    if words < 250:
        suggestions.append({
            "item": "content_depth",
            "priority": "medium",
            "evidence": f"texto principal com {words} palavras após excluir navegação e rodapé",
            "action": "Revisar se a página entrega contexto, resposta principal, exemplos e fontes suficientes para a intenção que recebe impressões.",
        })
    if len(headings) < 2 and words >= 300:
        suggestions.append({
            "item": "content_structure",
            "priority": "low",
            "evidence": f"{words} palavras distribuídas em apenas {len(headings)} subtítulo(s) H2",
            "action": "Organizar o texto em seções descritivas para tornar a resposta escaneável; não criar headings apenas para inserir keywords.",
        })
    internal = _internal_links(page)
    if not internal and words >= 150:
        suggestions.append({
            "item": "internal_linking",
            "priority": "low",
            "evidence": "nenhum link interno foi encontrado no HTML renderizado da página",
            "action": "Adicionar links contextuais para conteúdos relacionados que aprofundem ou complementem a resposta.",
        })

    # Deduplicate repeated evidence caused by near-identical GSC query variants.
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for suggestion in suggestions:
        key = (suggestion["item"], suggestion["evidence"])
        if key not in seen:
            unique.append(_enrich(suggestion))
            seen.add(key)
    return {
        "signals": {
            "main_word_count": words,
            "h2_count": len(headings),
            "internal_link_count": len(internal),
            "queries_considered": query_rows[:5],
        },
        "suggestions": unique,
    }


_SECTION_BY_ITEM = {
    "query_title_alignment": "revisar title/H1 (primeiros 60 caracteres)",
    "query_content_coverage": "seção dedicada que responda à query no corpo",
    "question_gap": "seção 'Resposta: <pergunta>' logo após a introdução",
    "content_depth": "expandir o corpo com contexto, exemplos e fontes",
    "content_structure": "organizar em subtítulos H2 descritivos e escaneáveis",
    "internal_linking": "adicionar links contextuais para conteúdos relacionados",
}
_ACCEPT_BY_ITEM = {
    "query_title_alignment": "title/H1 ≤60 chars contendo a intenção da query",
    "query_content_coverage": "o texto renderizado responde à query objetivamente",
    "question_gap": "a pergunta é respondida na própria seção (≤150 palavras)",
    "content_depth": "corpo ≥ 300 palavras com contexto, exemplos e fontes",
    "content_structure": "≥ 2 subtítulos descritivos, sem headings só de keyword",
    "internal_linking": "≥ 1 link interno contextual para página relacionada",
}


def _enrich(suggestion: dict[str, Any]) -> dict[str, Any]:
    """Add actionable fields: where, and how to accept the work."""
    item = suggestion["item"]
    suggestion["suggested_section"] = _SECTION_BY_ITEM.get(item, "rever a página")
    suggestion["acceptance_criteria"] = _ACCEPT_BY_ITEM.get(
        item, "revisar a alteração manualmente antes de marcar como feita"
    )
    return suggestion


def cannibalization_suggestions(briefs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Flag shared high-value queries among the analysed URLs.

    This is a triage signal, not a claim that cannibalisation exists: Google may
    correctly rank multiple pages for a broad query.  The recommendation asks
    for differentiation or consolidation review, never an automatic redirect.
    """
    owners: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for brief in briefs:
        url = brief.get("url", "")
        for query in brief.get("content_brief", {}).get("signals", {}).get("queries_considered", []):
            term = _normal(query.get("query", ""))
            if term and query.get("impressions", 0) >= 10:
                owners.setdefault(term, []).append((url, query))

    by_url: dict[str, list[dict[str, Any]]] = {}
    for term, matches in owners.items():
        urls = sorted({url for url, _ in matches})
        if len(urls) < 2:
            continue
        evidence = f"query '{term}' gera impressões para {len(urls)} URLs analisadas"
        for url, _query in matches:
            by_url.setdefault(url, []).append({
                "item": "possible_cannibalization",
                "priority": "medium",
                "evidence": evidence,
                "action": "Comparar intenção, escopo e conteúdo das URLs; diferenciar a proposta de cada uma ou planejar consolidação com revisão humana.",
                "related_urls": [other for other in urls if other != url],
            })
    return by_url
