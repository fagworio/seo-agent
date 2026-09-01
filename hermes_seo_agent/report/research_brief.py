"""M7 — Brief de pesquisa semântico, com revisão humana.

Para uma oportunidade aprovada (saída do M6), recupera:
  * melhores seções internas relacionadas (corpus M2);
  * queries GSC;
  * entidades e cluster (M3);
  * sinais GA4;
  * evidência externa/SERP (M4, se autorizada).

Produz um brief estruturado: intenção, URL recomendada ou justificativa para
novo conteúdo, diferenciação obrigatória, perguntas/subtópicos, risco de
duplicação, links internos recomendados e critérios de aceite.

O LLM (se usado) faz APENAS síntese do brief, com fontes citadas e sem
autoridade para executar ações. Aqui o brief é 100% determinístico.
"""

from __future__ import annotations

from typing import Any

from .decision_engine import OPPORTUNITY_TYPES


def build_research_brief(*, keyword: str, intent: dict[str, Any],
                         decision: dict[str, Any],
                         corpus_docs: list[dict[str, Any]],
                         corpus_sections: dict[str, list[dict[str, Any]]],
                         gsc_queries: list[dict[str, Any]],
                         entities: list[dict[str, Any]],
                         cluster: dict[str, Any] | None,
                         ga4: dict[str, Any] | None,
                         external: dict[str, Any] | None = None) -> dict[str, Any]:
    """Monta o brief estruturado (determinístico) de uma oportunidade."""
    decision_name = decision.get("decision", "expand_existing")
    opportunity_type = decision.get("opportunity_type",
                                    _default_type(decision_name))
    if opportunity_type not in OPPORTUNITY_TYPES:
        opportunity_type = "expand_existing"

    # URL recomendada: se há conteúdo interno, é o candidato a expandir; senão,
    # justificativa para novo conteúdo (sem criar URL automaticamente).
    recommended_url = ""
    if corpus_docs:
        recommended_url = corpus_docs[0].get("url", "")

    # links internos recomendados: os docs internos relacionados
    internal_links = [
        {"url": d.get("url", ""), "title": d.get("title", ""),
         "context": "candidato a interligar/expandir"}
        for d in corpus_docs[:5]
    ]

    subtopics = _subtopics(keyword, gsc_queries, corpus_sections)

    duplication_risk = _duplication_risk(corpus_docs, keyword)

    brief = {
        "keyword": keyword,
        "intent": {
            "type": _intent_type(intent),
            "description": f"intenção: {keyword}",
            "is_question": bool(intent.get("is_question")),
        },
        "decision": decision_name,
        "opportunity_type": opportunity_type,
        "recommended_url": recommended_url,
        "new_content_justification": "" if recommended_url else (
            f"nenhum conteúdo interno cobre '{keyword}' — criar conteúdo novo "
            f"pertence ao território; URL e publicação exigem revisão humana"),
        "differentiation": _differentiation(corpus_docs, keyword),
        "subtopics_questions": subtopics,
        "duplication_risk": duplication_risk,
        "internal_links_recommended": internal_links,
        "acceptance_criteria": _acceptance(opportunity_type, keyword),
        "evidence": {
            "corpus_docs": [
                {"url": d.get("url", ""), "title": d.get("title", ""),
                 "snippet": d.get("snippet", "")} for d in corpus_docs[:5]
            ],
            "gsc_queries": gsc_queries[:10],
            "entities": entities[:10],
            "cluster": {
                "entity": (cluster or {}).get("entity", ""),
                "posts": (cluster or {}).get("posts", 0),
                "impressions": (cluster or {}).get("impressions", 0),
            } if cluster else None,
            "ga4": ga4,
            "external": external,
        },
        "human_review_required": True,
        "llm_role": "síntese opcional — apenas reformata com fontes citadas; "
                    "sem autoridade para executar",
    }
    return brief


def _default_type(decision: str) -> str:
    mapping = {
        "new_content": "new_content", "supporting_post": "supporting_post",
        "expand_existing": "expand_existing", "refresh": "refresh",
        "internal_link": "internal_link",
        "cannibalization_review": "cannibalization_review",
        "monitor": "engagement_opportunity", "weak_signal": "engagement_opportunity",
        "discard": "new_content",
    }
    return mapping.get(decision, "expand_existing")


def _intent_type(intent: dict[str, Any]) -> str:
    if intent.get("is_question"):
        return "question"
    if intent.get("comparison"):
        return "comparison"
    return "informational"


def _subtopics(keyword: str, gsc_queries: list[dict[str, Any]],
               corpus_sections: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Perguntas/subtópicos derivados das queries GSC + seções internas."""
    subtopics: list[str] = []
    seen: set[str] = set()
    for q in gsc_queries:
        query = q.get("query", "")
        if query and query not in seen:
            subtopics.append(query)
            seen.add(query)
        if len(subtopics) >= 8:
            break
    for heading in _section_headings(corpus_sections):
        if heading and heading not in seen:
            subtopics.append(f"seção interna relacionada: {heading}")
            seen.add(heading)
        if len(subtopics) >= 12:
            break
    if not subtopics:
        subtopics.append(f"definir perguntas de suporte para '{keyword}'")
    return subtopics


def _section_headings(corpus_sections: dict[str, list[dict[str, Any]]]) -> list[str]:
    headings = []
    for sections in corpus_sections.values():
        for sec in sections:
            h = (sec.get("heading") or "").strip()
            if h:
                headings.append(h)
    return headings


def _duplication_risk(corpus_docs: list[dict[str, Any]], keyword: str) -> str:
    if len(corpus_docs) >= 3:
        return (f"ALTO: {len(corpus_docs)} documentos internos mencionam '{keyword}' — "
                "diferenciar escopo explicitamente ou revisar canibalização")
    if corpus_docs:
        return (f"MÉDIO: 1-2 documentos internos mencionam '{keyword}' — cobrir "
                "ângulo/escopo distinto")
    return f"BAIXO: nenhum documento interno menciona '{keyword}'"


def _differentiation(corpus_docs: list[dict[str, Any]], keyword: str) -> str:
    if not corpus_docs:
        return "conteúdo inédito no território (sem diferenciação obrigatória)"
    titles = " | ".join((d.get("title") or "")[:50] for d in corpus_docs[:3])
    return f"diferenciar de: {titles}"


def _acceptance(opportunity_type: str, keyword: str) -> list[str]:
    common = [f"responde à intenção de '{keyword}' de forma direta e escaneável"]
    by_type = {
        "title_meta": ["title/H1 ≤ 60 chars contendo a intenção"],
        "refresh": ["conteúdo atualizado (datas/fatos) e aderente à intenção atual"],
        "expand_existing": ["expandir a URL recomendada com seção/ângulo ausente, sem duplicar"],
        "new_content": ["conteúdo novo publicado só após aprovação humana"],
        "supporting_post": ["post de apoio publicado só após aprovação humana"],
        "internal_link": ["≥ 1 link interno contextual entre os docs do cluster"],
        "cannibalization_review": ["escopo de cada URL documentado; consolidação só com revisão humana"],
        "engagement_opportunity": ["monitorar; nenhuma ação automática"],
    }
    return common + by_type.get(opportunity_type, [])
