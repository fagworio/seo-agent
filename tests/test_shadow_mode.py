"""FASE 19 — shadow mode (F21), rollout (F23) e telemetria (F24)."""

from __future__ import annotations

from hermes_seo_agent.report.shadow_mode import (MODE_APPROVAL, MODE_AUTO, MODE_OBSERVE,
                                                engine_telemetry, measurement_summary,
                                                rollout_policy, shadow_compare,
                                                shadow_outcome_case, shadow_report,
                                                stratified_sample)


def _new_contract(decision="review_title", confidence="high", gain=0.42):
    return {
        "url": "https://x/gojo", "decision": decision, "confidence": confidence,
        "query_families": [
            {"family": "gojo::idade", "intent": "idade", "share": 0.42,
             "impressions": 1070},
            {"family": "gojo::poderes", "intent": "poderes", "share": 0.36,
             "impressions": 920},
        ],
        "current_title": {"title": "Gojo: poderes", "coverage": 0.36},
        "candidate": {"intents": ["idade", "poderes"], "families": ["gojo::idade",
                                                                   "gojo::poderes"],
                      "observed_demand_coverage": 0.78, "score": 78.7,
                      "phrase": "Gojo: idade e poderes"},
        "candidates_evaluated": [{"intents": ["idade"], "score": 60.0},
                                 {"intents": ["idade", "poderes"], "score": 78.7}],
        "rankability": {"gojo::idade": 0.74},
        "baseline": {"verdict": "below_p10"},
        "page": {"position": 5.2, "ctr": 0.0074},
        "ga4": {"status": "available"},
        "checks": {"baseline_anomaly": True, "title_coverage_gap": True,
                   "position_actionable": True, "entity_preserved": True,
                   "evidence_confidence": True, "page_impressions_sufficient": True,
                   "query_family_demand_sufficient": True},
        "checks_context": {"coverage_gain": gain},
        "model_version": "title-engine/1", "weights_version": 0,
    }


# --- FASE 21: shadow mode --------------------------------------------------

def test_shadow_registra_divergencia_sem_publicar():
    old = {"decision": "no_title_change", "confidence": "medium",
           "primary_query": "quantos anos tem gojo", "score": 1.2,
           "reason": ["CTR acima do P10", "intenção não coberta"]}
    pair = shadow_compare(old=old, new=_new_contract(), url="https://x/gojo")
    assert pair["old_decision"] == "no_title_change"
    assert pair["new_decision"] == "review_title"
    assert pair["same_decision"] is False
    assert pair["published"] is False
    assert "quantos anos tem gojo" in pair["reason_for_difference"]
    assert "idade" in pair["reason_for_difference"]
    assert "ganho de cobertura" in pair["reason_for_difference"]


def test_shadow_concordancia_entre_motores():
    pair = shadow_compare(old={"decision": "review_title"},
                          new=_new_contract(), url="u")
    assert pair["same_decision"] is True
    assert pair["reason_for_difference"] == "mesma decisão nos dois motores"


def test_shadow_report_conta_transicoes():
    pairs = [
        shadow_compare(old={"decision": "no_title_change"}, new=_new_contract(), url="a"),
        shadow_compare(old={"decision": "no_title_change"}, new=_new_contract(), url="b"),
        shadow_compare(old={"decision": "review_title"}, new=_new_contract(), url="c"),
    ]
    report = shadow_report(pairs)
    assert report["compared"] == 3 and report["divergent"] == 2
    assert report["transitions"] == {"no_title_change->review_title": 2}
    assert report["agreement_rate"] == round(1 / 3, 4)
    assert report["published"] is False


# --- FASE 23: rollout ------------------------------------------------------

def test_etapa_a_nunca_escreve():
    policy = rollout_policy(_new_contract(), mode=MODE_OBSERVE)
    assert policy["writes_allowed"] is False
    assert policy["approval_required"] is False
    assert "somente observação" in policy["reason"]


def test_etapa_b_exige_caixa_humana():
    policy = rollout_policy(_new_contract(), mode=MODE_APPROVAL)
    assert policy["writes_allowed"] is False and policy["approval_required"] is True


def test_etapa_c_automatiza_apenas_caso_seguro():
    seguro = _new_contract()
    policy = rollout_policy(seguro, mode=MODE_AUTO,
                            historical_success={"sufficient": True})
    assert policy["writes_allowed"] is True and policy["risk"] == "low"

    sem_historico = rollout_policy(seguro, mode=MODE_AUTO,
                                  historical_success={"sufficient": False})
    assert sem_historico["writes_allowed"] is False
    assert sem_historico["approval_required"] is True

    confianca_media = rollout_policy(_new_contract(confidence="medium"),
                                     mode=MODE_AUTO,
                                     historical_success={"sufficient": True})
    assert confianca_media["writes_allowed"] is False

    sem_decisao = rollout_policy(_new_contract(decision="no_title_change"),
                                 mode=MODE_AUTO,
                                 historical_success={"sufficient": True})
    assert sem_decisao["writes_allowed"] is False


# --- FASE 24: telemetria ---------------------------------------------------

def test_telemetria_conta_decisoes_familias_e_confianca():
    contracts = [
        _new_contract(),
        _new_contract(decision="no_title_change", confidence="medium"),
        {**_new_contract(decision="gather_more_data", confidence="low"),
         "query_families": [], "candidates_evaluated": []},
    ]
    telemetry = engine_telemetry(contracts)
    assert telemetry["pages_analyzed"] == 3
    assert telemetry["pages_with_query_data"] == 2
    assert telemetry["families_generated"] == 4
    assert telemetry["avg_families_per_page"] == round(4 / 3, 2)
    assert telemetry["combination_candidates"] == 4
    assert telemetry["review_title"] == 1
    assert telemetry["no_title_change"] == 1
    assert telemetry["gather_more_data"] == 1
    assert telemetry["high_confidence"] == 1
    assert telemetry["medium_confidence"] == 1
    assert telemetry["low_confidence"] == 1


def test_telemetria_de_resultados_medidos_7_28_56_90():
    cases = [
        shadow_outcome_case({**_new_contract(), "after": None}),
        shadow_outcome_case(_new_contract(), after={"7d": {"gsc_deltas": {"ctr": 0.01}}}),
    ]
    cases[0]["after_28d"] = {"gsc_deltas": {"position": 0.5}}
    cases[0]["verdict"] = "worsened"
    summary = measurement_summary(cases)
    assert summary["title_changes_measured_7d"] == 1
    assert summary["improved_7d"] == 1
    assert summary["title_changes_measured_28d"] == 1
    assert summary["regressed_28d"] == 1
    assert summary["title_changes_measured_56d"] == 0


def test_amostra_estratificada_para_inspecao_humana():
    """FASE 22: N contratos por estrato (decisão, confiança)."""
    contracts = [
        _new_contract(),
        _new_contract(confidence="medium"),
        _new_contract(decision="no_title_change", confidence="medium"),
        _new_contract(decision="no_title_change", confidence="medium"),
        _new_contract(decision="investigate_cause", confidence="medium"),
        _new_contract(decision="gather_more_data", confidence="low"),
    ]
    sample = stratified_sample(contracts, per_stratum=1)
    assert sample["strata"] == {"gather_more_data|low": 1,
                                "investigate_cause|medium": 1,
                                "no_title_change|medium": 2,
                                "review_title|high": 1,
                                "review_title|medium": 1}
    assert len(sample["sample"]) == 5
    assert stratified_sample(contracts, per_stratum=2)["sample"].__len__() == 6


def test_case_do_shadow_ja_vem_classificado_para_calibracao():
    case = shadow_outcome_case(_new_contract(), source="title_engine")
    assert case["intervention_type"] == "seo_title_optimization"
    assert case["eligible_for_title_calibration"] is True
    assert case["candidate_features"]["primary_intent"] == "idade"
    assert case["candidate_features"]["demand_coverage_before"] == 0.36
    assert case["candidate_features"]["demand_coverage_after"] == 0.78


def test_telemetria_traz_os_agregados_da_fase_de_shadow():
    """`observability` responde a lista de métricas do congelamento."""
    primeira = _new_contract()
    primeira["entity"] = {"value": "dredge", "source": "canonical",
                          "canonical_entity": "dredge", "canonical_plausible": True}
    primeira["signal_window"] = {"aligned": True, "families_with_measured_semantics": 2}
    primeira["observation"] = {"status": "partial", "query_observation_ratio": 0.3}
    primeira["rankability"] = {"gojo::idade": 0.4, "gojo::poderes": 0.2}

    segunda = _new_contract(decision="no_title_change", confidence="medium")
    segunda["entity"] = {"value": "Loki", "source": "page_entity",
                         "canonical_entity": "hiddleston", "canonical_plausible": False}
    segunda["signal_window"] = {"aligned": True, "families_with_measured_semantics": 0}
    segunda["observation"] = {"status": "thin", "query_observation_ratio": 0.1}
    segunda["candidate_failed_reason"] = "nenhum título validado atinge a cobertura do candidato pontuado"

    telemetry = engine_telemetry([primeira, segunda])
    observability = telemetry["observability"]
    assert observability["entity_source"] == {"canonical": 1, "page_entity": 1}
    assert observability["canonical_evaluated"] == 2
    assert observability["canonical_rejected"] == 1
    assert observability["canonical_rejection_rate"] == 0.5
    assert observability["pages_with_measured_semantics"] == 1
    assert observability["pages_with_measured_semantics_rate"] == 0.5
    assert list(observability["candidate_failed_reason"].values()) == [1]
    assert observability["query_observation_ratio"]["by_status"]["partial"] == 1
    assert observability["query_observation_ratio"]["by_status"]["thin"] == 1
    assert observability["query_observation_ratio"]["min"] == 0.1
    assert observability["query_observation_ratio"]["max"] == 0.3
    # 2 famílias na primeira + 1 no contrato padrão da segunda
    assert observability["rankability"]["count"] == 3
    assert observability["rankability"]["min"] == 0.2
    assert observability["rankability"]["max"] == 0.74
    # nada de decisão mudou: os campos antigos continuam iguais
    assert telemetry["pages_analyzed"] == 2
    assert telemetry["review_title"] == 1 and telemetry["no_title_change"] == 1
