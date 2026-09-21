"""FASE 19 — gerador determinístico (F15) e LLM opcional só como redator (F16)."""

from __future__ import annotations

from hermes_seo_agent.report.query_families import build_families, demand_share
from hermes_seo_agent.report.title_engine import (combination_candidates,
                                                 relevant_families)
from hermes_seo_agent.report.title_generator import (
    MODE_DETERMINISTIC, MODE_HYBRID, generate_candidates, validate_candidate,
)


def _row(query, impressions, clicks=0, position=5.0):
    return {"keys": [query], "impressions": impressions, "clicks": clicks,
            "position": position, "ctr": (clicks / impressions) if impressions else 0.0}


def _candidate(intents=("idade", "poderes")):
    # idade com o MAIOR share: a ordem das intenções do candidato é a ordem da
    # demanda observada (determinística), não a do dicionário.
    families = build_families([_row("quantos anos tem gojo", 900),
                              _row("gojo poderes", 500)])
    share = demand_share(families)
    cands = combination_candidates(relevant_families(share), entity="Gojo")
    best = max((c for c in cands if not c["discarded"]),
               key=lambda c: c["observed_demand_coverage"])
    return best


# --- FASE 15: templates ----------------------------------------------------

def test_gera_opcoes_por_template_preservando_entidade():
    result = generate_candidates(entity="Gojo", candidate=_candidate(),
                                 current_title="Gojo: historia", max_len=60)
    assert result["mode"] == MODE_DETERMINISTIC
    assert result["llm_used"] is False
    titles = [c["title"] for c in result["candidates"]]
    assert titles, "nenhuma opção válida gerada"
    assert all("Gojo" in t for t in titles)
    assert any(t == "Gojo: idade" for t in titles)
    assert any(t == "Gojo: idade e poderes" for t in titles)
    assert any(t == "idade de Gojo" for t in titles)
    assert all(c["validation"]["ok"] for c in result["candidates"])


def test_templates_ignoram_entrada_sem_evidencia():
    result = generate_candidates(entity="Gojo", candidate=None,
                                 current_title="Gojo: historia")
    assert result["candidates"] == []


def test_validador_recusa_terminar_em_preposicao():
    check = validate_candidate("Gojo: idade de", entity="Gojo",
                               evidence_intents=["idade"])
    assert check["ok"] is False
    assert "termina_em_preposicao" in check["violations"]


def test_validador_recusa_palavra_repetida_e_stuffing():
    repeated = validate_candidate("Gojo: idade e idade dos anos",
                                  entity="Gojo", evidence_intents=["idade"])
    assert "palavra_duplicada:idade" in repeated["violations"]
    stuffed = validate_candidate(
        "Gojo: idade altura morte elenco poderes ordem preco estreia final",
        entity="Gojo",
        evidence_intents=["idade", "altura", "morte", "elenco", "poderes",
                          "ordem", "preco", "estreia", "final"])
    assert "keyword_stuffing" in stuffed["violations"]


def test_validador_recusa_intencao_sem_evidencia():
    check = validate_candidate("Gojo: idade e preço", entity="Gojo",
                               evidence_intents=["idade"])
    assert "intencao_sem_evidencia:preco" in check["violations"]
    # intenção já presente no título atual não é introdução: é preservação
    kept = validate_candidate("Gojo: idade e preço", entity="Gojo",
                              evidence_intents=["idade"],
                              current_title="Gojo: preço e historia")
    assert "intencao_sem_evidencia:preco" not in kept["violations"]


def test_validador_recusa_numero_inventado_e_truncamento():
    invented = validate_candidate("Gojo: 1990 idade", entity="Gojo",
                                  evidence_intents=["idade"], current_title="Gojo")
    assert "numero_inventado:1990" in invented["violations"]
    truncado = validate_candidate("Gojo: idade e poderes…", entity="Gojo",
                                  evidence_intents=["idade", "poderes"])
    assert "frase_truncada" in truncado["violations"]


def test_validador_respeita_limite_configuravel():
    check = validate_candidate("Gojo: idade e poderes de todo o universo conhecido",
                               entity="Gojo", evidence_intents=["idade", "poderes"],
                               max_len=20)
    assert any(v.startswith("acima_do_limite") for v in check["violations"])


# --- FASE 16: LLM opcional ------------------------------------------------

def test_modo_deterministico_nunca_chama_writer():
    called = {"n": 0}

    def writer(_brief):
        called["n"] += 1
        return ["Gojo: idade"]

    result = generate_candidates(entity="Gojo", candidate=_candidate(),
                                 current_title="Gojo: historia",
                                 mode=MODE_DETERMINISTIC, writer=writer)
    assert called["n"] == 0
    assert result["llm_used"] is False


def test_modo_hybrid_usa_writer_e_valida_a_redacao():
    briefs: list[dict] = []

    def writer(brief):
        briefs.append(brief)
        return ["Idade de Gojo e seus poderes", "Gojo: idade de"]  # 1 válido, 1 inválido

    result = generate_candidates(
        entity="Gojo", candidate=_candidate(), current_title="Gojo: historia",
        evidence_intents=["idade", "poderes"], mode=MODE_HYBRID, writer=writer)
    assert result["llm_used"] is True
    assert briefs and briefs[0]["entity"] == "Gojo"
    # o briefing estruturado carrega as decisões JÁ tomadas (a LLM não decide)
    assert briefs[0]["intents"] == ["idade", "poderes"]
    assert "must_not" in briefs[0]
    llm_valid = [c for c in result["candidates"] if c["template"] == "llm"]
    assert [c["title"] for c in llm_valid] == ["Idade de Gojo e seus poderes"]
    # redação inválida é DESCARTADA (nunca publicada)
    discarded = [c["title"] for c in result["discarded"] if c["template"] == "llm"]
    assert discarded == ["Gojo: idade de"]
    # mesmo no modo hybrid o determinístico continua disponível (fallback)
    assert any(c["template"] != "llm" for c in result["candidates"])


def test_writer_que_falha_nao_derruba_o_run():
    def writer(_brief):
        raise RuntimeError("provider fora do ar")

    result = generate_candidates(entity="Gojo", candidate=_candidate(),
                                 current_title="Gojo: historia",
                                 mode=MODE_HYBRID, writer=writer)
    assert result["candidates"], "o determinístico deve continuar valendo"
    assert result["llm_used"] is True
