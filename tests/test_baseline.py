"""SEO-INC-013: baseline próprio (percentis por contexto) + alinhamento.

O baseline substitui benchmarks externos por comportamento observado do próprio
site. Quando o CTR ~0 é o PADRÃO do segmento, a página não é anômala — é o site
inteiro que não captura, e a ação correta é investigar, nunca reescrever título.
"""

from hermes_seo_agent.report.baseline import (
    build_baseline, classify_ctr, content_type, context_key, ctr_verdict,
)
from hermes_seo_agent.report.verdicts import diagnosis_codes, recommend


class _FakeStorage:
    """Storage mínimo: só o query_pages que o build_baseline consulta."""

    def __init__(self, rows):
        self._rows = rows

    class _Conn:
        def __init__(self, rows):
            self._rows = rows

        def execute(self, sql, params=()):
            self._last = list(self._rows)
            return self

        def fetchall(self):
            return self._last

    @property
    def conn(self):
        return self._Conn(self._rows)


def _sq(rows):
    return _FakeStorage(rows)


def test_context_key_por_faixas():
    assert context_key(2.0, 300) == "1-3|imp<500"
    assert context_key(4.0, 900) == "3-5|imp500-2k"
    assert context_key(30.0, 5000) == "20+|imp2k+"


def test_build_baseline_calcula_percentis():
    # 6 páginas na mesma faixa, CTR 0,0 / 0,1 / 0,2 / 0,3 / 0,4 / 0,5 %
    rows = [(f"https://x/{i}/", 600, i, 4.0) for i in range(6)]
    base = build_baseline(_sq(rows), min_impressions=100, with_segments=False)
    bucket = base["contexts"]["3-5|imp500-2k"]
    assert bucket["n"] == 6
    assert bucket["p10"] < bucket["p25"] < bucket["p50"] < bucket["p75"]
    # CTR da linha 0 é 0/600 = 0 -> abaixo do P10
    v = ctr_verdict(None, position=4.0, impressions=600, ctr=0.0, baseline=base)
    assert v["verdict"] == "below_p10"


def test_amostra_pequena_nao_conclui():
    rows = [("https://x/a/", 600, 1, 4.0), ("https://x/b/", 600, 2, 4.0)]
    base = build_baseline(_sq(rows), min_impressions=100, with_segments=False)
    v = ctr_verdict(None, position=4.0, impressions=600, ctr=0.0, baseline=base)
    assert v["verdict"] == "unknown"   # n < MIN_CTX_SAMPLE


def test_ctr_zero_sitewide_nao_vira_revisao_de_titulo():
    """P50 do segmento ~0: o site inteiro não captura -> investigar, não título."""
    gsc = {"position_after": 1.6, "impressions_after": 1200, "ctr_after": 0.0,
           "impressions_delta": 100, "impressions_before": 1100}
    baseline = {"window_end": "2026-09-19", "contexts": {
        "1-3|imp500-2k": {"n": 8, "p10": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.001}}}
    diag = diagnosis_codes(gsc, {}, query_aligned=True, baseline=baseline)
    assert "ctr_zero_sitewide" in diag["codes"]
    assert diag["ctr_anomaly"] is True
    dec = recommend("visibility_up", {"visibility": "up", "acquisition": "flat",
                                      "engagement": "unknown"}, diag)
    assert dec["recommended_action"] == "no_title_change"
    assert "não título" in dec["rationale"]


def test_baseline_nao_usa_benchmark_externo():
    """O baseline é o do próprio site: segmento com P10 alto marca abaixo."""
    baseline = {"window_end": "2026-09-19", "contexts": {
        "1-3|imp500-2k": {"n": 20, "p10": 0.03, "p25": 0.05,
                          "p50": 0.08, "p75": 0.12}}}
    gsc = {"position_after": 2.0, "impressions_after": 900, "ctr_after": 0.01}
    diag = diagnosis_codes(gsc, {}, baseline=baseline)
    assert "ctr_below_baseline" in diag["codes"]
    assert classify_ctr(0.01, baseline["contexts"]["1-3|imp500-2k"]) == "below_p10"
    assert classify_ctr(0.09, baseline["contexts"]["1-3|imp500-2k"]) == "high"

def test_content_type_deterministico():
    """Tipo de conteúdo vem do título por regex — sem IA."""
    assert content_type("He-Man: os 10 vilões e inimigos mais assustadores") == "listicle"
    assert content_type("Quantos anos tem Gojo? Idade de Satoru") == "explicacao"
    assert content_type("Rick e Morty: quem é a esposa de Rick Sanchez?") == "explicacao"
    assert content_type("Vagabond anime: 27 anos esperando uma adaptação") == "outro"
    assert content_type("Nova série estreia em outubro") == "noticia"
    assert content_type("") == "unknown"


def test_segmento_exige_amostra_maior():
    """Segmento fino só é usado com amostra suficiente; senão cai no contexto."""
    base = {"window_end": "2026-09-19",
            "contexts": {"3-5|imp500-2k": {"n": 40, "p10": 0.01, "p25": 0.02,
                                           "p50": 0.03, "p75": 0.05}},
            "segments": {"listicle|term": {"n": 3, "p10": 0.0, "p25": 0.0,
                                           "p50": 0.0, "p75": 0.0}}}
    v = ctr_verdict(None, position=4.0, impressions=900, ctr=0.005,
                    baseline=base, content="listicle", entity="term")
    assert v["level"] == "context"          # n=3 < MIN_SEGMENT_SAMPLE
    assert v["verdict"] == "below_p10"      # julga contra o contexto primario


def test_segmento_usado_quando_sustenta():
    base = {"window_end": "2026-09-19",
            "contexts": {"3-5|imp500-2k": {"n": 40, "p10": 0.01, "p25": 0.02,
                                           "p50": 0.03, "p75": 0.05}},
            "segments": {"listicle|term": {"n": 12, "p10": 0.06, "p25": 0.07,
                                           "p50": 0.09, "p75": 0.12}}}
    v = ctr_verdict(None, position=4.0, impressions=900, ctr=0.02,
                    baseline=base, content="listicle", entity="term")
    assert v["level"] == "segment"          # amostra suficiente
    assert v["verdict"] == "below_p10"      # 0.02 < P10 do proprio segmento
