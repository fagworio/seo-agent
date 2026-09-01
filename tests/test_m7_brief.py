"""Tests for M7 — semantic research brief (deterministic, human review)."""

from hermes_seo_agent.report.decision_engine import decide
from hermes_seo_agent.report.research_brief import build_research_brief


def _corpus_docs(url="https://x.com/op/", title="Guia de One Piece"):
    return [{"url": url, "title": title, "snippet": "[One Piece] Luffy"}]


def _sections():
    return {"https://x.com/op/": [
        {"heading": "Idade do Luffy", "heading_level": 2, "position": 0,
         "text": "Luffy tem 19 anos"},
        {"heading": "Os Chapéus de Palha", "heading_level": 2, "position": 1,
         "text": "Navegam"},
    ]}


def _gsc_queries():
    return [{"query": "one piece luffy idade", "impressions": 800, "clicks": 20},
            {"query": "quantos anos tem o luffy", "impressions": 500, "clicks": 5}]


def _decision(corpus_covers=True, is_question=True):
    intent = {"demand_score": 0.9, "relevant": True, "corpus_covers": corpus_covers,
              "coverage_sufficient": False, "competing_urls": 1, "is_question": is_question,
              "stale": False, "trend": "growing", "confidence": 0.7}
    return decide(intent)


def test_brief_expand_existing_with_all_evidence():
    brief = build_research_brief(
        keyword="one piece luffy", intent={"is_question": True},
        decision=_decision(), corpus_docs=_corpus_docs(), corpus_sections=_sections(),
        gsc_queries=_gsc_queries(), entities=[{"entity": "one piece", "entity_type": "franchise"}],
        cluster={"entity": "one piece", "posts": 3, "impressions": 1200},
        ga4={"sessions": 100, "engagement_rate": 0.5},
    )
    assert brief["opportunity_type"] == "expand_existing"
    assert brief["recommended_url"] == "https://x.com/op/"
    assert not brief["new_content_justification"]
    # subtópicos derivados de queries + seções internas
    joined = " ".join(brief["subtopics_questions"])
    assert "quantos anos tem o luffy" in joined
    assert "Idade do Luffy" in joined
    # risco de duplicação e diferenciação explicados
    assert brief["duplication_risk"].startswith("MÉDIO")
    assert "Guia de One Piece" in brief["differentiation"]
    # links internos recomendados
    assert brief["internal_links_recommended"][0]["url"] == "https://x.com/op/"
    # aceite por tipo
    assert any("expand" in a for a in brief["acceptance_criteria"])
    assert brief["human_review_required"] is True


def test_brief_new_content_justification():
    brief = build_research_brief(
        keyword="exterminador do futuro 4k", intent={"is_question": False},
        decision=_decision(corpus_covers=False, is_question=False), corpus_docs=[],
        corpus_sections={}, gsc_queries=[], entities=[],
        cluster=None, ga4=None,
    )
    assert brief["opportunity_type"] == "new_content"
    assert brief["recommended_url"] == ""
    assert "nenhum conteúdo interno" in brief["new_content_justification"]
    assert brief["duplication_risk"].startswith("BAIXO")
    assert brief["human_review_required"] is True


def test_brief_high_duplication_risk():
    docs = [_corpus_docs(f"https://x.com/op{i}/", f"Título {i}")[0]
            for i in range(4)]
    brief = build_research_brief(
        keyword="one piece", intent={}, decision=_decision(),
        corpus_docs=docs, corpus_sections={}, gsc_queries=[],
        entities=[], cluster=None, ga4=None,
    )
    assert brief["duplication_risk"].startswith("ALTO")
    assert "canibalização" in brief["duplication_risk"].lower()


def test_brief_llm_role_is_scoped():
    brief = build_research_brief(
        keyword="x", intent={}, decision=_decision(), corpus_docs=_corpus_docs(),
        corpus_sections={}, gsc_queries=[], entities=[], cluster=None, ga4=None,
    )
    assert "síntese opcional" in brief["llm_role"]
    assert "sem autoridade para executar" in brief["llm_role"]


def test_brief_external_suggestions_as_subtopics():
    """M4/M7: sugestões externas do Trends entram como subtópicos marcados
    (sinal de demanda), nunca como pauta."""
    external = {
        "provider": "trends_scrape",
        "keyword_suggestions": [
            {"keyword": "One Piece season 2", "type": "TV series season"},
            {"keyword": "One-piece swimsuit", "type": "Suit"},
        ],
        "data_status": "available",
    }
    brief = build_research_brief(
        keyword="one piece", intent={}, decision=_decision(),
        corpus_docs=_corpus_docs(), corpus_sections={}, gsc_queries=[],
        entities=[], cluster=None, ga4=None, external=external,
    )
    joined = " ".join(brief["subtopics_questions"])
    assert "tópico externo (trends_scrape)" in joined
    assert "One Piece season 2" in joined
    # evidência externa registrada, sem autoridade de execução
    assert brief["evidence"]["external"]["provider"] == "trends_scrape"
    assert brief["human_review_required"] is True
