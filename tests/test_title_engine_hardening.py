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
                                                    entity_preserved, title_coverage,
                                                    tokens)
from hermes_seo_agent.report.title_engine import (TITLE_WEIGHTS, combination_candidates,
                                                  decide_title, family_rankability,
                                                  finalize_titles, page_headroom,
                                                  relevant_families)
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


# --- 5) Topic Authority calculado tem de ENTRAR no observed_ease ------------

def test_topic_authority_none_nos_sinais_nao_bloqueia_a_injecao():
    """`setdefault` não substitui None: o TA calculado precisa vencer o None."""
    rows = [_row("quantos anos tem gojo", 900, 9, 4.0)]
    share, _shares, _coverage, relevant, _candidates = _evidence(
        rows, "Gojo: historia")
    family = relevant[0]
    base_signals = {"topic_authority": None, "impressions": family["impressions"],
                    "clicks": family["clicks"],
                    "position": family["weighted_position"],
                    "related_top10_share": 0.5}
    fraco = family_rankability(family, query_signals=dict(base_signals),
                               cluster_signals={"related_queries": 10,
                                                "related_top10_queries": 5},
                               title="Gojo: historia", topic_authority=0.1)
    forte = family_rankability(family, query_signals=dict(base_signals),
                               cluster_signals={"related_queries": 10,
                                                "related_top10_queries": 5},
                               title="Gojo: historia", topic_authority=0.9)
    assert forte["score"] > fraco["score"]
    assert forte["factors"]["observed_ease"]["score"] == round(0.9 * 0.6 + 0.5 * 0.4, 3)

    # e um valor JÁ medido nos sinais não é sobrescrito pelo fallback
    medido = family_rankability(
        family, query_signals={**base_signals, "topic_authority": 1.0},
        cluster_signals={}, title="Gojo: historia", topic_authority=0.1)
    assert medido["factors"]["observed_ease"]["score"] == round(1.0 * 0.6 + 0.5 * 0.4, 3)


# --- 6) ausência de medição semântica é None, nunca 0.0 --------------------

def test_build_query_signals_marca_ausencia_como_none(tmp_path):
    from hermes_seo_agent.report.rankability_signals import build_query_signals

    storage = Storage(str(tmp_path / "sig.db"))
    signals = build_query_signals(storage, {"urls": ["https://x/a"]}, "gojo idade")
    semantic = signals["semantic"]
    assert set(semantic) == {"entity_fit", "title_fit", "h1_fit", "heading_fit",
                             "body_fit", "question_fit", "related_entity_fit"}
    # corpus vazio: NADA foi medido -> None (antes tudo era 0.0, como se medido)
    assert all(value is None for value in semantic.values())
    # e o semantic_fit devolve 0.0 com o motivo explícito, não uma média falsa
    from hermes_seo_agent.report.rankability_v2 import semantic_fit
    score, why = semantic_fit(semantic)
    assert score == 0.0 and "sem sinais" in why
    storage.close()


# --- 7) uma decisão = uma janela (tração não soma coletas) ----------------

def test_tracao_da_query_nao_soma_janelas_diferentes(tmp_path):
    from hermes_seo_agent.report.rankability_signals import (build_query_signals,
                                                             latest_window_pair)

    storage = Storage(str(tmp_path / "win.db"))
    url = "https://x/a"
    rows = [
        ("gojo idade", url, "2026-08-01", "2026-08-28", 0, 1000.0, 0.0, 5.0),
        ("gojo idade", url, "2026-08-28", "2026-08-28", 0, 900.0, 0.0, 6.0),
        ("gojo idade", url, "2026-08-27", "2026-08-27", 0, 1100.0, 0.0, 7.0),
    ]
    storage.conn.executemany(
        "INSERT INTO query_pages (query, url, window_start, window_end, clicks, "
        "impressions, ctr, position) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    storage.conn.commit()

    pair = latest_window_pair(storage)
    assert pair == ("2026-08-28", "2026-08-28")
    only_pair = build_query_signals(storage, {"urls": [url]}, "gojo idade",
                                    window_start=pair[0], window_end=pair[1])
    assert only_pair["impressions"] == 900.0        # não 3.000

    sem_janela = build_query_signals(storage, {"urls": [url]}, "gojo idade")
    assert sem_janela["impressions"] == 3000.0      # comportamento legado explícito
    storage.close()


def test_sinais_da_familia_ponderam_por_impressoes(monkeypatch):
    import hermes_seo_agent.report.rankability_signals as rs

    def _fake_semantic(storage, query, *, target_url=None):
        principal = query == "gojo idade"
        return {"semantic": {"body_fit": 1.0 if principal else 0.0,
                             "h1_fit": None, "heading_fit": None,
                             "entity_fit": 1.0 if principal else None,
                             "title_fit": None, "question_fit": None,
                             "related_entity_fit": None},
                "semantic_scope": "target_url", "semantic_note": "stub"}

    monkeypatch.setattr(rs, "build_query_semantic_signals", _fake_semantic)
    family = {"family_id": "gojo::idade",
              "queries": ["gojo idade", "idade do gojo"],
              "top_queries": ["gojo idade", "idade do gojo"],
              "query_impressions": {"gojo idade": 900.0, "idade do gojo": 100.0},
              "impressions": 1000.0, "clicks": 6.0, "weighted_position": 5.0}
    out = rs.build_family_query_signals(None, {}, family, target_url="https://x/a")
    # média semântica ponderada pela impressão REAL de cada query
    assert out["semantic"]["body_fit"] == 0.9
    assert out["semantic"]["entity_fit"] == 1.0          # só a principal mediu
    assert out["semantic"]["h1_fit"] is None              # ninguém mediu -> None
    # TRAÇÃO = GSC real da família (1.000), sem recontar variantes
    assert out["impressions"] == 1000.0 and out["clicks"] == 6.0
    assert out["position"] == 5.0
    assert out["traction_source"].startswith("family")
    assert out["semantic_queries"] == ["gojo idade", "idade do gojo"]
    assert out["semantic_scope"] == "target_url"


# --- 3ª rodada: janela do RUN, alinhamento real e sem dupla contagem -------

def test_signal_window_prefere_a_janela_do_proprio_run(tmp_path):
    """Várias coletas terminando no MESMO dia: usar o par do run, não o mais curto."""
    from hermes_seo_agent.report.rankability_signals import resolve_signal_window

    storage = Storage(str(tmp_path / "w.db"))
    rows = [
        # 28 dias (a janela da decisão) e 1 dia, ambos terminando em 2026-09-21
        ("gojo idade", "https://x/a", "2026-08-24", "2026-09-21", 5000.0),
        ("gojo idade", "https://x/b", "2026-09-21", "2026-09-21", 120.0),
    ]
    storage.conn.executemany(
        "INSERT INTO query_pages (query, url, window_start, window_end, impressions) "
        "VALUES (?, ?, ?, ?, ?)", rows)
    storage.conn.commit()

    window = resolve_signal_window(storage, "2026-08-24", "2026-09-21")
    assert window["aligned"] is True and window["source"] == "run_window"
    assert (window["window_start"], window["window_end"]) == ("2026-08-24", "2026-09-21")

    # o par "mais recente" escolheria a janela de 1 dia (bug estrutural) — o
    # resolver NÃO usa esse critério quando a janela do run existe
    from hermes_seo_agent.report.rankability_signals import latest_window_pair
    assert latest_window_pair(storage) == ("2026-09-21", "2026-09-21")

    # run cuja janela ainda não foi persistida: fallback EXPLÍCITO
    fallback = resolve_signal_window(storage, "2026-09-22", "2026-10-20")
    assert fallback["aligned"] is False
    assert fallback["source"] == "latest_persisted"
    assert (fallback["window_start"], fallback["window_end"]) == ("2026-09-21", "2026-09-21")
    assert "não está persistida" in fallback["note"]
    storage.close()


def test_query_title_alignment_mede_alinhamento_de_verdade():
    from hermes_seo_agent.report.query_families import query_title_alignment

    desalinhado = query_title_alignment("quantos anos tem gojo",
                                        "Os poderes mais fortes de Gojo")
    alinhado = query_title_alignment("quantos anos tem gojo",
                                     "Quantos anos tem Gojo? A idade do personagem")
    assert desalinhado is not None and alinhado is not None
    assert alinhado > 0.7 > desalinhado
    # sem título não há medição -> None (antes dava 0.9 só por ter título)
    assert query_title_alignment("quantos anos tem gojo", "") is None
    assert query_title_alignment("", "Gojo: idade") is None


def test_title_fit_vem_do_alinhamento_e_nao_da_existencia_de_titulo(tmp_path):
    """Regressão do bug antigo: `0.9 if best.get("title")` virava 0.9 sempre."""
    from hermes_seo_agent.report.rankability_signals import build_query_semantic_signals

    storage = Storage(str(tmp_path / "tf.db"))
    storage.conn.execute(
        "INSERT INTO corpus_documents (url, title, h1, body_text, built_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("https://x/a", "Os poderes mais fortes de Gojo", "Poderes de Gojo",
         "poderes e tecnicas", "2026-09-21"))
    storage.conn.commit()
    medida = build_query_semantic_signals(storage, "quantos anos tem gojo",
                                         target_url="https://x/a")
    # tem título, mas NÃO responde à query de idade: nada de 0.9 automático
    assert medida["semantic"]["title_fit"] is not None
    assert medida["semantic"]["title_fit"] < 0.6
    # documento fora do corpus: sem título medível -> None (desconhecido)
    outro = build_query_semantic_signals(storage, "quantos anos tem gojo",
                                         target_url="https://x/fora")
    assert outro["semantic"]["title_fit"] is None
    storage.close()


def test_familia_expoe_top_queries_e_impressoes_por_query():
    rows = [_row("quantos anos tem gojo", 900), _row("gojo idade", 400),
            _row("idade do gojo", 100)]
    families = build_families(rows)
    family = families[0]
    assert family["top_queries"] == ["quantos anos tem gojo", "gojo idade",
                                     "idade do gojo"]
    assert family["query_impressions"]["quantos anos tem gojo"] == 900.0
    assert sum(family["query_impressions"].values()) == family["impressions"] == 1400.0


def test_tracao_da_familia_nao_duplica_queries_expandidas(tmp_path):
    """`expand_query` faz uma query casar as variantes da irmã: a tração da
    família continua sendo o GSC REAL, sem a soma duplicada."""
    from hermes_seo_agent.report.rankability_signals import build_family_query_signals
    from hermes_seo_agent.report.semantic import expand_query

    storage = Storage(str(tmp_path / "dup.db"))
    url = "https://x/a"
    # a MESMA linha real, duas queries distintas na mesma família
    storage.conn.executemany(
        "INSERT INTO query_pages (query, url, window_start, window_end, impressions, "
        "clicks, position) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [("quantos anos tem gojo", url, "2026-08-24", "2026-09-21", 900.0, 9.0, 4.0),
         ("gojo idade", url, "2026-08-24", "2026-09-21", 400.0, 4.0, 6.0)])
    storage.conn.commit()

    rows = [_row("quantos anos tem gojo", 900, 9, 4.0), _row("gojo idade", 400, 4, 6.0)]
    family = build_families(rows)[0]
    # a expansão de "quantos anos tem gojo" já alcança "gojo idade" (colisão real)
    assert any("gojo idade" in v for v in expand_query("quantos anos tem gojo"))

    signals = build_family_query_signals(storage, {"urls": [url]}, family,
                                         window_start="2026-08-24",
                                         window_end="2026-09-21")
    assert signals["impressions"] == 1300.0     # 900 + 400, e não 900+900+400
    assert signals["clicks"] == 13.0
    assert signals["traction_source"].startswith("family")
    storage.close()



def test_historico_do_candidato_sobrevive_ao_rescore_do_titulo():
    rows = [_row("quantos anos tem gojo", 900, 9, 4.0),
            _row("gojo poderes", 500, 5, 6.0)]
    share, shares, coverage, relevant, candidates = _evidence(
        rows, "Gojo: poderes e historia")
    history = {"value": 0.2, "sample": 15, "scope": "segmento", "sufficient": True,
               "note": "histórico", "segment": {}}

    def _evaluate(cand, ctx, /, **_kw):
        # mesma cadeia que a CLI usa: gera títulos e re-mede, PRESERVANDO o
        # histórico que selecionou a combinação
        generated = generate_candidates(entity="Gojo", candidate=cand,
                                        current_title="Gojo: poderes e historia",
                                        evidence_intents=cand["intents"], max_len=60)
        return finalize_titles(generated=generated["candidates"], candidate=cand,
                               families=share["families"], shares=shares,
                               historical_success=(cand.get("history") or {}).get("value"))

    contract = decide_title(
        url="u", title="Gojo: poderes e historia",
        page={"impressions": 4300, "clicks": 31, "position": 5.2, "entity": "Gojo"},
        baseline_verdict={"verdict": "below_p10", "context": "5-10|imp2k+",
                          "sample_size": 41, "bucket": {"p10": 0.01, "p50": 0.03}},
        families=share["families"], coverage=coverage, candidates=candidates,
        rankability={f["family"]: 0.7 for f in relevant}, headroom_value=0.6,
        ga4={"sessions": 300, "engagement_rate": 0.8},
        historical_success_fn=lambda count, primary: history,
        title_evaluator=_evaluate)
    assert contract["candidate"]["history"]["value"] == 0.2
    assert contract["candidate"]["factors"]["historical_success"] == 0.2
    assert contract["candidate"]["factors"]["historical_success"] != 0.5


# --- 9) Evidence Contract: observed_impressions são IMPRESSÕES -------------

def test_contrato_expoe_impressoes_observadas_e_nao_um_share():
    rows = [_row("quantos anos tem gojo", 900, 9, 4.0),
            _row("gojo poderes", 500, 5, 6.0)]
    share, _shares, coverage, relevant, candidates = _evidence(
        rows, "Gojo: poderes e historia")
    contract = decide_title(
        url="u", title="Gojo: poderes e historia",
        page={"impressions": 4300, "clicks": 31, "position": 5.2, "entity": "Gojo"},
        baseline_verdict={"verdict": "below_p10", "context": "5-10|imp2k+",
                          "sample_size": 41, "bucket": {"p10": 0.01, "p50": 0.03}},
        families=share["families"], coverage=coverage, candidates=candidates,
        rankability={f["family"]: 0.7 for f in relevant}, headroom_value=0.6,
        ga4={"sessions": 300, "engagement_rate": 0.8},
        observed_impressions=share["observed_impressions"], observation_ratio=0.33)
    assert contract["observation"]["observed_impressions"] == 1400.0
    assert contract["observation"]["observed_impressions"] > 1.0
    assert contract["observation"]["query_observation_ratio"] == 0.33


# --- 5b) confiança não pode confundir "tem famílias" com "tem corpus" -----

def test_confianca_usa_corpus_e_semantica_REAIS():
    rows = [_row("quantos anos tem gojo", 900, 9, 4.0),
            _row("gojo poderes", 500, 5, 6.0)]
    share, _shares, coverage, relevant, candidates = _evidence(
        rows, "Gojo: poderes e historia")
    kwargs: dict[str, Any] = dict(
        url="u", title="Gojo: poderes e historia",
        page={"impressions": 4300, "clicks": 31, "position": 5.2, "entity": "Gojo"},
        baseline_verdict={"verdict": "below_p10", "context": "5-10|imp2k+",
                          "sample_size": 41, "bucket": {"p10": 0.01, "p50": 0.03}},
        families=share["families"], coverage=coverage, candidates=candidates,
        rankability={f["family"]: 0.7 for f in relevant}, headroom_value=0.6,
        ga4=None)
    sem_corpus = decide_title(**kwargs, corpus_available=False, semantic_evidence=0.0)
    com_corpus = decide_title(**kwargs, corpus_available=True, semantic_evidence=1.0)
    assert (com_corpus["confidence_detail"]["score"]
            > sem_corpus["confidence_detail"]["score"])
    assert sem_corpus["confidence_detail"]["checks"]["corpus_available"] == 0.0
    assert com_corpus["confidence_detail"]["checks"]["corpus_available"] == 1.0

def test_semantica_e_medida_na_pagina_alvo_e_nao_em_outra_pagina(tmp_path):
    """O fit semântico da página A não pode vir do melhor doc do corpus (B)."""
    from hermes_seo_agent.report.rankability_signals import build_query_semantic_signals

    storage = Storage(str(tmp_path / "alvo.db"))
    alvo = "https://x/gojo-poderes"
    irma = "https://x/gojo-idade"
    storage.conn.executemany(
        "INSERT INTO corpus_documents (url, title, h1, body_text, built_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [(alvo, "Os poderes mais fortes de Gojo", "Poderes de Gojo",
          "Lista dos poderes e tecnicas de Gojo em Jujutsu Kaisen.", "2026-09-21"),
         # página IRMÃ perfeitamente alinhada com a query de idade
         (irma, "Quantos anos tem Gojo: idade no anime", "Idade do Gojo",
          "A idade de Gojo e revelada no anime.", "2026-09-21")])
    storage.conn.executemany(
        "INSERT INTO corpus_sections (url, heading, heading_level, position, text) "
        "VALUES (?, ?, ?, ?, ?)",
        [(alvo, "Quais sao os poderes de Gojo?", 2, 1, "poderes e tecnicas"),
         (irma, "Quantos anos tem Gojo?", 2, 1, "idade de gojo no anime")])
    storage.conn.commit()

    query = "quantos anos tem gojo"
    na_alvo = build_query_semantic_signals(storage, query, target_url=alvo)
    na_irma = build_query_semantic_signals(storage, query, target_url=irma)
    assert na_alvo["semantic_scope"] == "target_url"
    # a página-alvo NÃO responde à intenção de idade, mesmo existindo uma irmã que responde
    assert (na_alvo["semantic"]["title_fit"] or 0) < 0.6
    assert (na_alvo["semantic"]["question_fit"] or 0) == 0.0
    assert na_irma["semantic"]["title_fit"] > 0.8
    assert na_alvo["semantic"]["title_fit"] < na_irma["semantic"]["title_fit"]
    assert na_irma["semantic"]["question_fit"] == 1.0
    assert na_alvo["semantic"]["body_fit"] is not None

    # URL fora do corpus: DESCONHECIDO, sem cair para outra página
    fora = build_query_semantic_signals(storage, query,
                                        target_url="https://x/nao-existe")
    assert fora["semantic_scope"] == "target_url_unavailable"
    assert all(value is None for value in fora["semantic"].values())
    assert "outra página" in fora["semantic_note"]

    # sem URL alvo não há medição semântica
    sem_alvo = build_query_semantic_signals(storage, query)
    assert sem_alvo["semantic_scope"] == "no_target"
    assert all(value is None for value in sem_alvo["semantic"].values())
    storage.close()


def test_semantica_encontra_a_pagina_com_host_diferente_www_x_prod(tmp_path):
    """GSC entrega `www.`; o corpus indexa `prod.` — o match é por PATH."""
    from hermes_seo_agent.report.rankability_signals import build_query_semantic_signals

    storage = Storage(str(tmp_path / "host.db"))
    storage.conn.execute(
        "INSERT INTO corpus_documents (url, title, h1, body_text, built_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("https://prod.unicorniohater.com.br/quantos-anos-tem-o-loki/",
         "Quantos anos tem o Loki no MCU: idade do personagem", "Idade do Loki",
         "A idade do Loki de Tom Hiddleston e revelada no MCU.", "2026-09-21"))
    storage.conn.commit()

    medidas = build_query_semantic_signals(
        storage, "quantos anos tem loki",
        target_url="https://www.unicorniohater.com.br/quantos-anos-tem-o-loki/")
    assert medidas["semantic_scope"] == "target_url"
    assert medidas["semantic_match"] == "path_match"
    assert medidas["semantic_url"].startswith("https://prod.unicorniohater.com.br/")
    assert (medidas["semantic"]["title_fit"] or 0) > 0.8
    assert medidas["semantic"]["body_fit"] is not None
    storage.close()


def test_family_rankability_nao_faz_sql_de_traccao_por_variante(tmp_path):
    """Tração vem da família: nenhuma consulta a `query_pages` no caminho semântico."""
    from hermes_seo_agent.report.rankability_signals import build_family_query_signals

    storage = Storage(str(tmp_path / "sql.db"))
    url = "https://x/a"

    class _CountingConn:
        def __init__(self, conn):
            self._conn = conn
            self.sql: list[str] = []

        def execute(self, sql, params=()):
            self.sql.append(sql)
            return self._conn.execute(sql, params)

    rows = [_row("quantos anos tem gojo", 900, 9, 4.0), _row("gojo idade", 400, 4, 6.0)]
    family = build_families(rows)[0]
    counting = _CountingConn(storage.conn)
    proxy = type("P", (), {"conn": counting})()
    signals = build_family_query_signals(proxy, {"urls": [url]}, family, target_url=url)
    assert signals["impressions"] == 1300.0
    assert counting.sql, "deveria consultar o corpus"
    assert not any("query_pages" in sql for sql in counting.sql)
    assert all("corpus_" in sql for sql in counting.sql)
    storage.close()


def test_janela_desalinhada_derruba_review_title_para_investigate():
    """`signal_window.aligned=false` nunca permite `review_title` nem `high`."""
    rows = [_row("quantos anos tem gojo", 1760, 14, 4.8),
            _row("gojo poderes", 1510, 11, 5.4),
            _row("altura do gojo", 290, 3, 7.0)]
    share, _shares, coverage, relevant, candidates = _evidence(
        rows, "Gojo: poderes em Jujutsu Kaisen")
    verdict = {"verdict": "below_p10", "context": "5-10|imp2k+", "sample_size": 41,
               "bucket": {"p10": 0.01, "p50": 0.03}}
    headroom_detail = page_headroom(5.2, 31 / 4200, verdict)
    base: dict[str, Any] = dict(
        url="https://x/g", title="Gojo: poderes em Jujutsu Kaisen",
        page={"impressions": 4200, "clicks": 31, "position": 5.2, "entity": "Gojo"},
        baseline_verdict=verdict, families=share["families"], coverage=coverage,
        candidates=candidates,
        rankability={f["family"]: 0.8 for f in relevant},
        headroom_value=headroom_detail, ga4={"sessions": 340, "engagement_rate": 0.71})
    alinhado = decide_title(**base, signal_window_aligned=True)
    assert alinhado["decision"] == "review_title"
    assert alinhado["checks"]["signal_window_aligned"] is True

    desalinhado = decide_title(**base, signal_window_aligned=False)
    assert desalinhado["decision"] == "investigate_cause"
    assert desalinhado["confidence"] != "high"
    assert desalinhado["checks"]["signal_window_aligned"] is False
    assert any("janela dos sinais" in line for line in desalinhado["reason"])

    # não informado: compatível (nenhum gate novo aplicado)
    neutro = decide_title(**base, signal_window_aligned=None)
    assert neutro["decision"] == "review_title"
    assert neutro["checks"]["signal_window_aligned"] is None


def test_query_title_alignment_nao_confunde_franquias():
    """Entidade composta que só compartilha um token não é o mesmo assunto."""
    from hermes_seo_agent.report.query_families import (entity_alignment_score,
                                                        query_title_alignment)

    assert entity_alignment_score("dragon ball", "Dragon Quest") == 0.5
    assert entity_alignment_score("dragon ball", "Dragon Ball Z") == 1.0
    assert entity_alignment_score("gojo", "Satoru Gojo") == 1.0

    franquia_errada = query_title_alignment("dragon ball idade",
                                            "Dragon Quest: idade dos personagens")
    franquia_certa = query_title_alignment("dragon ball idade",
                                           "Dragon Ball: idade dos personagens")
    assert franquia_errada < 0.6
    assert franquia_certa > 0.8
    # entidade ausente do texto também é OUTRO assunto (teto 0.5), mesmo que a
    # intenção coincida
    outra = query_title_alignment("gojo poderes", "Naruto: poderes e tecnicas")
    assert outra <= 0.5


def test_related_top10_share_vem_do_cluster_e_move_o_rankability(tmp_path):
    """O refactor zerou 40% do observed_ease: o share é do CLUSTER, não da query."""
    import hermes_seo_agent.report.rankability_signals as rs

    storage = Storage(str(tmp_path / "share.db"))
    rows = [_row("quantos anos tem gojo", 900, 9, 4.0)]
    family = build_families(rows)[0]
    fraco = rs.build_family_query_signals(
        storage, {"positions": [15.0, 18.0, 20.0, 25.0]}, family,
        target_url="https://x/a")
    forte = rs.build_family_query_signals(
        storage, {"positions": [2.0, 4.0, 8.0, 15.0]}, family,
        target_url="https://x/a")
    assert fraco["related_top10_share"] == 0.0
    assert forte["related_top10_share"] == 0.75
    assert forte["related_top10_source"] == "cluster_positions"

    # mais related_top10_share -> observed_ease maior -> rankability nunca menor
    base = {"topic_authority": 0.4}
    r_fraco = family_rankability(family, query_signals={**base, **_ease_inputs(fraco)},
                                 cluster_signals={"positions": [15.0, 18.0, 20.0, 25.0]},
                                 title="Gojo: historia")
    r_forte = family_rankability(family, query_signals={**base, **_ease_inputs(forte)},
                                 cluster_signals={"positions": [2.0, 4.0, 8.0, 15.0]},
                                 title="Gojo: historia")
    assert (r_forte["factors"]["observed_ease"]["score"]
            > r_fraco["factors"]["observed_ease"]["score"])
    assert r_forte["score"] >= r_fraco["score"]
    storage.close()


def _ease_inputs(signals: dict[str, Any]) -> dict[str, Any]:
    return {"impressions": signals["impressions"], "clicks": signals["clicks"],
            "position": signals["position"],
            "related_top10_share": signals["related_top10_share"]}


def test_janela_desalinhada_conta_em_checks_passed_e_failed():
    """`aligned=false` precisa aparecer no veredito agregado (não só na decisão)."""
    rows = [_row("quantos anos tem gojo", 1760, 14, 4.8),
            _row("gojo poderes", 1510, 11, 5.4),
            _row("altura do gojo", 290, 3, 7.0)]
    share, _shares, coverage, relevant, candidates = _evidence(
        rows, "Gojo: poderes em Jujutsu Kaisen")
    verdict = {"verdict": "below_p10", "context": "5-10|imp2k+", "sample_size": 41,
               "bucket": {"p10": 0.01, "p50": 0.03}}
    base: dict[str, Any] = dict(
        url="https://x/g", title="Gojo: poderes em Jujutsu Kaisen",
        page={"impressions": 4200, "clicks": 31, "position": 5.2, "entity": "Gojo"},
        baseline_verdict=verdict, families=share["families"], coverage=coverage,
        candidates=candidates,
        rankability={f["family"]: 0.8 for f in relevant},
        headroom_value=page_headroom(5.2, 31 / 4200, verdict),
        ga4={"sessions": 340, "engagement_rate": 0.71})

    alinhado = decide_title(**base, signal_window_aligned=True)
    assert alinhado["checks"]["passed"] is True
    assert "signal_window_aligned" not in alinhado["checks"]["failed"]

    desalinhado = decide_title(**base, signal_window_aligned=False)
    assert desalinhado["checks"]["passed"] is False
    assert "signal_window_aligned" in desalinhado["checks"]["failed"]

    # não informado: veredito agregado como antes (sem o gate novo)
    neutro = decide_title(**base, signal_window_aligned=None)
    assert neutro["checks"]["passed"] is True
    assert "signal_window_aligned" not in neutro["checks"]["failed"]


def test_entity_preserved_usa_o_piso_unico_de_cobertura():
    from hermes_seo_agent.report.query_families import (ENTITY_OVERLAP_FLOOR,
                                                        compatible_entity,
                                                        entity_preserved)
    assert entity_preserved("Gojo", "Satoru Gojo") is True
    assert entity_preserved("Dragon Ball", "Dragon Ball Z") is True
    assert entity_preserved("Dragon Ball", "Dragon Quest") is False
    assert entity_preserved("Dragon Ball", "Dragon Quest: idade dos personagens") is False
    # sem entidade detectável não há violação (ausência não é falha)
    assert entity_preserved("", "qualquer titulo") is True
    # piso ÚNICO: o merge de família usa o mesmo valor
    assert ENTITY_OVERLAP_FLOOR == 0.6
    import inspect

    from hermes_seo_agent.report.query_families import compatible_entity as _ce
    assert inspect.signature(_ce).parameters["min_overlap"].default == ENTITY_OVERLAP_FLOOR
    assert compatible_entity("dragon ball", "Dragon Ball Z") is True


def test_entity_gate_valida_o_titulo_final_e_nao_a_phrase():
    """O gate tem de olhar o TEXTO final: o gerador pode reescrever a phrase."""
    from hermes_seo_agent.report.title_engine import title_gates

    base: dict[str, Any] = dict(
        page={"impressions": 4200, "clicks": 31, "position": 5.2},
        baseline_verdict={"verdict": "below_p10"}, ga4=None, confidence_score=0.8)
    coverage = {"observed_demand_coverage": 0.3}

    errado = title_gates(
        **base, families=[{"family_id": "dragon ball::idade", "intent": "idade",
                           "impressions": 900, "entity": "dragon ball", "share": 1.0}],
        coverage=coverage, entity="Dragon Ball",
        candidate={"phrase": "Dragon Ball: idade", "title": "Dragon Quest: idade",
                   "observed_demand_coverage": 1.0})
    assert errado["entity_preserved"] is False

    certo = title_gates(
        **base, families=[{"family_id": "dragon ball::idade", "intent": "idade",
                           "impressions": 900, "entity": "dragon ball", "share": 1.0}],
        coverage=coverage, entity="Dragon Ball",
        candidate={"phrase": "Dragon Ball: idade", "title": "Dragon Ball: idade",
                   "observed_demand_coverage": 1.0})
    assert certo["entity_preserved"] is True

    # sem título final cai para a phrase (compatível com chamadas antigas)
    so_phrase = title_gates(
        **base, families=[{"family_id": "dragon ball::idade", "intent": "idade",
                           "impressions": 900, "entity": "dragon ball", "share": 1.0}],
        coverage=coverage, entity="Dragon Ball",
        candidate={"phrase": "Dragon Ball: idade", "observed_demand_coverage": 1.0})
    assert so_phrase["entity_preserved"] is True


def test_validador_do_gerador_rejeita_entidade_de_outra_franquia():
    from hermes_seo_agent.report.title_generator import validate_candidate

    ruim = validate_candidate("Dragon Quest: idade dos personagens",
                              entity="Dragon Ball", evidence_intents=["idade"])
    assert ruim["ok"] is False
    assert "entidade_ausente" in ruim["violations"]

    # token compartilhado NÃO basta (era o falso positivo do "any token")
    parcial = validate_candidate("Dragon Quest: idade", entity="Dragon Ball",
                                 evidence_intents=["idade"])
    assert "entidade_ausente" in parcial["violations"]

    bom = validate_candidate("Dragon Ball: idade", entity="Dragon Ball",
                             evidence_intents=["idade"])
    assert "entidade_ausente" not in bom["violations"]
    assert bom["ok"] is True


def test_resolve_title_entity_prefere_a_canonica_e_mantem_os_fallbacks():
    """Canônica PLAUSÍVEL > entidade do título > família dominante."""
    from hermes_seo_agent.report.title_engine import resolve_title_entity

    longa = "Onde encontrar cada tabuleta de pedra em Dredge"
    familias = [{"entity_label": "Dredge", "entity": "dredge"}]
    # o corpus resolveu a entidade E ela é compatível com as queries: vence
    assert resolve_title_entity(longa, "Dredge", familias) == "Dredge"
    # sem canônica, cai para a entidade da página
    assert resolve_title_entity("Gojo", "", familias) == "Gojo"
    # sem página e sem canônica, usa a família dominante
    assert resolve_title_entity("", "", familias) == "Dredge"
    assert resolve_title_entity("   ", None, familias) == "Dredge"
    # nada disponível: string vazia (não inventa entidade)
    assert resolve_title_entity("", "", []) == ""
    # sem famílias observadas não há contradição: canônica com conteúdo serve
    assert resolve_title_entity(longa, "Dredge", []) == "Dredge"


def test_canonica_fragmentada_nao_vence_a_entidade_da_pagina():
    """Casos REAIS: 'melhores', 'fica' e 'hiddleston' não são a entidade."""
    from hermes_seo_agent.report.title_engine import resolve_title_entity

    # "melhores": stopword -> sem token significativo
    assert resolve_title_entity("Melhores arqueiros de anime", "melhores",
                                [{"entity": "anime usam arco flecha"}]) == \
        "Melhores arqueiros de anime"
    # "fica" (verbo) e "hiddleston" (o ator) NÃO pertencem ao assunto das queries
    assert resolve_title_entity("Animes de traicao em que o protagonista fica",
                                "fica",
                                [{"entity": "anime traido overpower"}]) == \
        "Animes de traicao em que o protagonista fica"
    assert resolve_title_entity("Quantos anos tem o Loki de Tom Hiddleston no MCU",
                                "hiddleston",
                                [{"entity": "loki"}, {"entity": "loki marvel"}]) == \
        "Quantos anos tem o Loki de Tom Hiddleston no MCU"
    # e a canônica que É o assunto das queries continua vencendo
    assert resolve_title_entity("Celestiais da Marvel vs Galactus", "celestiais",
                                [{"entity": "celestiais"}]) == "celestiais"


def test_entidade_canonica_evita_candidato_inviavel():
    """Título sem separador vira "entidade" gigante e mataria o candidato."""
    from hermes_seo_agent.report.title_engine import resolve_title_entity

    titulo = "Onde encontrar cada tabuleta de pedra em Dredge"
    rows = [_row("tabuletas dredge", 200), _row("onde encontrar tabuletas dredge", 150)]
    share, _shares, _coverage, relevant, _candidates = _evidence(rows, titulo)
    page_entity = titulo  # é o que `entity_of()` devolve sem ":" no título

    inviavel = combination_candidates(relevant, entity=page_entity, max_len=60,
                                      title_terms=tokens(titulo))
    assert not any(not c["discarded"] for c in inviavel), \
        "com a pseudo-entidade nenhum candidato deveria ser viável"
    assert {c["discard_reason"] for c in inviavel} & {"comprimento_inviavel",
                                                      "entidade_perdida"}

    entidade = resolve_title_entity(page_entity, "Dredge", relevant)
    assert entidade == "Dredge"
    viavel = combination_candidates(relevant, entity=entidade, max_len=60,
                                    title_terms=tokens(titulo))
    motivos = {c["discard_reason"] for c in viavel if c["discarded"]}
    # com a entidade canônica os descartes causados pela pseudo-entidade somem:
    # sobra no máximo a de-duplicação de termos já presentes no título atual
    # (`sem_termo_novo`), que é regra independente e legítima.
    assert not motivos & {"comprimento_inviavel", "entidade_perdida"}
    assert motivos <= {"sem_termo_novo"}
    assert all(c["phrase"].startswith("Dredge:") for c in viavel)
    assert all(entity_preserved(entidade, c["phrase"]) for c in viavel)


def test_resolve_title_entity_detail_registra_a_origem_real():
    """Origem vem do resolver, não de comparar strings (caso ambíguo)."""
    from hermes_seo_agent.report.title_engine import resolve_title_entity_detail

    # canônica REJEITADA que coincide textualmente com a página: a origem é a
    # página (antes a CLI inferia "canonical" só porque os textos batiam)
    ambiguo = resolve_title_entity_detail("Hiddleston", "Hiddleston",
                                          [{"entity": "loki"}])
    assert ambiguo["value"] == "Hiddleston"
    assert ambiguo["source"] == "page_entity"
    assert ambiguo["canonical_plausible"] is False
    assert isinstance(ambiguo["canonical_plausible"], bool)

    aceito = resolve_title_entity_detail("Celestiais da Marvel vs Galactus",
                                         "celestiais", [{"entity": "celestiais"}])
    assert aceito["source"] == "canonical"
    assert aceito["canonical_plausible"] is True

    # sem página e sem canônica: origem família
    por_familia = resolve_title_entity_detail("", "", [{"entity": "loki",
                                                        "entity_label": "Loki"}])
    assert por_familia["value"] == "Loki"
    assert por_familia["source"] == "family"
    assert por_familia["canonical_plausible"] is False

    vazio = resolve_title_entity_detail("", "", [])
    assert vazio["value"] == "" and vazio["source"] == "family"


def test_demand_share_preserva_o_entity_label_da_familia():
    """O rótulo legível (forma da query) sobrevive ao demand share."""
    rows = [_row("Gojo Satoru idade", 900)]
    familia = demand_share(build_families(rows))["families"][0]
    assert familia["entity"] == "gojo satoru"          # normalizada (comparação)
    assert familia["entity_label"] == "Gojo Satoru"     # legível (título)
    assert familia["entity_label"] != familia["entity"]


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
