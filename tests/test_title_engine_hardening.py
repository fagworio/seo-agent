"""Endurecimento (revisão do commit c860757) — casos de risco apontados.

Cada teste aqui corresponde a uma inconsistência real encontrada na revisão:

1. baseline 1 dia × página 28 dias (janela temporalmente inconsistente);
2. título gerado que NÃO representa o candidato pontuado;
3. calibração sem os sete fatores (proxy circular em historical_success);
4. p50 = 0 virando 6% no headroom;
5. 'metro' (altura) casando 'Metroid';
6. 'Dragon Ball' absorvendo 'Dragon Quest' (over-merge de entidade);
7. falta da razão de observação das queries (share estreito ≠ share da página);
8. historical_success igual para todas as combinações da página.
"""

from __future__ import annotations

from typing import Any

from hermes_seo_agent.report.baseline import (build_baseline,
                                              build_baseline_from_pages, ctr_verdict)
from hermes_seo_agent.report.interventions import (_feature_value, outcome_record,
                                                   predictability, title_calibration)
from hermes_seo_agent.report.query_families import (build_families, demand_share,
                                                    title_coverage, tokens)
from hermes_seo_agent.report.title_engine import (TITLE_WEIGHTS, combination_candidates,
                                                  decide_title, finalize_titles,
                                                  page_headroom, relevant_families)
from hermes_seo_agent.report.title_generator import generate_candidates
from hermes_seo_agent.storage.db import Storage

WINDOW = ("2026-08-01", "2026-08-28")


def _row(query, impressions, clicks=0, position=5.0):
    return {"keys": [query], "impressions": impressions, "clicks": clicks,
            "position": position, "ctr": (clicks / impressions) if impressions else 0.0}


def _evidence(rows, title, entity="Gojo"):
    families = build_families(rows)
    share = demand_share(families)
    shares = {f["family"]: f["share"] for f in share["families"]}
    coverage = title_coverage(title, share["families"], shares=shares)
    relevant = relevant_families(share)
    candidates = combination_candidates(relevant, entity=entity,
                                        title_terms=tokens(title))
    return share, shares, coverage, relevant, candidates


# --- 1) baseline: janela é o PAR (start, end), nunca só o fim --------------

def test_baseline_nao_agrega_janelas_diferentes_com_o_mesmo_fim(tmp_path):
    storage = Storage(str(tmp_path / "b.db"))
    rows = []
    # janela longa (28d) com CTR alto
    for index in range(40):
        rows.append((f"q{index}", f"https://x/l{index}", WINDOW[0], WINDOW[1],
                     3000 * 0.05, 3000.0, 0.05, 7.0, "informational"))
    # janela de 1 dia terminando no MESMO dia, CTR baixo
    for index in range(40):
        rows.append((f"q{index}", f"https://x/d{index}", WINDOW[1], WINDOW[1],
                     3000 * 0.001, 3000.0, 0.001, 7.0, "informational"))
    storage.conn.executemany(
        "INSERT INTO query_pages (query, url, window_start, window_end, clicks, "
        "impressions, ctr, position, intent) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    storage.conn.commit()

    # default = par mais recente (o dia), sem misturar com a janela de 28 dias
    recent = build_baseline(storage, min_impressions=100)
    assert (recent["window_start"], recent["window_end"]) == (WINDOW[1], WINDOW[1])
    assert recent["pages"] == 40
    assert recent["contexts"]["5-10|imp2k+"]["p50"] == round(0.001, 6)

    long_window = build_baseline(storage, window_start=WINDOW[0], window_end=WINDOW[1],
                                 min_impressions=100)
    assert long_window["pages"] == 40
    assert long_window["contexts"]["5-10|imp2k+"]["p50"] == round(0.05, 6)
    storage.close()


def test_baseline_das_mesmas_paginas_do_gsc_e_a_forma_consistente():
    """Página 28d e baseline 28d medidos no MESMO período (mesma coleta)."""
    pages = [_row(f"https://x/c{i}", 3000, 90, 7.0) for i in range(40)]
    pages.append(_row("https://x/alvo", 4300, 31, 5.2))
    baseline = build_baseline_from_pages(pages, window_start=WINDOW[0],
                                         window_end=WINDOW[1], min_impressions=100)
    assert baseline["source"] == "gsc_live_pages"
    assert baseline["window_start"] == WINDOW[0] and baseline["pages"] == 41
    verdict = ctr_verdict(None, position=5.2, impressions=4300, ctr=31 / 4300,
                          baseline=baseline)
    assert verdict["verdict"] == "below_p10"
    assert verdict["baseline_source"] == "gsc_live_pages"
    assert verdict["baseline_window"] == WINDOW[1]


# --- 2) o título final precisa cobrir o candidato pontuado -----------------

def test_titulo_que_cobre_so_parte_do_candidato_e_rejeitado():
    rows = [_row("quantos anos tem gojo", 900, 9, 4.0),
            _row("gojo poderes", 500, 5, 6.0)]
    share, shares, coverage, _relevant, candidates = _evidence(
        rows, "Gojo: historia completa")
    combo = next(c for c in candidates
                 if c["intents"] == ["idade", "poderes"] and not c["discarded"])
    assert combo["observed_demand_coverage"] == 1.0

    parcial = finalize_titles(
        generated=[{"title": "Gojo: idade", "template": "x",
                    "intents": ["idade", "poderes"], "source": "deterministic"}],
        candidate=combo, families=share["families"], shares=shares)
    assert parcial["best"] is None
    assert "cobertura medida" in parcial["rejected"][0]["reason"]

    completo = finalize_titles(
        generated=[{"title": "Gojo: idade e poderes", "template": "y",
                    "intents": ["idade", "poderes"], "source": "deterministic"}],
        candidate=combo, families=share["families"], shares=shares)
    assert completo["best"]["measured_coverage"] == 1.0
    # o score é do TÍTULO (cobertura medida), não da combinação
    assert completo["best"]["title_score"]["factors"]["demand_coverage"] == 1.0


def test_trio_de_intencoes_gera_e_exige_titulo_com_as_tres():
    rows = [_row("quantos anos tem gojo", 900, 9, 4.0),
            _row("gojo poderes", 500, 5, 6.0),
            _row("qual a altura do gojo", 400, 3, 8.0)]
    share, shares, _coverage, _relevant, candidates = _evidence(
        rows, "Gojo: historia completa")
    trio = next(c for c in candidates
                if c["intent_count"] == 3 and not c["discarded"])
    assert trio["observed_demand_coverage"] == 1.0

    generated = generate_candidates(entity="Gojo", candidate=trio,
                                    current_title="Gojo: historia",
                                    evidence_intents=trio["intents"], max_len=60)
    titles = [c["title"] for c in generated["candidates"]]
    assert "Gojo: idade, poderes e altura" in titles

    # título com só DUAS das três intenções é rejeitado pelo medidor
    only_two = finalize_titles(
        generated=[{"title": "Gojo: idade e poderes", "template": "x",
                    "intents": trio["intents"], "source": "deterministic"}],
        candidate=trio, families=share["families"], shares=shares)
    assert only_two["best"] is None

    all_three = finalize_titles(generated=generated["candidates"], candidate=trio,
                                families=share["families"], shares=shares)
    assert all_three["best"]["title"] == "Gojo: idade, poderes e altura"
    assert all_three["best"]["measured_coverage"] == 1.0


def test_sem_titulo_valido_a_decisao_nao_propoe_alteracao():
    rows = [_row("quantos anos tem gojo", 900, 9, 4.0),
            _row("gojo poderes", 500, 5, 6.0)]
    share, shares, coverage, relevant, candidates = _evidence(
        rows, "Gojo: poderes e historia")
    contract = decide_title(
        url="u", title="Gojo: poderes e historia",
        page={"impressions": 4300, "clicks": 31, "position": 5.2, "entity": "Gojo"},
        baseline_verdict={"verdict": "below_p10", "context": "5-10|imp2k+",
                          "sample_size": 41, "bucket": {"p10": 0.01, "p50": 0.03}},
        families=share["families"], coverage=coverage, candidates=candidates,
        rankability={f["family"]: 0.6 for f in relevant},
        headroom_value=page_headroom(5.2, 31 / 4300, {"bucket": {"p50": 0.03}}),
        ga4={"sessions": 300, "engagement_rate": 0.7},
        title_evaluator=lambda cand, ctx: {"best": None, "titles": [],
                                           "rejected": [{"title": "x",
                                                         "measured_coverage": 0.4}]})
    assert contract["decision"] == "no_title_change"
    assert "nenhum título validado" in (contract["candidate_failed_reason"] or "")


# --- 3) calibração dos SETE fatores, sem proxy circular --------------------

def _cases_single_factor(key: str, *, n: int = 20):
    cases = []
    for index in range(n):
        alta = {k: 0.5 for k in TITLE_WEIGHTS}
        alta[key] = 0.95
        baixa = {k: 0.5 for k in TITLE_WEIGHTS}
        baixa[key] = 0.05
        cases.append(outcome_record(
            url=f"https://x/i{index}-{key}",
            candidate_features={"score_factors": alta}, extra={"verdict": "improved"}))
        cases.append(outcome_record(
            url=f"https://x/w{index}-{key}",
            candidate_features={"score_factors": baixa}, extra={"verdict": "worsened"}))
    return cases


def test_predictabilidade_e_aprendida_para_cada_um_dos_sete_fatores():
    for key in TITLE_WEIGHTS:
        cases = _cases_single_factor(key)
        pred = predictability(cases)
        assert pred[key] > 0.5, key
        assert all(valor == 0.0 for other, valor in pred.items() if other != key), key
        report = title_calibration(cases, calibrated_at="t")
        assert report["weights"][key] > TITLE_WEIGHTS[key], key
        assert round(sum(report["weights"].values()), 6) == 1.0


def test_calibracao_nao_usa_o_score_final_como_proxy_do_historico():
    """historical_success ausente NÃO pode ser o próprio score (circularidade)."""
    case = outcome_record(candidate_features={"title_score": 99.0},
                          extra={"verdict": "improved"})
    assert _feature_value(case, "historical_success") is None
    assert predictability([case])["historical_success"] == 0.0


def test_confianca_persistida_em_numero_e_rotulo_legado_convertido():
    novo = outcome_record(candidate_features={"score_factors": {"confidence": 0.8}},
                          confidence_score=0.8, extra={"verdict": "improved"})
    assert novo["candidate_features"]["confidence_score"] == 0.8
    assert _feature_value(novo, "confidence") == 0.8

    # linha legada: rótulo textual vira número em vez de ser ignorado
    bom = outcome_record(candidate_features={"confidence": "high"},
                         extra={"verdict": "improved"})
    ruim = outcome_record(candidate_features={"confidence": "low"},
                          extra={"verdict": "worsened"})
    assert predictability([bom, ruim])["confidence"] > 0


def test_outcome_persiste_os_sete_fatores_do_score():
    factors = {k: 0.5 for k in TITLE_WEIGHTS}
    case = outcome_record(candidate_features={"demand_coverage_after": 0.7},
                          factors=factors, extra={"verdict": "improved"})
    assert case["candidate_features"]["score_factors"] == factors
    for key in TITLE_WEIGHTS:
        assert _feature_value(case, key) == 0.5


# --- 4) headroom nunca inventa CTR de referência ---------------------------

def test_headroom_sem_referencia_e_neutro_e_p50_zero_nao_vira_6_por_cento():
    ausente = page_headroom(5.0, 0.004, {"bucket": {}})
    assert ausente["status"] == "unknown" and ausente["score"] == 0.5
    assert ausente["expected_ctr"] is None

    degenerado = page_headroom(5.0, 0.004, {"bucket": {"p50": 0.0}})
    assert degenerado["status"] == "degenerate" and degenerado["score"] == 0.5
    assert degenerado["expected_ctr"] == 0.0

    medido = page_headroom(5.0, 0.004, {"bucket": {"p50": 0.03}})
    assert medido["status"] == "measured" and medido["expected_ctr"] == 0.03
    # CTR abaixo do P50 do segmento abre headroom, e posição mais distante abre mais
    assert page_headroom(15.0, 0.004, {"bucket": {"p50": 0.03}})["score"] > medido["score"]

    # sem posição não há headroom: 0.0 e não um valor médio
    assert page_headroom(None, 0.004, {"bucket": {"p50": 0.03}})["score"] == 0.0


# --- 7) razão de observação das queries -----------------------------------

def test_query_observation_ratio_mede_a_fatia_da_pagina():
    rows = [_row("quantos anos tem gojo", 900), _row("gojo poderes", 500),
            _row("qual a altura do gojo", 150)]
    families = build_families(rows)
    share = demand_share(families, page_impressions=5000)
    assert share["observed_impressions"] == 1550
    assert share["query_observation_ratio"] == round(1550 / 5000, 4)
    assert share["observation_status"] == "partial"
    # sem impressões da página a razão é DESCONHECIDA (não zero)
    assert demand_share(families)["query_observation_ratio"] is None
    assert demand_share(families)["observation_status"] == "unknown"


def test_ratio_de_observacao_estreito_rebaixa_a_confianca():
    rows = [_row("quantos anos tem gojo", 900, 9, 4.0),
            _row("gojo poderes", 500, 5, 6.0)]
    share, _shares, coverage, relevant, candidates = _evidence(
        rows, "Gojo: poderes e historia")
    base_kwargs: dict[str, Any] = dict(
        url="u", title="Gojo: poderes e historia",
        page={"impressions": 4300, "clicks": 31, "position": 5.2, "entity": "Gojo"},
        baseline_verdict={"verdict": "below_p10", "context": "5-10|imp2k+",
                          "sample_size": 41, "bucket": {"p10": 0.01, "p50": 0.03}},
        families=share["families"], coverage=coverage, candidates=candidates,
        rankability={f["family"]: 0.8 for f in relevant}, headroom_value=0.7,
        ga4={"sessions": 300, "engagement_rate": 0.8})
    estreito = decide_title(**base_kwargs, observation_ratio=0.12)
    assert estreito["confidence"] == "medium"
    assert estreito["observation"]["status"] == "thin"
    amplo = decide_title(**base_kwargs, observation_ratio=0.8)
    assert amplo["confidence"] in {"high", "medium"}
    assert amplo["observation"]["status"] == "well_observed"


# --- 8) historical success por COMBINAÇÃO ---------------------------------

def test_historico_de_sucesso_e_calculado_por_candidato():
    rows = [_row("quantos anos tem gojo", 900, 9, 4.0),
            _row("gojo poderes", 500, 5, 6.0)]
    share, _shares, coverage, relevant, candidates = _evidence(
        rows, "Gojo: poderes e historia")
    chamadas: list[tuple[int, str | None]] = []

    def _history(count: int, primary: str | None) -> dict:
        chamadas.append((count, primary))
        return {"value": 0.9 if count == 1 else 0.2, "sample": 15, "scope": "segmento",
                "sufficient": True, "note": "histórico", "segment": {}}

    contract = decide_title(
        url="u", title="Gojo: poderes e historia",
        page={"impressions": 4300, "clicks": 31, "position": 5.2, "entity": "Gojo"},
        baseline_verdict={"verdict": "below_p10", "context": "5-10|imp2k+",
                          "sample_size": 41, "bucket": {"p10": 0.01, "p50": 0.03}},
        families=share["families"], coverage=coverage, candidates=candidates,
        rankability={f["family"]: 0.7 for f in relevant}, headroom_value=0.6,
        ga4={"sessions": 300, "engagement_rate": 0.8},
        historical_success_fn=_history)
    # singles e pares recebem históricos DIFERENTES (era o mesmo para todos)
    historicos = {c["history"] for c in contract["candidates_evaluated"]}
    assert historicos == {0.9, 0.2}
    assert (1, "idade") in chamadas and (2, "idade") in chamadas
    # e o fator do score carrega o histórico daquela combinação
    assert contract["candidate"]["factors"]["historical_success"] in {0.9, 0.2}
