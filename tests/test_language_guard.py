"""Guard de idioma × fidelidade do relatório (incidente Sony/PlayStation).

O relatório citou ``rank_math_title`` como

    Sony: 的 PlayStation 光盘工厂转型为微透镜

quando o valor real no WordPress é

    Sony: fábrica de discos do PlayStation vira microlentes

Nada foi escrito no WordPress — o dano foi de OBSERVABILIDADE: o relatório deixou
de representar o estado real do sistema. Estes testes fixam as duas propriedades
que importam: a prosa é pt-BR E os valores de ferramenta vêm literais.
"""
from __future__ import annotations

from hermes_seo_agent.report.language_guard import (CJK_RANGES, build_draft,
                                                    cjk_characters, has_cjk,
                                                    validate_report)

TITULO_REAL = "Sony: fábrica de discos do PlayStation vira microlentes"
TITULO_TRADUZIDO = "Sony: 的 PlayStation 光盘工厂转型为微透镜"


def _relatorio_valido():
    return build_draft(
        narrative=(f"*SEO UPDATE — Post #4821*\n"
                   f'Título corrigido: "{TITULO_REAL}"\n'
                   "Status: AGUARDANDO DADOS\n"
                   "Baseline: posição 4,1 | 1.240 impressões | CTR 0,8%."),
        evidence={"rank_math_title": TITULO_REAL, "post_id": 4821,
                  "slug": "sony-playstation-microlentes"})


# --- o incidente, exatamente -------------------------------------------------

def test_incidente_sony_prosa_pt_br_e_titulo_literal():
    report = _relatorio_valido()
    verdict = validate_report(report, expected={"rank_math_title": TITULO_REAL})
    assert verdict["ok"] is True
    assert verdict["violations"] == []
    assert verdict["checks"]["narrative_pt_br"] is True
    # a propriedade central: o título aparece EXATAMENTE como veio da ferramenta
    assert TITULO_REAL in report["narrative"]


def test_titulo_traduzido_na_prosa_e_rejeitado():
    """Traduzir a evidência é violação — mesmo 'parecendo' adequado ao idioma."""
    report = build_draft(
        narrative=(f"*SEO UPDATE — Post #4821*\n"
                   f'Título corrigido: "{TITULO_TRADUZIDO}"\nStatus: AGUARDANDO DADOS'),
        evidence={"rank_math_title": TITULO_REAL})
    verdict = validate_report(report, expected={"rank_math_title": TITULO_REAL})
    assert verdict["ok"] is False
    assert "valor_nao_citado:rank_math_title" in verdict["violations"]
    assert verdict["cjk_in_narrative"]
    assert verdict["checks"]["narrative_pt_br"] is False
    assert verdict["retry_instruction"], "precisa instruir a reescrita da prosa"


def test_evidencia_alterada_em_arquivo_e_rejeitada():
    """Resumir/reescrever o valor no bloco de evidência também é violação."""
    report = build_draft(narrative="Tudo certo por aqui.",
                         evidence={"rank_math_title": "Sony: fábrica de discos vira microlentes"})
    verdict = validate_report(report, expected={"rank_math_title": TITULO_REAL})
    assert verdict["ok"] is False
    assert "valor_alterado:rank_math_title" in verdict["violations"]
    assert "valor_nao_citado:rank_math_title" in verdict["violations"]


def test_acento_caixa_e_pontuacao_contam():
    for errado in ("Sony: fabrica de discos do PlayStation vira microlentes",
                   "sony: fábrica de discos do PlayStation vira microlentes",
                   "Sony: fábrica de discos do PlayStation vira microlentes."):
        verdict = validate_report(
            build_draft("Relatório do ciclo.",
                        evidence={"rank_math_title": errado}),
            expected={"rank_math_title": TITULO_REAL})
        assert verdict["ok"] is False, errado
        assert "valor_alterado:rank_math_title" in verdict["violations"]


# --- escopo: CJK na EVIDÊNCIA é dado legítimo -------------------------------

def test_cjk_em_valor_de_evidencia_e_permitido():
    """Título/valor legítimo em outra escrita não pode ser bloqueado."""
    titulo_cn = "原神：版本更新时间"
    report = build_draft(
        narrative=(f'*SEO UPDATE — Post #77*\nTítulo corrigido: "{titulo_cn}"\n'
                   "Status: AGUARDANDO DADOS"),
        evidence={"rank_math_title": titulo_cn})
    verdict = validate_report(report, expected={"rank_math_title": titulo_cn})
    # o valor literal carrega CJK: permitido; o que não pode é a PROSA ter CJK
    assert verdict["checks"]["evidence_fields_with_cjk"] == ["rank_math_title"]
    assert verdict["ok"] is True


def test_cjk_na_prosa_e_violacao_mesmo_com_evidencia_correta():
    report = build_draft(
        narrative=(f'*SEO UPDATE*\nTítulo corrigido: "{TITULO_REAL}"\n'
                   "Observação 中文 adicionada pelo agente."),
        evidence={"rank_math_title": TITULO_REAL})
    verdict = validate_report(report, expected={"rank_math_title": TITULO_REAL})
    assert verdict["ok"] is False
    assert verdict["checks"]["evidence_verbatim"] is True
    assert verdict["checks"]["narrative_pt_br"] is False


# --- campos e valores ------------------------------------------------------

def test_campo_esperado_ausente_e_violacao():
    report = build_draft("Relatório sem o id.", evidence={"rank_math_title": TITULO_REAL})
    verdict = validate_report(report, expected={"rank_math_title": TITULO_REAL,
                                                "post_id": 4821})
    assert verdict["ok"] is False
    assert "campo_ausente:post_id" in verdict["violations"]


def test_valores_soltos_via_values():
    report = build_draft("Ciclo ok.", evidence={"slug": "sony-microlentes"})
    verdict = validate_report(report, values=["sony-microlentes"])
    assert verdict["ok"] is True
    quebrado = validate_report(build_draft("Ciclo ok.", evidence={}),
                               values=["sony-microlentes"])
    assert quebrado["ok"] is False


def test_relatorio_sem_prosa_e_violacao():
    verdict = validate_report({"narrative": "", "evidence": {}})
    assert verdict["ok"] is False
    assert verdict["checks"]["narrative_present"] is False


# --- utilidades -------------------------------------------------------------

def test_deteccao_de_cjk_por_faixa():
    assert has_cjk("光盘工厂") is True
    assert has_cjk("マイクロレンズ") is True
    assert has_cjk("미세 렌즈") is True
    assert has_cjk("Sony: fábrica de discos") is False
    assert cjk_characters("a光b光c") == ["光"]
    assert len(CJK_RANGES) >= 4
