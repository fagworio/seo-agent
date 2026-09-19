"""SEO-INC-012: veredito multiaxial — CTR é UM sinal, nunca o veredito.

Contexto (19/09/2026): páginas em posição alta com CTR ~0 (resultados
compostos: AI Overviews citam a URL e vários links compartilham a posição)
produziam "worsened" por um clique a menos e disparavam retriagem de título
sem causa real. Agora cada eixo (visibility/acquisition/engagement) é medido
separadamente e o veredito composto é explícito.
"""

from hermes_seo_agent.report.verdicts import axis_verdicts, multiaxial_verdict


def _gsc(imp, imp2, clk, clk2, ctr, ctr2, pos, pos2):
    """Deltas no formato do impact_deltas (com o 'before' p/ limite relativo)."""
    return {
        "impressions_delta": imp2 - imp, "impressions_before": imp,
        "clicks_delta": clk2 - clk, "clicks_before": clk,
        "ctr_delta": ctr2 - ctr, "ctr_before": ctr,
        "position_delta": pos2 - pos, "position_before": pos,
    }


def test_anomalia_de_ctr_nao_e_regressao():
    """Visibilidade sobe, cliques ficam ~zero: NÃO é falha do título."""
    gsc = _gsc(imp=1000, imp2=1500, clk=2, clk2=2, ctr=0.002, ctr2=0.0013,
               pos=4.0, pos2=3.5)
    verdict, axes = multiaxial_verdict(gsc, {})
    assert axes["visibility"] == "up"
    assert axes["acquisition"] == "flat"
    assert verdict == "visibility_up", "nao pode virar regressed/worsened"


def test_piora_real_regride():
    """Impressões e posição caíram sem nenhuma melhora -> regressed."""
    gsc = _gsc(imp=1000, imp2=600, clk=10, clk2=5, ctr=0.01, ctr2=0.008,
               pos=3.0, pos2=6.0)
    verdict, axes = multiaxial_verdict(gsc, {})
    assert axes["visibility"] == "down"
    assert verdict == "regressed"


def test_cliques_subindo_e_traffic_up():
    gsc = _gsc(imp=1000, imp2=1200, clk=10, clk2=25, ctr=0.01, ctr2=0.021,
               pos=5.0, pos2=4.0)
    verdict, _ = multiaxial_verdict(gsc, {})
    assert verdict == "traffic_up"


def test_ruido_nao_e_movimento():
    """Variação dentro do piso (0,1 clique / 0,1 p.p. de CTR) = no_change."""
    gsc = _gsc(imp=1000, imp2=1005, clk=10, clk2=10, ctr=0.01, ctr2=0.0101,
               pos=4.0, pos2=4.0)
    verdict, axes = multiaxial_verdict(gsc, {})
    assert verdict == "no_change", axes


def test_engajamento_sustenta_engagement_up():
    gsc = _gsc(imp=1000, imp2=1000, clk=10, clk2=10, ctr=0.01, ctr2=0.01,
               pos=4.0, pos2=4.0)
    ga4 = {"sessions_delta": 5, "sessions_before": 10,
           "engagement_rate_delta": 0.1, "engagement_rate_before": 0.4}
    verdict, axes = multiaxial_verdict(gsc, ga4)
    assert axes["engagement"] == "up"
    assert verdict == "engagement_up"


def test_sem_dados_em_nenhum_eixo():
    verdict, axes = multiaxial_verdict({}, {})
    assert verdict == "insufficient_data"
    assert set(axes.values()) == {"unknown"}
