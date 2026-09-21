"""FASE 19 — histórico de intervenções, tipos separados e calibração (F11–F14)."""

from __future__ import annotations

from hermes_seo_agent.report.interventions import (
    CANDIDATE_FEATURES, INTERVENTION_TYPES, MIN_HISTORY_SAMPLE, classify_intervention,
    historical_questions, historical_success_factor, outcome_record,
    predictability, title_calibration,
)
from hermes_seo_agent.report.title_engine import TITLE_WEIGHTS


def _case(*, coverage=0.7, rankability=0.6, verdict="improved", kind="seo_title_optimization",
          position=4.0, intents=("idade", None), after=None):
    intervention = classify_intervention(intervention_type=kind)
    return outcome_record(
        url="https://x/p", intervention=intervention,
        before={"title": "Gojo: poderes", "position": position, "ctr": 0.004},
        candidate_features={
            "demand_coverage_before": 0.36, "demand_coverage_after": coverage,
            "primary_intent": intents[0], "secondary_intent": intents[1],
            "query_rankability": rankability, "baseline_percentile": "below_p10",
            "position_before": position, "ctr_before": 0.004, "family_share": 0.42,
            "title_score": 70.0, "confidence": "high"},
        after=after or {"7d": {"gsc_deltas": {"ctr": 0.02, "position": -1.2}}},
        extra={"verdict": verdict})


# --- FASE 11: registro do outcome -----------------------------------------

def test_outcome_registra_features_e_janelas_7_28_56_90():
    case = _case(after={"7d": {"gsc_deltas": {"ctr": 0.01}},
                        "28d": {"gsc_deltas": {"ctr": 0.03}}})
    assert set(case["candidate_features"]) == set(CANDIDATE_FEATURES)
    for window in ("7d", "28d", "56d", "90d"):
        assert f"after_{window}" in case
    assert case["after_56d"] is None      # janela não medida != zero
    assert case["after_28d"]["gsc_deltas"]["ctr"] == 0.03
    assert case["intervention_type"] == "seo_title_optimization"


# --- FASE 12: separação dos tipos -----------------------------------------

def test_restauracao_de_titulo_truncado_nao_calibra_seo():
    """As restaurações recentes entram como integridade, nunca como otimização."""
    repair = classify_intervention(source="title_shortener")
    assert repair["intervention_type"] == "title_integrity_repair"
    assert repair["optimization_driven"] is False
    assert repair["eligible_for_title_calibration"] is False
    assert "fora da calibração" in repair["reason"]

    optimization = classify_intervention(source="title_engine")
    assert optimization["intervention_type"] == "seo_title_optimization"
    assert optimization["eligible_for_title_calibration"] is True
    assert set(INTERVENTION_TYPES) >= {"seo_title_optimization", "title_integrity_repair",
                                       "manual_editorial_change", "brand_cleanup",
                                       "technical_title_fix", "rollback"}


def test_tipos_desconhecidos_caem_em_manual_editorial():
    assert classify_intervention(source="qualquer-coisa")["intervention_type"] == \
        "manual_editorial_change"


# --- FASE 13: calibração versionada ---------------------------------------

def test_calibracao_nao_ajusta_pesos_com_amostra_insuficiente():
    cases = [_case(verdict="improved") for _ in range(29)]
    report = title_calibration(cases, calibrated_at="2026-09-21T00:00:00")
    assert report["stage"] == "insufficient_sample"
    assert report["weights"] == TITLE_WEIGHTS
    assert report["weights_version"] == 0          # NÃO versiona
    assert report["sample_count"] == 29
    assert "amostra insuficiente" in report["note"]


def test_calibracao_limitada_entre_30_e_100_move_no_maximo_5_por_cento():
    cases = ([_case(coverage=0.9, rankability=0.9, verdict="improved") for _ in range(35)]
             + [_case(coverage=0.2, rankability=0.1, verdict="worsened") for _ in range(5)])
    report = title_calibration(cases, calibrated_at="2026-09-21T00:00:00")
    assert report["stage"] == "limited"
    assert report["max_relative_shift"] == 0.05
    assert report["weights_version"] == 1
    assert round(sum(report["weights"].values()), 6) == 1.0
    # o eixo que separa melhoria (demand_coverage) ganha peso, dentro do teto
    assert report["weights"]["demand_coverage"] > TITLE_WEIGHTS["demand_coverage"]
    assert report["weights"]["demand_coverage"] <= TITLE_WEIGHTS["demand_coverage"] * 1.05 + 1e-9
    assert report["predictability"]["demand_coverage"] > 0


def test_calibracao_progressiva_acima_de_100_e_versiona_por_ciclo():
    cases = ([_case(coverage=0.95, verdict="improved") for _ in range(120)]
             + [_case(coverage=0.1, verdict="worsened") for _ in range(30)])
    first = title_calibration(cases, calibrated_at="t1")
    assert first["stage"] == "progressive"
    assert first["max_relative_shift"] == 0.10
    assert first["weights_version"] == 1
    second = title_calibration(cases, previous=first, calibrated_at="t2")
    assert second["weights_version"] == 2
    # variação relativa de cada eixo nunca passa de 10% por ciclo
    for key, weight in second["weights"].items():
        assert abs(weight - first["weights"][key]) <= first["weights"][key] * 0.10 + 1e-9


def test_amostra_de_calibracao_ignora_integridade_e_nao_medidos():
    cases = [_case(kind="title_integrity_repair") for _ in range(40)]
    cases += [_case(verdict="") for _ in range(40)]     # sem evidência de resultado
    report = title_calibration(cases, calibrated_at="t")
    assert report["sample_count"] == 0
    assert report["stage"] == "insufficient_sample"
    assert report["weights"] == TITLE_WEIGHTS


def test_predictabilidade_zero_sem_um_dos_grupos():
    cases = [_case(verdict="improved") for _ in range(5)]
    assert all(v == 0.0 for v in predictability(cases).values())


# --- FASE 14: historical success ------------------------------------------

def test_historical_success_neutro_sem_amostra_suficiente():
    cases = [_case(verdict="improved") for _ in range(MIN_HISTORY_SAMPLE - 1)]
    factor = historical_success_factor(cases, position=4.0)
    assert factor["value"] is None                 # neutro: score usa 0.5
    assert factor["sufficient"] is False
    assert "histórico insuficiente" in factor["note"]


def test_historical_success_usa_o_segmento_quando_ha_amostra():
    cases = ([_case(verdict="improved", position=4.0) for _ in range(8)]
             + [_case(verdict="worsened", position=4.0) for _ in range(4)]
             + [_case(verdict="worsened", position=15.0) for _ in range(12)])
    segment = historical_success_factor(cases, position=4.0)
    assert segment["sufficient"] is True
    assert segment["scope"] == "segmento"
    assert segment["value"] == round(8 / 12, 3)
    assert segment["sample"] == 12


def test_perguntas_empiricas_da_fase_14():
    cases = ([_case(verdict="improved", intents=("idade", "poderes")) for _ in range(12)]
             + [_case(verdict="worsened", intents=("poderes", None)) for _ in range(12)])
    answers = historical_questions(cases)
    questions = [q["question"] for q in answers]
    assert any("segunda intenção" in q for q in questions)
    assert any("duas intenções performam melhor que três" in q for q in questions)
    assert any("onde_assistir" in q for q in questions)
    assert any("cobertura de demanda melhora o CTR" in q for q in questions)
    pairs = next(a for a in answers if "duas intenções" in a["question"])
    assert pairs["answer"]["two_intents"]["sample"] == 12
    assert pairs["answer"]["two_intents"]["value"] == 1.0
