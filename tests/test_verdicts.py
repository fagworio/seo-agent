"""SEO-INC-012: medição multiaxial + diagnóstico + decisão.

O teste mais importante aqui é o de INTEGRAÇÃO: `impact_deltas()` (contrato
real do pipeline) alimentando o veredito. A versão anterior passava `before`
como None no fluxo integrado, então +2% de impressões já virava "up" — o
teste unitário com dicionário montado à mão não pegava isso.
"""

from hermes_seo_agent.report.impact import impact_deltas
from hermes_seo_agent.report.verdicts import (
    DOWN, FLAT, MIXED, UNKNOWN, UP,
    diagnosis_codes, evaluate_result, merge_axes, multiaxial_verdict, recommend,
)


# -- o bug real: contrato integrado ----------------------------------------

def test_integracao_ruido_nao_vira_movimento():
    """+2% de impressões/cliques e -0,1 de posição = no_change (não 'up')."""
    before = {"impressions": 1000, "clicks": 100, "ctr": 0.10, "position": 5.0}
    after = {"impressions": 1020, "clicks": 102, "ctr": 0.10, "position": 4.9}
    deltas = impact_deltas(before, after)
    verdict, axes = multiaxial_verdict(deltas, {})
    assert verdict == "no_change", (verdict, axes)
    assert axes["visibility"] == FLAT and axes["acquisition"] == FLAT


def test_integracao_um_clique_nao_e_regressao():
    """Base 100: perder 1 clique (1%) é ruído — não pode virar regressed."""
    before = {"impressions": 5000, "clicks": 100, "ctr": 0.02, "position": 4.0}
    after = {"impressions": 4990, "clicks": 99, "ctr": 0.0198, "position": 4.05}
    deltas = impact_deltas(before, after)
    verdict, _ = multiaxial_verdict(deltas, {})
    assert verdict != "regressed", verdict


def test_integracao_queda_real_e_regressao():
    """-40% de impressões e -50% de cliques: aí sim regrediu."""
    before = {"impressions": 5000, "clicks": 200, "ctr": 0.04, "position": 3.0}
    after = {"impressions": 3000, "clicks": 100, "ctr": 0.033, "position": 3.2}
    deltas = impact_deltas(before, after)
    verdict, axes = multiaxial_verdict(deltas, {})
    assert verdict == "regressed", (verdict, axes)


# -- eixos preservam conflito ----------------------------------------------

def test_merge_preserva_conflito():
    assert merge_axes(UP, DOWN) == MIXED
    assert merge_axes(DOWN, FLAT) == DOWN
    assert merge_axes(UP, UNKNOWN) == UP
    assert merge_axes(UNKNOWN, UNKNOWN) == UNKNOWN


def test_visibility_mixed_quando_impressoes_caem_e_posicao_melhora():
    gsc = {"impressions_delta": -100, "impressions_before": 1000, "impressions_after": 900,
           "position_delta": -4.0, "position_before": 8.0, "position_after": 4.0}
    verdict, axes = multiaxial_verdict(gsc, {})
    assert axes["visibility"] == MIXED, axes
    assert verdict == "mixed", verdict


def test_vis_down_com_acq_up_e_mixed_nao_traffic_up():
    """Perdeu metade da visibilidade mas os cliques subiram -> mixed."""
    gsc = {"impressions_delta": -50000, "impressions_before": 100000,
           "impressions_after": 50000, "position_delta": 0.0, "position_before": 3.0,
           "position_after": 3.0, "clicks_delta": 200, "clicks_before": 2000,
           "clicks_after": 2200, "ctr_delta": 0.02, "ctr_before": 0.02, "ctr_after": 0.044}
    verdict, axes = multiaxial_verdict(gsc, {})
    assert verdict == "mixed", (verdict, axes)


def test_visibility_anomalia_nao_e_regressao():
    """Posição alta + impressões crescendo + CTR ~0 -> visibility_up."""
    gsc = {"impressions_delta": 5000, "impressions_before": 2000, "impressions_after": 7000,
           "position_delta": -1.0, "position_before": 4.0, "position_after": 3.0,
           "clicks_delta": 0, "clicks_before": 2, "clicks_after": 2,
           "ctr_delta": 0.0, "ctr_before": 0.001, "ctr_after": 0.001}
    verdict, axes = multiaxial_verdict(gsc, {})
    assert verdict == "visibility_up", (verdict, axes)


# -- diagnóstico e decisão --------------------------------------------------

def test_diagnostico_ctr_anomalo_com_query_alinhada_nao_mexe_titulo():
    gsc = {"position_after": 1.6, "impressions_after": 344, "ctr_after": 0.0,
           "impressions_delta": 100, "impressions_before": 244, "position_delta": -0.2,
           "position_before": 1.8, "clicks_delta": 0, "clicks_before": 0, "clicks_after": 0}
    out = evaluate_result(gsc, {}, query_aligned=True)
    assert out["measurement"]["verdict"] == "visibility_up"
    assert out["diagnosis"]["ctr_anomaly"] is True
    assert out["diagnosis"]["cause"] == "undetermined"
    assert out["decision"]["recommended_action"] == "no_title_change"
    assert out["decision"]["review_required"] is False


def test_regressao_sem_causa_nao_vira_revisao_de_titulo():
    gsc = {"impressions_delta": -3000, "impressions_before": 5000, "impressions_after": 2000,
           "impressions_pct": -60.0, "clicks_delta": -80, "clicks_before": 100,
           "clicks_after": 20, "clicks_pct": -80.0, "position_after": 3.0,
           "position_before": 3.0, "position_delta": 0.0}
    out = evaluate_result(gsc, {}, query_aligned=True)
    assert out["measurement"]["verdict"] == "regressed"
    assert out["decision"]["recommended_action"] == "investigate_cause"
    assert out["decision"]["review_required"] is True


def test_perda_de_trafego_com_gap_de_query_vira_revisao_de_titulo():
    gsc = {"impressions_delta": -2000, "impressions_before": 3000, "impressions_after": 1000,
           "impressions_pct": -66.0, "clicks_delta": -50, "clicks_before": 60,
           "clicks_after": 10, "clicks_pct": -83.0, "position_after": 6.0,
           "position_before": 6.0, "position_delta": 0.0}
    diag = diagnosis_codes(gsc, {}, query_aligned=False)
    dec = recommend("regressed", {"visibility": DOWN, "acquisition": DOWN}, diag)
    assert "query_title_gap" in diag["codes"]
    assert dec["recommended_action"] == "review_title"
    assert dec["review_required"] is True


def test_sem_dados_e_monitor():
    out = evaluate_result({}, {})
    assert out["measurement"]["verdict"] == "insufficient_data"
    assert out["decision"]["recommended_action"] == "gather_more_data"
    assert out["decision"]["review_required"] is False
