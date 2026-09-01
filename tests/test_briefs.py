"""Tests for E2: content-gap detection + brief building."""

from hermes_seo_agent.report.briefs import build_brief, detect_gaps


def test_question_unanswered_gap():
    gaps = detect_gaps(
        title="Jujutsu Kaisen idade", h2s=["História", "Poderes"],
        word_count=800, age_days=30, ctr=0.0, impressions=5000,
        in_links=2, queries=["quantos anos tem o gojo"],
    )
    assert any(g["gap"] == "question_unanswered" for g in gaps)


def test_low_depth_gap():
    gaps = detect_gaps(
        title="X", h2s=["A"], word_count=120, age_days=30, ctr=0.05,
        impressions=100, in_links=1, queries=[],
    )
    assert any(g["gap"] == "low_depth" for g in gaps)


def test_orphan_gap():
    gaps = detect_gaps(
        title="X", h2s=["A"], word_count=800, age_days=30, ctr=0.05,
        impressions=100, in_links=0, queries=[],
    )
    assert any(g["gap"] == "orphan" for g in gaps)


def test_stale_and_ctr_gaps():
    gaps = detect_gaps(
        title="X", h2s=["A"], word_count=800, age_days=300, ctr=0.01,
        impressions=500, in_links=1, queries=[],
    )
    gaps_by_name = {g["gap"]: g for g in gaps}
    assert "stale" in gaps_by_name
    assert "ctr" in gaps_by_name


def test_build_brief_full():
    brief = build_brief(
        url="https://x.com/a/", title="Título", h2s=["Seção 1"],
        word_count=200, age_days=200, ctr=0.01, impressions=800,
        in_links=0, queries=["o que aconteceu com x"],
    )
    assert brief["url"] == "https://x.com/a/"
    assert brief["gaps"]  # at least one gap
    assert brief["priority"] > 0
    assert brief["action"]  # non-empty manual action


def test_healthy_page_no_gaps():
    gaps = detect_gaps(
        title="Título de Teste", h2s=["Como Funciona", "O que Acontece"],
        word_count=900, age_days=30, ctr=0.06, impressions=500,
        in_links=3, queries=["como funciona o teste"],
    )
    assert gaps == []
