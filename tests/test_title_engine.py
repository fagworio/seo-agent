"""FASE 19 — motor combinatório, score, gates, evidence contract e explicação."""

from __future__ import annotations

from hermes_seo_agent.report.query_families import (build_families, demand_share,
                                                  title_coverage, tokens)
from hermes_seo_agent.report.rankability_v2 import query_rankability
from hermes_seo_agent.report.title_engine import (
    GA4_AVAILABLE, GA4_MISSING, TITLE_WEIGHTS, MAX_TITLE_INTENTS,
    combination_candidates, decide_title, family_rankability, family_semantic_signals,
    family_trends, finalize_titles, ga4_evidence_status, page_headroom,
    relevant_families, trend_factor, weighted_title_score,
)


def _row(query, impressions, clicks=0, position=5.0):
    return {"keys": [query], "impressions": impressions, "clicks": clicks,
            "position": position, "ctr": (clicks / impressions) if impressions else 0.0}


ROWS = [
    _row("quantos anos tem gojo", 500, 5, 4.0),
    _row("gojo idade", 300, 3, 5.0),
    _row("idade do gojo", 270, 6, 4.5),
    _row("gojo poderes", 920, 12, 6.0),
    _row("qual a altura do gojo", 180, 1, 8.0),
    _row("gojo", 380, 2, 3.0),
]
TITLE = "Gojo: poderes em Jujutsu Kaisen"
BASELINE = {"verdict": "below_p10", "context": "5-10|imp2k-5k", "level": "context",
            "sample_size": 82, "bucket": {"p10": 0.011, "p25": 0.018, "p50": 0.031},
            "baseline_window": "2026-08-28"}


def _evidence():
    families = build_families(ROWS)
    share = demand_share(families, url="https://www.unicorniohater.com.br/gojo")
    shares = {f["family"]: f["share"] for f in share["families"]}
    coverage = title_coverage(TITLE, share["families"], shares=shares)
    relevant = relevant_families(share)
    candidates = combination_candidates(relevant, entity="Gojo",
                                        title_terms=tokens(TITLE))
    rankability = {
        f["family"]: family_rankability(
            f, query_signals={"impressions": f["impressions"], "clicks": f["clicks"],
                              "position": f["weighted_position"]}, title=TITLE)["score"]
        for f in relevant}
    return families, share, coverage, relevant, candidates, rankability


def _contract(**overrides):
    from typing import Any

    _families, share, coverage, relevant, candidates, rankability = _evidence()
    kwargs: dict[str, Any] = dict(
        url="https://www.unicorniohater.com.br/gojo", title=TITLE,
        page={"impressions": 4300, "clicks": 31, "ctr": 0.0074, "position": 5.2,
              "entity": "Gojo"},
        baseline_verdict=BASELINE, families=share["families"], coverage=coverage,
        candidates=candidates, rankability=rankability, headroom_value=0.55,
        trends=family_trends({"quantos anos tem gojo": {"interest": 70, "momentum": 1}},
                             relevant),
        ga4={"sessions": 340, "engagement_rate": 0.71})
    kwargs.update(overrides)
    return decide_title(**kwargs)


# --- FASE 5: combinações ---------------------------------------------------

def test_combinatorio_avalia_individuais_pares_e_trios():
    _f, _s, _c, relevant, candidates, _r = _evidence()
    sizes = sorted({c["intent_count"] for c in candidates})
    assert sizes == [1, 2, 3]
    assert len(candidates) <= 25          # 5 individuais + 10 pares + 10 trios
    valid = [c for c in candidates if not c["discarded"]]
    best = max(valid, key=lambda c: c["observed_demand_coverage"])
    assert best["intents"] == ["idade", "poderes"]
    assert best["observed_demand_coverage"] == 0.7804


def test_combinatorio_descarta_com_motivo_auditavel():
    _f, _s, _c, relevant, candidates, _r = _evidence()
    reasons = {c["discard_reason"] for c in candidates if c["discarded"]}
    assert "trios_exigem_share>=15%" in reasons     # altura tem 7% de share
    assert all(c["discard_reason"] for c in candidates if c["discarded"])


def test_combinatorio_recusa_duplicacao_semantica_e_incompativel():
    families = [
        {"family": "jogo::onde_assistir", "intent": "onde_assistir", "share": 0.4,
         "impressions": 400, "queries": ["onde assistir jogo"]},
        {"family": "jogo::streaming", "intent": "streaming", "share": 0.3,
         "impressions": 300, "queries": ["jogo streaming"]},
        {"family": "jogo::preco", "intent": "preco", "share": 0.3,
         "impressions": 300, "queries": ["quanto custa jogo"]},
        {"family": "jogo::final", "intent": "final", "share": 0.2,
         "impressions": 200, "queries": ["final explicado jogo"]},
    ]
    cands = combination_candidates(families, entity="Jogo")
    reasons = {(tuple(c["intents"])): c["discard_reason"] for c in cands}
    assert reasons[("onde_assistir", "streaming")] == "duplicacao_semantica"
    assert reasons[("onde_assistir", "preco")] == "intencao_incompativel"
    assert reasons[("preco", "final")] == "intencao_incompativel"


def test_combinatorio_descarta_entidade_perdida_e_comprimento():
    families = [{"family": "muito-longa-entidade::poderes", "intent": "poderes",
                 "share": 0.5, "impressions": 500, "queries": ["poderes"]},
                {"family": "muito-longa-entidade::idade", "intent": "idade",
                 "share": 0.4, "impressions": 400, "queries": ["idade"]}]
    cands = combination_candidates(families, entity="Entidade Que Nao Cabe No Titulo",
                                   max_len=25)
    assert all(c["discarded"] for c in cands)
    assert {c["discard_reason"] for c in cands} <= {"comprimento_inviavel",
                                                    "entidade_perdida"}


# --- FASE 6: rankability reaproveitada ------------------------------------

def test_rankability_da_familia_usa_a_formula_existente():
    """family_rankability é a MESMA fórmula de rankability_v2 (nenhuma paralela)."""
    _f, share, _c, relevant, _cand, rankability = _evidence()
    family = relevant[0]
    dist = {"total": 1, "counts": {"top3": 0, "top10": 0, "top20": 0, "top50": 0},
            "shares": {"top3": 0.0, "top10": 0.0, "top20": 0.0, "top50": 0.0},
            "median_position": family["weighted_position"],
            "avg_position": family["weighted_position"]}
    signals = {"keyword": family["family"], "impressions": family["impressions"],
               "clicks": family["clicks"], "position": family["weighted_position"],
               # mesmos sinais que o fallback do motor monta (medidos, não fake)
               "semantic": family_semantic_signals(family, title=TITLE)}
    direct = query_rankability(signals,
                               {"related_queries": 0, "related_top10_queries": 0},
                               dist)
    assert rankability[family["family"]] == direct["score"]
    # o fator é FACILIDADE observada (mais autoridade nunca reduz o rankability)
    assert "observed_ease" in direct["factors"]
    assert "observed_difficulty" not in direct["factors"]


def test_rankability_cresce_com_autoridade_historica():
    """Teste monotônico: mais autoridade do assunto nunca diminui o rankability."""
    dist = {"total": 4, "counts": {"top3": 0, "top10": 2, "top20": 3, "top50": 4},
            "shares": {"top3": 0.0, "top10": 0.5, "top20": 0.75, "top50": 1.0},
            "median_position": 8.0, "avg_position": 9.0}
    cluster = {"related_queries": 40, "related_top10_queries": 20}
    base = {"keyword": "gojo idade", "impressions": 900, "clicks": 9,
            "position": 5.0,
            "semantic": {"entity_fit": 1.0, "title_fit": 1.0, "body_fit": 0.6}}
    fraco = query_rankability({**base, "topic_authority": 0.1}, cluster, dist)
    forte = query_rankability({**base, "topic_authority": 0.9}, cluster, dist)
    assert forte["score"] > fraco["score"]
    assert forte["factors"]["observed_ease"]["score"] > fraco["factors"]["observed_ease"]["score"]


# --- FASE 7: score ---------------------------------------------------------

def test_score_e_indice_0_100_com_pesos_somando_1():
    assert round(sum(TITLE_WEIGHTS.values()), 6) == 1.0
    scored = weighted_title_score({k: 1.0 for k in TITLE_WEIGHTS})
    assert scored["score"] == 100.0
    assert scored["scale"] == "0-100"
    assert "Title Opportunity Score" in scored["label"]
    assert "probabilidade" not in scored["label"].lower()
    assert scored["semantics"].startswith("índice determinístico")


def test_score_e_reproduzivel_a_partir_da_mesma_evidencia():
    first = _contract()
    second = _contract()
    assert first["candidate"]["score"] == second["candidate"]["score"]
    assert first["candidate"]["factors"] == second["candidate"]["factors"]


# --- FASE 8 / FASE 19: gates ----------------------------------------------

def test_cadeia_completa_recomenda_review_title_high():
    contract = _contract()
    assert contract["decision"] == "review_title"
    assert contract["confidence"] == "high"
    assert contract["checks"]["passed"] is True
    assert contract["candidate"]["intents"] == ["idade", "poderes"]


def test_score_alto_sem_baseline_anomalo_nao_altera_titulo():
    contract = _contract(baseline_verdict={"verdict": "typical", "context": "x",
                                          "sample_size": 90})
    assert contract["decision"] == "no_title_change"
    assert "baseline_anomaly" in contract["checks"]["failed"]


def test_score_alto_sem_posicao_vai_para_gather_more_data():
    contract = _contract(page={"impressions": 4300, "clicks": 31, "position": None,
                               "entity": "Gojo"})
    assert contract["decision"] == "gather_more_data"
    assert contract["checks"]["position_actionable"] is False


def test_ga4_ausente_nao_bloqueia_mas_rebaixa_confianca():
    contract = _contract(ga4=None)
    assert contract["decision"] == "review_title"
    assert contract["confidence"] == "medium"
    assert contract["ga4"]["status"] == GA4_MISSING
    assert contract["ga4"]["blocks_decision"] is False


def test_ga4_com_pos_clique_ruim_manda_investigar():
    contract = _contract(ga4={"sessions": 300, "engagement_rate": 0.12})
    assert contract["decision"] == "investigate_cause"
    assert contract["ga4"]["status"] == GA4_AVAILABLE


def test_sem_demanda_de_familia_pede_mais_dados():
    contract = _contract(families=[], coverage={"covered_families": [],
                                               "uncovered_families": [],
                                               "observed_demand_coverage": 0.0,
                                               "generic_share": 0.0},
                         candidates=[])
    assert contract["decision"] == "gather_more_data"
    assert contract["confidence"] == "low"


def test_gate_de_entidade_preservada_bloqueia_candidato_sem_entidade():
    _f, share, coverage, relevant, candidates, rankability = _evidence()
    candidates = [dict(c, phrase="Idade e poderes", discarded=False,
                       discard_reason=None) for c in candidates[:1]]
    contract = decide_title(
        url="u", title=TITLE,
        page={"impressions": 4300, "clicks": 31, "position": 5.2, "entity": "Gojo"},
        baseline_verdict=BASELINE, families=share["families"], coverage=coverage,
        candidates=candidates, rankability=rankability, headroom_value=0.5)
    assert contract["checks"]["entity_preserved"] is False
    assert contract["decision"] == "no_title_change"


# --- FASE 9 / FASE 10: Trends e GA4 como sinais auxiliares -----------------

def test_trends_por_familia_reaproveita_o_mesmo_lookup():
    _f, _s, _c, relevant, _cand, _r = _evidence()
    trends = {"quantos anos tem gojo": {"interest": 80, "momentum": 1},
              "gojo idade": {"interest": 40, "momentum": -1}}
    result = family_trends(trends, relevant)
    idade = result["gojo::idade"]
    assert idade["available"] is True
    assert idade["interest"] == 60.0                     # média das queries da família
    assert result["gojo::poderes"]["available"] is False  # ausente != zero
    assert result["gojo::poderes"]["interest"] is None
    # nunca cria necessidade: fator no máximo 1 dentro do peso de 5%
    assert 0.0 <= trend_factor(idade) <= 1.0


def test_ga4_status_disponivel_insuficiente_ausente():
    assert ga4_evidence_status({"sessions": 40, "engagement_rate": 0.6})["status"] == GA4_AVAILABLE
    assert ga4_evidence_status({"sessions": 2})["status"] == "insufficient"
    assert ga4_evidence_status(None)["status"] == GA4_MISSING


# --- FASE 17 / FASE 18: evidence contract e explicabilidade ----------------

def test_evidence_contract_tem_a_forma_exigida():
    contract = _contract()
    for key in ("decision", "confidence", "page", "baseline", "query_families",
                "current_title", "candidate", "rankability", "ga4", "trends",
                "checks", "reason", "explanation"):
        assert key in contract, f"campo ausente: {key}"
    assert contract["baseline"]["p10"] == 0.011
    assert contract["baseline"]["sample_size"] == 82
    assert contract["current_title"]["coverage"] == 0.3608
    assert contract["candidate"]["observed_demand_coverage"] == 0.7804
    assert set(contract["checks"]) >= {
        "page_impressions_sufficient", "query_family_demand_sufficient",
        "baseline_anomaly", "title_coverage_gap", "position_actionable",
        "entity_preserved", "evidence_confidence"}
    assert contract["evidence_meta"]["coverage"] == "partial"


def test_explicacao_responde_por_que_esta_sendo_proposto():
    contract = _contract()
    text = contract["explanation"]
    assert "Título atual cobre aproximadamente 36%" in text
    assert '"idade" representa 42%' in text
    assert '"poderes" representa 36%' in text
    assert "idade + poderes" in text and "78%" in text
    assert "Title Opportunity Score" in text
    assert "abaixo do P10 de 82 páginas" in text
    assert "Decisão: REVIEW TITLE" in text
    assert "Confiança: HIGH" in text


def test_limite_de_intencoes_por_titulo():
    assert MAX_TITLE_INTENTS == 3
