"""FASE 19 — Query Family Engine, Demand Share, Support e Coverage (unitários)."""

from __future__ import annotations

from hermes_seo_agent.report.query_families import (
    FAMILY_INTENTS, GENERIC_INTENT, INTENT_LABELS, build_families, demand_share,
    detect_entity, entity_covered, family_key, intent_matches, primary_intent,
    term_support, title_coverage, tokens,
)
from hermes_seo_agent.tools.title_opportunities import INTENT_GROUPS


def _row(query, impressions, clicks=0, position=5.0):
    ctr = (clicks / impressions) if impressions else 0.0
    return {"keys": [query], "impressions": impressions, "clicks": clicks,
            "position": position, "ctr": ctr}


# --- FASE 1: famílias ------------------------------------------------------

def test_variacoes_da_mesma_intencao_convergem_para_uma_familia():
    """"quantos anos tem gojo" / "gojo idade" / "idade do gojo" -> UMA família."""
    families = build_families([
        _row("quantos anos tem gojo", 500, clicks=5), _row("gojo idade", 300, clicks=3),
        _row("idade do gojo", 270, clicks=6)])
    assert len(families) == 1
    family = families[0]
    assert family["family_id"] == "gojo::idade"
    assert family["entity"] == "gojo" and family["intent"] == "idade"
    assert family["query_count"] == 3
    # auditoria: as queries ORIGINAIS ficam preservadas
    assert set(family["queries"]) == {"quantos anos tem gojo", "gojo idade",
                                      "idade do gojo"}
    assert family["impressions"] == 1070
    assert family["ctr"] == round(14 / 1070, 5)


def test_intencoes_distintas_permanecem_familias_diferentes():
    families = build_families([_row("gojo idade", 100), _row("gojo poderes", 90)])
    ids = {f["family_id"] for f in families}
    assert ids == {"gojo::idade", "gojo::poderes"}


def test_entidades_distintas_nao_se_misturam():
    families = build_families([_row("gojo idade", 100), _row("sukuna idade", 80)])
    assert {f["entity"] for f in families} == {"gojo", "sukuna"}


def test_entidade_e_intencao_deterministicas():
    assert detect_entity("quantos anos tem gojo") == "gojo"
    assert detect_entity("onde assistir jujutsu kaisen") == "jujutsu kaisen"
    assert primary_intent("quantos episodios tem jujutsu kaisen") == "episodios"
    assert primary_intent("gojo poderes e habilidades") == "poderes"
    assert primary_intent("gojo") == GENERIC_INTENT
    assert family_key("Gojo", "idade") == "gojo::idade"


def test_dicionario_de_familia_cobre_o_dicionario_do_gerador_estrategico():
    """Anti-duplicação: o dicionário do motor é superset do já existente."""
    family_dict = {label: aliases for label, aliases in FAMILY_INTENTS}
    for label, aliases in INTENT_GROUPS:
        assert label in INTENT_LABELS, f"label {label} desapareceu"
        for alias in aliases:
            assert alias in family_dict[label], (
                f"alias '{alias}' de {label} não está representado")


def test_multi_intencao_registrada_com_primaria_deterministica():
    matches = intent_matches("data de estreia de jujutsu kaisen")
    assert "estreia" in matches and "data" in matches
    # alias mais longo vence (data de = 7 chars > data = 4)
    assert primary_intent("data de estreia de jujutsu kaisen") == "estreia"


def test_intencao_de_localizacao_reconhecida():
    """"onde encontrar ..." é intenção de localização (expansão do dicionário)."""
    assert primary_intent("onde encontrar cada tabuleta de pedra em dredge") == "localizacao"
    assert primary_intent("dredge stone tablet locations") == "localizacao"
    # não colide com onde_assistir
    assert primary_intent("onde assistir jujutsu kaisen") == "onde_assistir"


def test_entidade_da_pagina_agrupa_variacoes_de_ordem_e_digitacao():
    """Sem a dica de entidade a MESMA intenção se fragmenta (dado real do GSC)."""
    rows = [
        _row("tabuletas dredge", 200),
        _row("dredge tabuletas", 100),
        _row("tabuletas de pedra dredge", 90),
        _row("dredge stone tablets location", 40),
    ]
    fragmentado = build_families(rows)
    assert len(fragmentado) > 2, "ordem das palavras não deveria fragmentar"
    hint = "Onde encontrar cada tabuleta de pedra em Dredge"
    agrupado = build_families(rows, entity_hint=hint)
    # agrupa por ENTIDADE + INTENÇÃO: 3 queries sem intenção (geral) + 1 de
    # localização viram 2 famílias da MESMA entidade da página — não 4.
    assert len(agrupado) == 2
    assert {f["entity"] for f in agrupado} == {"onde encontrar cada tabuleta de pedra em dredge"}
    assert {f["entity_label"] for f in agrupado} == {hint}
    assert {f["intent"] for f in agrupado} == {"geral", "localizacao"}
    assert sum(f["query_count"] for f in agrupado) == 4
    assert sum(f["impressions"] for f in agrupado) == 430


def test_entidade_de_outro_assunto_nao_e_absorvida_pela_dica():
    families = build_families([_row("gojo idade", 100), _row("sukuna idade", 90)],
                              entity_hint="Gojo")
    assert {f["entity"] for f in families} == {"gojo", "sukuna"}


# --- FASE 2: demand share --------------------------------------------------

def test_demand_share_usa_universo_observado_e_soma_1():
    families = build_families([
        _row("quantos anos tem gojo", 1070), _row("gojo poderes", 920),
        _row("qual a altura do gojo", 180), _row("gojo", 380)])
    share = demand_share(families, url="https://x/gojo", window_start="2026-08-01",
                         window_end="2026-08-28")
    assert share["observed_impressions"] == 2550
    assert share["metric"] == "observed_query_share"
    assert round(sum(f["share"] for f in share["families"]), 4) == 1.0
    by_intent = {f["intent"]: f for f in share["families"]}
    assert by_intent["idade"]["share"] == 0.4196
    assert by_intent["poderes"]["share"] == 0.3608


def test_demand_share_sem_universo_nao_vira_zero():
    """Ausência de dado NUNCA é lida como zero (princípio 4)."""
    share = demand_share([], url="https://x/vazia")
    assert share["has_data"] is False
    assert share["families"] == []
    assert share["observed_impressions"] == 0


# --- FASE 3: term/ intent support -----------------------------------------

def test_suporte_ponderado_por_impressoes_vence_numero_de_queries():
    """20 queries com 1 impressão NÃO superam 3 queries com 2.000 impressões."""
    rows = [_row(f"erro de digitacao {i}", 1) for i in range(20)]
    rows += [_row("quantos anos tem gojo", 1200), _row("gojo idade", 500),
             _row("idade do gojo", 300)]
    support = term_support(rows)
    tokens_support = {t["token"]: t for t in support["token_support"]}
    intents_support = {i["intent"]: i for i in support["intent_support"]}
    assert intents_support["idade"]["impressions"] == 2000
    assert intents_support["idade"]["share"] > tokens_support["digitacao"]["share"]
    # 20 queries / 20 impressões perdem para 3 queries / 2.000 impressões
    assert tokens_support["digitacao"]["query_count"] == 20
    assert intents_support["idade"]["query_count"] == 3
    assert intents_support["idade"]["share"] > 0.9


# --- FASE 4: coverage ------------------------------------------------------

def _demand_fixture():
    families = build_families([
        _row("quantos anos tem gojo", 1070), _row("gojo poderes", 920),
        _row("qual a altura do gojo", 180), _row("gojo", 380)])
    share = demand_share(families)
    return share, {f["family"]: f["share"] for f in share["families"]}


def test_coverage_titulo_cobrindo_so_a_intencao_secundaria():
    share, shares = _demand_fixture()
    coverage = title_coverage("Gojo: poderes em Jujutsu Kaisen",
                              share["families"], shares=shares)
    assert coverage["covered_families"] == ["gojo::poderes"]
    assert set(coverage["uncovered_families"]) == {"gojo::idade", "gojo::altura"}
    assert coverage["observed_demand_coverage"] == 0.3608
    # demanda de entidade pura não é gap de intenção, mas também não é escondida
    assert coverage["generic_share"] == 0.149
    assert all(f["counted"] is False for f in coverage["families"]
               if f["intent"] == GENERIC_INTENT)


def test_coverage_por_dicionario_nao_por_overlap_lexical():
    share, shares = _demand_fixture()
    # sinônimo/plural/acento contam
    assert title_coverage("Quantos anos tem Gojo? Idade do feiticeiro",
                          share["families"], shares=shares)["covered_families"] == ["gojo::idade"]
    # entidade coberta NÃO cobre a intenção
    assert "gojo::idade" in title_coverage("Gojo: historia completa",
                                           share["families"], shares=shares)["uncovered_families"]
    assert entity_covered("gojo", "Satoru Gojo: poderes",
                          set(tokens("Satoru Gojo: poderes"))) is True
