"""FASE 20 — integração PONTA A PONTA com as funções REAIS.

Cenário: query_pages (SQLite real) + baseline do próprio site + GA4 + Trends +
título atual -> famílias -> demand share -> cobertura -> combinações ->
rankability -> score -> gates -> decisão -> Evidence Contract -> geração ->
outcome -> calibração versionada -> novo ciclo com os pesos calibrados.

Nenhuma etapa é substituída por dicionário sintético: as funções do motor são
executadas na ordem do fluxo.
"""

from __future__ import annotations

from hermes_seo_agent.report.baseline import build_baseline, ctr_verdict
from hermes_seo_agent.report.interventions import (classify_intervention, load_cases,
                                                   outcome_record, persist_case,
                                                   title_calibration)
from hermes_seo_agent.report.query_families import (build_families, demand_share,
                                                   title_coverage, tokens)
from hermes_seo_agent.report.rankability_v2 import headroom, query_distribution
from hermes_seo_agent.report.shadow_mode import (engine_telemetry, measurement_summary,
                                                rollout_policy, shadow_compare,
                                                shadow_report, shadow_outcome_case)
from hermes_seo_agent.report.title_engine import (TITLE_WEIGHTS, combination_candidates,
                                                 decide_title, family_rankability,
                                                 family_trends, finalize_titles,
                                                 page_headroom, relevant_families)
from hermes_seo_agent.report.title_generator import generate_candidates
from hermes_seo_agent.storage.db import Storage


def _row(query, impressions, clicks=0, position=5.0):
    return {"keys": [query], "impressions": impressions, "clicks": clicks,
            "position": position, "ctr": (clicks / impressions) if impressions else 0.0}

URL = "https://www.unicorniohater.com.br/gojo"
TITLE = "Gojo: poderes em Jujutsu Kaisen"
WINDOW = ("2026-08-01", "2026-08-28")

# query x página: as QUATRO variações de idade caem na MESMA família
QUERY_ROWS = [
    ("quantos anos tem gojo", 500, 5, 4.0),
    ("gojo idade", 300, 3, 5.0),
    ("idade do gojo", 270, 6, 4.5),
    ("gojo poderes", 920, 12, 6.0),
    ("qual a altura do gojo", 180, 1, 8.0),
    ("gojo", 380, 2, 3.0),
]


def _gsc_rows():
    return [{"keys": [q], "impressions": i, "clicks": c, "position": p,
             "ctr": (c / i) if i else 0.0} for q, i, c, p in QUERY_ROWS]


def _seed_storage(path):
    """Semeia query_pages (baseline real do site) + a página alvo."""
    storage = Storage(str(path))
    rows = []
    # comparáveis do MESMO contexto (posição 5-10, impressões 2k+) com CTR bom
    for index in range(60):
        ctr = 0.03 + index * 0.0001
        impressions = 3000.0
        rows.append((f"comparavel {index}", f"https://x/c{index}", WINDOW[0], WINDOW[1],
                     impressions * ctr, impressions, ctr, 7.0, "informational"))
    # a página alvo: CTR 0,0074 (abaixo do P10 das comparáveis)
    for query, impressions, clicks, position in QUERY_ROWS:
        rows.append((query, URL, WINDOW[0], WINDOW[1], clicks, impressions,
                     clicks / impressions, position, "informational"))
    rows.append(("gojo total", URL, WINDOW[0], WINDOW[1], 31, 4300, 31 / 4300, 5.2,
                 "informational"))
    storage.conn.executemany(
        "INSERT INTO query_pages (query, url, window_start, window_end, clicks, "
        "impressions, ctr, position, intent) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows)
    storage.conn.commit()
    return storage


def test_fluxo_completo_do_gsc_ao_titulo_e_ao_outcome(tmp_path):
    storage = _seed_storage(tmp_path / "seo.db")

    # 1) baseline do PRÓPRIO site -> veredicto real da página
    baseline = build_baseline(storage, min_impressions=100)
    verdict = ctr_verdict(storage, position=5.2, impressions=4300, ctr=31 / 4300,
                          baseline=baseline)
    assert verdict["verdict"] == "below_p10", verdict
    assert verdict["sample_size"] >= 5

    # 2) famílias de query -> demanda observada -> cobertura do título atual
    families = build_families(_gsc_rows())
    assert {f["family_id"] for f in families} == {
        "gojo::idade", "gojo::poderes", "gojo::altura", "gojo::geral"}
    demand = demand_share(families, url=URL, window_start=WINDOW[0], window_end=WINDOW[1])
    assert round(sum(f["share"] for f in demand["families"]), 4) == 1.0
    shares = {f["family"]: f["share"] for f in demand["families"]}
    coverage = title_coverage(TITLE, demand["families"], shares=shares)
    assert coverage["observed_demand_coverage"] == 0.3608

    # 3) combinações + rankability + headroom + Trends (reaproveitados)
    relevant = relevant_families(demand, top_n=5)
    assert [f["intent"] for f in relevant] == ["idade", "poderes", "altura"]
    candidates = combination_candidates(relevant, entity="Gojo",
                                        title_terms=tokens(TITLE))
    rankability = {
        f["family"]: family_rankability(
            f, query_signals={"impressions": f["impressions"], "clicks": f["clicks"],
                              "position": f["weighted_position"]}, title=TITLE)["score"]
        for f in relevant}
    headroom_value, _why = headroom(5.2, 31 / 4300,
                                    (verdict.get("bucket") or {}).get("p50"))
    trends = family_trends({"quantos anos tem gojo": {"interest": 72, "momentum": 1},
                            "gojo idade": {"interest": 55, "momentum": 0}}, relevant)
    assert trends["gojo::idade"]["available"] is True

    # 4) decisão + Evidence Contract
    contract = decide_title(
        url=URL, title=TITLE,
        page={"impressions": 4300, "clicks": 31, "ctr": 31 / 4300, "position": 5.2,
              "entity": "Gojo"},
        baseline_verdict=verdict, families=demand["families"], coverage=coverage,
        candidates=candidates, rankability=rankability, headroom_value=headroom_value,
        trends=trends, ga4={"sessions": 340, "engagement_rate": 0.71})
    assert contract["decision"] == "review_title"
    assert contract["confidence"] == "high"
    assert contract["candidate"]["intents"] == ["idade", "poderes"]
    assert contract["candidate"]["observed_demand_coverage"] == 0.7804
    assert contract["current_title"]["coverage"] == 0.3608
    assert "Title Opportunity Score" in contract["explanation"]

    # 5) redação (determinística) das opções
    generated = generate_candidates(
        entity="Gojo", candidate=contract["candidate"], current_title=TITLE,
        evidence_intents=contract["candidate"]["intents"], max_len=60,
        mode="deterministic")
    assert generated["llm_used"] is False          # zero tokens na análise
    assert generated["candidates"], generated["discarded"]
    assert all(c["validation"]["ok"] for c in generated["candidates"])

    # 6) rollout: Etapa A não publica
    policy = rollout_policy(contract, mode="observe")
    assert policy["writes_allowed"] is False

    # 7) shadow vs motor atual (query individual)
    old = {"decision": "no_title_change", "confidence": "medium",
           "primary_query": "gojo poderes", "reason": ["título já cobre a query de maior clique"]}
    pair = shadow_compare(old=old, new=contract, url=URL)
    report = shadow_report([pair])
    assert report["divergent"] == 1 and report["published"] is False
    assert "idade" in pair["reason_for_difference"]
    telemetry = engine_telemetry([contract])
    assert telemetry["review_title"] == 1 and telemetry["pages_with_query_data"] == 1

    # 8) outcome persistido + medição + calibração versionada (ciclo fechado)
    case = shadow_outcome_case(contract, source="title_engine")
    outcome_id = persist_case(storage, case, keyword="gojo")
    storage.set_outcome_verdict(outcome_id, verdict="improved", days=7,
                                result={"gsc_deltas": {"ctr": 0.018, "position": -1.1}})
    loaded = load_cases(storage)
    assert len(loaded) == 1
    assert loaded[0]["verdict"] == "improved"
    assert loaded[0]["after_7d"]["gsc_deltas"]["ctr"] == 0.018
    assert measurement_summary(loaded)["improved_7d"] == 1

    # 33 cenários medidos a mais (mínimo de calibração = 30)
    _persist_history(storage, count=33)
    cases = load_cases(storage)
    assert sum(1 for c in cases if c["eligible_for_title_calibration"]) == 34
    # interventions de INTEGRIDADE não entram na amostra (FASE 12)
    persist_case(storage, outcome_record(
        intervention=classify_intervention(source="title_shortener"),
        candidate_features={"title_score": 90.0}, extra={"verdict": "improved"}))
    report_calibration = title_calibration(load_cases(storage), calibrated_at="2026-09-21")
    assert report_calibration["stage"] == "limited"
    assert report_calibration["weights_version"] == 1
    assert report_calibration["sample_count"] == 34
    assert round(sum(report_calibration["weights"].values()), 6) == 1.0

    # 9) o ciclo fecha: os pesos calibrados são usados no próximo run
    calibrated = decide_title(
        url=URL, title=TITLE,
        page={"impressions": 4300, "clicks": 31, "position": 5.2, "entity": "Gojo"},
        baseline_verdict=verdict, families=demand["families"], coverage=coverage,
        candidates=candidates, rankability=rankability, headroom_value=headroom_value,
        trends=trends, ga4={"sessions": 340, "engagement_rate": 0.71},
        weights=report_calibration["weights"],
        weights_version=report_calibration["weights_version"])
    assert calibrated["weights_version"] == 1
    assert calibrated["candidate"]["weights"] != contract["candidate"]["weights"]
    assert calibrated["decision"] == "review_title"
    storage.close()


def _persist_history(storage, *, count: int) -> None:
    """Histórico medido de otimizações (varia features e veredicto)."""
    for index in range(count):
        improved = index % 2 == 0
        case = outcome_record(
            url=f"https://x/h{index}",
            intervention=classify_intervention(source="title_engine"),
            before={"position": 4.0 if improved else 12.0},
            candidate_features={
                "demand_coverage_before": 0.30,
                "demand_coverage_after": 0.80 if improved else 0.35,
                "primary_intent": "idade",
                "query_rankability": 0.7 if improved else 0.3,
                "position_before": 4.0 if improved else 12.0,
                "title_score": 75.0 if improved else 45.0,
                "confidence": "high" if improved else "medium"},
            after={"7d": {"gsc_deltas": {"ctr": 0.02 if improved else -0.01}}},
            extra={"verdict": "improved" if improved else "worsened"})
        outcome_id = persist_case(storage, case)
        storage.set_outcome_verdict(
            outcome_id, verdict=case["verdict"], days=28,
            result={"gsc_deltas": {"ctr": 0.02 if improved else -0.01}})


def test_integracao_titulo_medido_fatores_persistidos_e_calibracao(tmp_path):
    """Fluxo endurecido: baseline das mesmas páginas GSC → famílias → candidato →
    TÍTULO medido → outcome com os SETE fatores → calibração versionada."""
    from hermes_seo_agent.report.baseline import build_baseline_from_pages

    pages = [{"keys": [f"https://x/c{i}"], "impressions": 3000.0, "clicks": 105.0,
              "position": 7.0, "ctr": 0.035} for i in range(40)]
    pages.append({"keys": [URL], "impressions": 4300.0, "clicks": 31.0,
                  "position": 5.2, "ctr": 31 / 4300})
    baseline = build_baseline_from_pages(pages, window_start="2026-08-01",
                                         window_end="2026-08-28",
                                         min_impressions=100)
    verdict = ctr_verdict(None, position=5.2, impressions=4300, ctr=31 / 4300,
                          baseline=baseline)
    assert verdict["verdict"] == "below_p10"

    ROWS = [
        _row("quantos anos tem gojo", 900, 9, 4.0),
        _row("gojo poderes", 500, 5, 6.0),
        _row("qual a altura do gojo", 400, 3, 8.0),
    ]
    families = build_families(ROWS, entity_hint="Gojo")
    demand = demand_share(families, url=URL, window_start="2026-08-01",
                          window_end="2026-08-28", page_impressions=4300.0)
    shares = {f["family"]: f["share"] for f in demand["families"]}
    assert demand["query_observation_ratio"] == round(1800 / 4300, 4)
    coverage = title_coverage("Gojo: historia", demand["families"], shares=shares)
    relevant = relevant_families(demand)
    candidates = combination_candidates(relevant, entity="Gojo",
                                        title_terms=tokens("Gojo: historia"))
    rankability = {f["family"]: 0.7 for f in relevant}
    headroom_detail = page_headroom(5.2, 31 / 4300, verdict)
    trends = family_trends({"quantos anos tem gojo": {"interest": 70, "momentum": 1}},
                           relevant)

    def _evaluate(cand, ctx, /, **_kw):
        generated = generate_candidates(entity="Gojo", candidate=cand,
                                        current_title="Gojo: historia",
                                        evidence_intents=cand["intents"], max_len=60)
        return finalize_titles(generated=generated["candidates"], candidate=cand,
                               families=demand["families"], shares=shares,
                               rankability=rankability,
                               headroom_value=ctx.get("headroom", headroom_detail),
                               trends=trends,
                               confidence_score=float(ctx.get("confidence_score") or 0))

    contract = decide_title(
        url=URL, title="Gojo: historia",
        page={"impressions": 4300, "clicks": 31, "ctr": 31 / 4300, "position": 5.2,
              "entity": "Gojo"},
        baseline_verdict=verdict, families=demand["families"], coverage=coverage,
        candidates=candidates, rankability=rankability,
        headroom_value=headroom_detail, trends=trends,
        ga4={"sessions": 300, "engagement_rate": 0.8},
        historical_success_fn=lambda count, primary: {
            "value": 0.8 if count == 1 else 0.4, "sample": 12, "scope": "segmento",
            "sufficient": True, "note": "histórico", "segment": {}},
        title_evaluator=_evaluate,
        observation_ratio=demand["query_observation_ratio"])
    # o candidato pontuado É um título com as três intenções, com cobertura MEDIDA
    assert contract["candidate"]["title"] == "Gojo: idade, poderes e altura"
    assert contract["candidate"]["observed_demand_coverage"] == 1.0
    assert contract["candidate"]["factors"]["demand_coverage"] == 1.0
    assert set(contract["candidate"]["factors"]) == set(TITLE_WEIGHTS)
    assert contract["candidate"]["history"]["value"] == 0.4     # trio
    assert contract["observation"]["status"] == "partial"
    assert contract["observation"]["query_observation_ratio"] == round(1800 / 4300, 4)

    # outcome → store → calibração com os sete fatores versionados
    storage = Storage(str(tmp_path / "hard.db"))
    case = shadow_outcome_case(contract, source="title_engine")
    assert case["candidate_features"]["score_factors"] == contract["candidate"]["factors"]
    for index in range(33):
        extra = outcome_record(
            url=f"https://x/h{index}",
            candidate_features={"score_factors": {
                **{k: 0.5 for k in TITLE_WEIGHTS},
                "demand_coverage": 0.9 if index % 2 == 0 else 0.1}},
            extra={"verdict": "improved" if index % 2 == 0 else "worsened"})
        persist_case(storage, extra)
    persist_case(storage, case)
    cases = load_cases(storage)
    report = title_calibration(cases, calibrated_at="2026-09-21")
    assert report["stage"] == "limited" and report["weights_version"] == 1
    assert report["weights"]["demand_coverage"] > TITLE_WEIGHTS["demand_coverage"]
    storage.close()
