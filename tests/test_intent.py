"""Tests for E1: query normalization + intent classification."""

from hermes_seo_agent.tools.intent import (
    classify_intent,
    group_variations,
    normalize_query,
)


def test_normalize_query():
    assert normalize_query("Quantos Anos Tem o Gojo?") == "quantos anos tem o gojo"
    assert normalize_query("  Cómo  Funciona ") == "como funciona"


def test_classify_intent_question():
    assert classify_intent("quantos anos tem o gojo") == "question"
    assert classify_intent("o que aconteceu com viserys") == "question"
    assert classify_intent("será que wolverine e dentes de sabre são irmãos") == "question"


def test_classify_intent_comparison():
    assert classify_intent("scorpion ou sub zero mais forte") == "comparison"
    assert classify_intent("melhor jogo ps5 2025") == "comparison"


def test_classify_intent_news():
    assert classify_intent("anime india mumbai 2026") == "news"
    assert classify_intent("lançamento de star overdrive") == "news"


def test_classify_intent_brand_and_informational():
    assert classify_intent("unicorniohater") == "brand"
    assert classify_intent("idade dos personagens de jujutsu") == "informational"
    assert classify_intent("") == "unknown"


def test_group_variations():
    groups = group_variations(["Quantos Anos Tem o Gojo?", "quantos anos tem o gojo",
                               "Choso Idade"])
    assert len(groups["quantos anos tem o gojo"]) == 2
