"""Tests for E3/E4: backlog generation + interlink suggestions."""

from hermes_seo_agent.report.backlog import generate_pautas
from hermes_seo_agent.report.interlinks import explain_interlink, suggest_interlinks


def test_generate_pautas_cannibalization():
    pautas = generate_pautas(
        cannibalization=[{"query": "monstro senhor dos aneis", "urls": 7,
                          "total_impressions": 521}],
        briefs=[], top_demand=[], category_urls={}, category_titles={},
    )
    assert pautas[0]["pauta_type"] == "cannibalization_review"
    assert "monstro senhor dos aneis" in pautas[0]["title"]


def test_generate_pautas_expand_and_supporting():
    pautas = generate_pautas(
        cannibalization=[],
        briefs=[{"url": "https://x.com/a/", "title": "Titulo A", "intent": "question",
                 "gaps": [{"gap": "ctr"}], "action": "reescrever", "priority": 5.0}],
        top_demand=[{"query": "quantos anos tem o gojo", "intent": "question",
                     "impressions": 500.0, "position": 6.0}],
        category_urls={}, category_titles={},
    )
    types = {p["pauta_type"] for p in pautas}
    assert "expand_existing" in types
    assert "supporting_post" in types


def test_generate_pautas_skips_query_already_covered_by_inventory():
    pautas = generate_pautas(
        cannibalization=[], briefs=[],
        top_demand=[{"query": "idade do gojo", "intent": "informational", "impressions": 500, "position": 4}],
        category_urls={}, category_titles={},
        existing_pages=[{"url": "https://x.com/gojo-idade/", "title": "Idade do Gojo",
                         "h1": "Idade do Gojo", "h2s": ["Quantos anos ele tem"],
                         "body_text": "A idade do Gojo é explicada neste guia."}],
    )
    assert not any(p["pauta_type"] == "supporting_post" for p in pautas)


def test_generate_pautas_hub():
    pautas = generate_pautas(
        cannibalization=[], briefs=[], top_demand=[],
        category_urls={"animes": [f"https://x.com/animes/post-{i}/" for i in range(6)]},
        category_titles={"animes": ["post 1", "post 2", "post 3", "post 4", "post 5", "post 6"]},
    )
    hubs = [p for p in pautas if p["pauta_type"] == "hub_page"]
    assert len(hubs) == 1
    assert "animes" in hubs[0]["title"]


def test_suggest_interlinks_shared_tokens_not_linked():
    sources = ["https://x.com/jujutsu-kaisen-idade/"]
    targets = [
        "https://x.com/jujutsu-kaisen-gege-confirma/",   # compartilha "jujutsu"
        "https://x.com/jujutsu-kaisen-idade-gojo/",      # compartilha 2 termos
        "https://x.com/outro-post-qualquer/",            # nada em comum
        "https://x.com/jujutsu-kaisen-idade/",           # self
    ]
    existing_out = {"https://x.com/jujutsu-kaisen-idade/": {"https://x.com/jujutsu-kaisen-gege-confirma/"}}
    suggestions = suggest_interlinks(sources=sources, targets=targets,
                                     existing_out=existing_out, limit_per_source=3)
    suggested = {s["target_url"] for s in suggestions}
    assert "https://x.com/jujutsu-kaisen-idade-gojo/" in suggested   # 2 termos, não linkado
    assert "https://x.com/jujutsu-kaisen-gege-confirma/" not in suggested  # já linkado
    assert "https://x.com/outro-post-qualquer/" not in suggested     # sem relação
    assert "https://x.com/jujutsu-kaisen-idade/" not in suggested    # self


def test_suggest_interlinks_prefers_more_shared_tokens():
    sources = ["https://x.com/rick-morty-esposa/"]
    targets = [
        "https://x.com/rick-morty-final/",          # 1 termo
        "https://x.com/rick-morty-esposa-detalhes/",  # 2 termos
    ]
    suggestions = suggest_interlinks(sources=sources, targets=targets,
                                     existing_out={"https://x.com/rick-morty-esposa/": set()},
                                     limit_per_source=3)
    assert suggestions[0]["target_url"] == "https://x.com/rick-morty-esposa-detalhes/"


def test_suggest_interlinks_includes_context_and_skips_noindex_target():
    source = "https://x.com/gojo-idade/"
    target = "https://x.com/gojo-idade-guia/"
    suggestions = suggest_interlinks(
        sources=[source], targets=[target], existing_out={source: set()},
        contexts={
            source: {"title": "Idade do Gojo", "body_text": "A idade do Gojo é um ponto importante da história."},
            target: {"title": "Guia da idade do Gojo", "body_text": "", "status_code": 200},
        },
    )
    assert suggestions[0]["context_excerpt"]
    assert suggestions[0]["anchor"] == "Guia da idade do Gojo"
    suggestions = suggest_interlinks(
        sources=[source], targets=[target], existing_out={source: set()},
        contexts={source: {"title": "Idade do Gojo"}, target: {"title": "Idade do Gojo", "is_noindex": True}},
    )
    assert suggestions == []


def test_explain_interlink_returns_anchor_placement_and_benefits():
    detail = explain_interlink(
        source_url="https://x.com/gojo-idade/", target_url="https://x.com/gojo-guia/",
        source_context={"title": "Idade do Gojo", "h1": "Idade do Gojo",
                        "body_text": "A idade do Gojo é importante para entender sua história."},
        target_context={"title": "Guia da idade do Gojo", "h1": "Guia da idade do Gojo"},
    )
    assert detail["suggested_anchor"] == "Guia da idade do Gojo"
    assert {"idade", "gojo"}.issubset(detail["shared_terms"])
    assert detail["source_excerpt"].startswith("A idade do Gojo")
    assert detail["relevance"] in {"moderate", "strong"}
    assert detail["google_benefits"] and detail["site_benefits"]


def test_explain_interlink_flags_unrelated_content_as_weak():
    detail = explain_interlink(
        source_url="https://x.com/genigods/", target_url="https://x.com/fire-emblem/",
        source_context={"title": "Genigods Nezha chega ao Xbox", "body_text": "Nezha será lançado."},
        target_context={"title": "Fire Emblem no Nintendo Music"},
    )
    assert detail["shared_terms"] == []
    assert detail["relevance"] == "weak"
    assert "Não inserir automaticamente" in detail["insertion_instruction"]
