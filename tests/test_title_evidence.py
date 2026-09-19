"""SEO-INC-017/018/019: seleção pelo baseline, intenção e cadeia de evidência.

Os três resíduos de heurística que a revisão apontou:

1. `ctr <= 2%` fixo selecionava os candidatos (erra nos dois sentidos: entra
   página saudável de segmento fraco e fica de fora a anomalia de segmento
   forte). Agora quem decide é o baseline do PRÓPRIO site.
2. `_covered()` a 50% lexical aceitava "Gojo: poderes e história" como resposta
   para "quantos anos tem gojo" — entidade coberta, intenção não.
3. A decisão de alterar título não exigia cadeia completa nem carregava a
   evidência citável.
"""

from __future__ import annotations

from hermes_seo_agent.tools.title_opportunities import (
    _covered,
    empirical_title_case,
    intent_terms,
)
from hermes_seo_agent.report.baseline import classify_ctr


def test_intencao_nao_coberta_pela_entidade():
    """SEO-INC-018: cobrir 'gojo' não cobre 'quantos anos tem gojo'."""
    # título só com a entidade -> gap de intenção
    assert _covered("quantos anos tem gojo", "Gojo: poderes e história") is False
    # título com a intenção (anos) -> coberto
    assert _covered("quantos anos tem gojo", "Quantos anos tem Gojo? Idade do feiticeiro") is True
    # altura: variantes contam
    assert _covered("qual a altura do gojo", "Gojo: altura e poderes") is True
    assert _covered("qual a altura do gojo", "Gojo: historia completa") is False


def test_intent_terms_detecta_grupos():
    labels = [label for label, _v in intent_terms("quantos anos tem gojo e onde assistir")]
    assert "idade" in labels and "onde_assistir" in labels
    assert intent_terms("jujutsu kaisen episodio 12") == ()


def test_cadeia_completa_recomenda_review_title():
    """Todos os elos presentes -> review_title com confiança alta."""
    case = empirical_title_case(
        impressions=1832, ctr=0.0038, position=4.7,
        baseline_verdict={"verdict": "below_p10", "context": "3-5|imp500-2k",
                          "sample_size": 38},
        query="quantos anos tem gojo", query_impressions=712,
        title="Gojo: poderes e história",
        ga4={"sessions": 340, "engagement_rate": 0.71},
    )
    assert case["action"] == "review_title" and case["confidence"] == "high"
    assert case["missing"] == []
    ev = case["evidence"]
    assert ev["baseline"]["context"] == "3-5|imp500-2k"
    assert ev["query_evidence"]["coverage"] == "partial"   # GSC não é exaustivo
    assert any("P10" in r for r in case["reason"])


def test_cadeia_sem_gap_nao_altera_titulo():
    """Intenção já coberta -> no_title_change (sem churn)."""
    case = empirical_title_case(
        impressions=1800, ctr=0.0038, position=4.7,
        baseline_verdict={"verdict": "below_p10"},
        query="quantos anos tem gojo", query_impressions=700,
        title="Quantos anos tem Gojo? Idade e história do feiticeiro",
    )
    assert case["action"] == "no_title_change"
    assert "query_title_gap" in case["missing"]


def test_cadeia_sem_demanda_pede_mais_dados():
    case = empirical_title_case(
        impressions=180, ctr=0.0, position=9.0,
        baseline_verdict={"verdict": "below_comparable"},
        query="sylvie morre em loki", query_impressions=3,
        title="O que aconteceu no final de Loki",
    )
    assert case["action"] == "gather_more_data" and case["confidence"] == "low"


def test_cadeia_bloqueia_pos_clique_ruim():
    """GA4 muito ruim: não é problema de título — investigar antes."""
    case = empirical_title_case(
        impressions=2000, ctr=0.004, position=5.0,
        baseline_verdict={"verdict": "below_p10"},
        query="onde assistir jujutsu", query_impressions=200,
        title="Jujutsu Kaisen: guia",
        ga4={"sessions": 300, "engagement_rate": 0.12},
    )
    assert case["action"] != "review_title"
    assert "post_click_healthy" in case["missing"]


def test_ga4_e_trends_nao_criam_necessidade():
    """Sem anomalia no baseline, GA4/Trends altos não geram proposta."""
    case = empirical_title_case(
        impressions=2000, ctr=0.05, position=2.0,
        baseline_verdict={"verdict": "high"},
        query="melhores animes", query_impressions=900,
        title="Os melhores animes",
        ga4={"sessions": 900, "engagement_rate": 0.9},
        trends={"interest": 95, "momentum": 1},
    )
    assert case["action"] != "review_title"
    assert case["checks"]["ctr_below_baseline"] is False


def test_low_nao_autoriza_mudanca_de_titulo():
    """`low` (entre P10 e P25) é sinal fraco: no máximo investigar.

    Mesmo com gap de intenção presente, um CTR apenas "low" não autoriza
    reescrever título (só `below_p10`/`below_comparable` autorizam).
    """
    case = empirical_title_case(
        impressions=1500, ctr=0.01, position=5.0,
        baseline_verdict={"verdict": "low"},
        query="quantos anos tem gojo", query_impressions=400,
        title="Gojo: poderes e história",   # <- gap de intenção presente
        ga4={"sessions": 80, "engagement_rate": 0.6},
    )
    assert case["action"] == "investigate_cause"
    assert case["checks"]["ctr_low"] is True
    assert case["checks"]["ctr_below_baseline"] is False
    assert case["checks"]["query_title_gap"] is True


def test_posicao_ausente_nao_e_acionavel():
    """Sem posição a cadeia está incompleta — não vira review_title."""
    case = empirical_title_case(
        impressions=1500, ctr=0.0, position=None,
        baseline_verdict={"verdict": "below_p10"},
        query="quantos anos tem gojo", query_impressions=300,
        title="Gojo: poderes",
        ga4={"sessions": 50, "engagement_rate": 0.6},
    )
    assert case["action"] != "review_title"
    assert "position_actionable" in case["missing"]


def test_ga4_ausente_rebaixa_confianca():
    """GA4 ausente = ausência de evidência: não bloqueia, mas nunca `high`."""
    case = empirical_title_case(
        impressions=1800, ctr=0.002, position=4.0,
        baseline_verdict={"verdict": "below_p10"},
        query="quantos anos tem gojo", query_impressions=500,
        title="Gojo: poderes e história",
        ga4=None,
    )
    assert case["action"] == "review_title"
    assert case["confidence"] == "medium"


def test_demanda_vem_da_query_escolhida(tmp_path):
    """SEO-INC-019b: a demanda é da query que o seletor escolheu, não do topo.

    `queries[0]` (ordenado por cliques) pode ter impressões altas enquanto a
    query escolhida tem pouca demanda — usar queries[0] inflava o gate.
    """
    from hermes_seo_agent.tools.title_opportunities import strategic_title

    queries = [
        {"keys": ["gojo"], "impressions": 800, "clicks": 20, "position": 4.0, "ctr": 0.025},
        {"keys": ["quantos anos tem gojo"], "impressions": 7, "clicks": 0,
         "position": 3.0, "ctr": 0.0},
    ]
    decision = strategic_title("Gojo: poderes e história", queries)
    assert decision is not None
    escolhida = decision["keyword"]
    imp_escolhida = float((decision.get("gsc") or {}).get("impressions", 0))
    if escolhida != "gojo":
        assert imp_escolhida == 7.0, (escolhida, imp_escolhida)
        case = empirical_title_case(
            impressions=800, ctr=0.025, position=4.0,
            baseline_verdict={"verdict": "below_p10"},
            query=escolhida, query_impressions=imp_escolhida,
            title="Gojo: poderes e história",
            ga4={"sessions": 50, "engagement_rate": 0.6},
        )
        assert case["checks"]["query_demand"] is False
        assert case["action"] == "gather_more_data"


def test_below_comparable_exige_captura_material():
    """SEO-INC-017b: p75 ~ruído não sustenta 'anomalia relativa'."""
    ruido = {"n": 8, "p10": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.001}
    assert classify_ctr(0.0, ruido) != "below_comparable"
    real = {"n": 22, "p10": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0046}
    assert classify_ctr(0.0, real) == "below_comparable"
