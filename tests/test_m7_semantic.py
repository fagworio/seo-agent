"""Tests for M7 — semântica leve/híbrida (expansão de consulta + busca híbrida)."""

from hermes_seo_agent.connectors.static_site import PageSnapshot
from hermes_seo_agent.corpus.builder import build_corpus
from hermes_seo_agent.report.semantic import expand_query, hybrid_search
from hermes_seo_agent.storage.db import Storage


def _page(url, title, body, h2s=None):
    page = PageSnapshot(url, 200)
    page.title = title
    page.h1 = [title]
    page.body_text = body
    page.html = "<h1>%s</h1>" % title
    for h2 in (h2s or []):
        page.html += f"<h2>{h2}</h2><p>{h2}</p>"
        page.body_text += f" {h2}"
    page.meta_robots = ""
    page.canonical = url
    return page


def _seed(storage: Storage) -> None:
    pages = [
        # doc sobre One Piece: menciona Luffy e a idade, mas não "quantos anos"
        _page("https://x.com/one-piece/", "Guia de One Piece",
              "One Piece é um anime. Luffy tem 19 anos no início da jornada. "
              "Navega pelo Grand Line com os Chapéus de Palha.",
              h2s=["Idade do Luffy", "Os Chapéus de Palha"]),
        # doc sobre Jujutsu: outro território
        _page("https://x.com/jjk/", "Guia de Jujutsu Kaisen",
              "Jujutsu Kaisen é um anime sobre Gojo e Yuji.",
              h2s=["O Gojo"]),
        # doc sobre esportes: não relacionado
        _page("https://x.com/futebol/", "Resultados do futebol",
              "Resultados dos jogos do campeonato.",
              h2s=["Classificação"]),
    ]
    build_corpus(storage, pages, built_at="2026-01-01T00:00:00+00:00")


# -- expansão de consulta ----------------------------------------------------

def test_expand_query_question_to_terms():
    variants = expand_query("qual a idade do luffy")
    joined = " | ".join(variants)
    # forma perguntativa encurtada + pares significativos
    assert any("luffy idade" == v or "idade luffy" in v for v in variants)
    assert variants[0] == "qual a idade do luffy"


def test_expand_query_franchise_alias():
    variants = expand_query("jjk")
    assert "jujutsu kaisen" in variants  # alias expandido


def test_expand_query_accent_and_singular():
    variants = expand_query("personagens de one piece")
    assert any("one piece" in v for v in variants)
    assert any("personagem" in v for v in variants)


def test_expand_query_empty():
    assert expand_query("") == []
    assert expand_query("   ") == []


# -- busca híbrida -----------------------------------------------------------

def test_hybrid_finds_intention_not_exact_words(tmp_path):
    """Critério M7: 'quantos anos tem o luffy' encontra o doc que diz
    'Luffy tem 19 anos' — mesmo sem o termo exato 'quantos'/'anos'."""
    db = tmp_path / "sem.db"
    with Storage(str(db)) as storage:
        _seed(storage)
        results = hybrid_search(storage, "quantos anos tem o luffy", limit=5)
        urls = [r["url"] for r in results]
        assert "https://x.com/one-piece/" in urls
        # o doc do One Piece deve ter score maior que o de futebol
        op = next(r for r in results if r["url"] == "https://x.com/one-piece/")
        fut = next((r for r in results if r["url"] == "https://x.com/futebol/"), None)
        if fut:
            assert op["semantic_score"] > fut["semantic_score"]
        # explicação presente
        assert op["matched_variants"]
        assert "semantic_score" in op


def test_hybrid_ranks_franchise_cluster_higher(tmp_path):
    db = tmp_path / "sem2.db"
    with Storage(str(db)) as storage:
        _seed(storage)
        # entidade canônica reconhecida -> doc do cluster pontua por entidade
        results = hybrid_search(storage, "one piece", limit=5)
        op = next(r for r in results if r["url"] == "https://x.com/one-piece/")
        assert op["entity_hit"] is True


def test_hybrid_section_hits(tmp_path):
    db = tmp_path / "sem3.db"
    with Storage(str(db)) as storage:
        _seed(storage)
        results = hybrid_search(storage, "idade do luffy", limit=5)
        op = next(r for r in results if r["url"] == "https://x.com/one-piece/")
        # a seção "Idade do Luffy" casa com o termo "idade"
        assert op["section_hits"] >= 1


def test_hybrid_empty_keyword(tmp_path):
    db = tmp_path / "sem4.db"
    with Storage(str(db)) as storage:
        _seed(storage)
        assert hybrid_search(storage, "") == []


def test_corpus_covers_helper_unifies_decide_register(tmp_path):
    """Consistência M7: decide/register/brief usam a MESMA definição de
    cobertura (híbrida) — uma keyword sem match lexical exato mas com match
    semântico NÃO vira 'new_content' falso."""
    from hermes_seo_agent.cli import _corpus_covers
    db = tmp_path / "sem5.db"
    with Storage(str(db)) as storage:
        _seed(storage)
        docs, semantic = _corpus_covers(storage, "quantos anos tem o luffy")
        assert len(docs) > 0
        assert semantic is True
        assert any(d["url"] == "https://x.com/one-piece/" for d in docs)
        # lexical puro (fallback) só se a semântica falhar
        docs2, semantic2 = _corpus_covers(storage, "futebol")
        assert len(docs2) >= 1
