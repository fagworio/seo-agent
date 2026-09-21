"""Guard determinístico de IDIOMA × FIDELIDADE do relatório (prosa × evidência).

Incidente que motivou (2026-09-21): o relatório do agente citou o campo real
``rank_math_title`` como ``Sony: 的 PlayStation 光盘工厂转型为微透镜``, enquanto o
valor no WordPress é ``Sony: fábrica de discos do PlayStation vira microlentes``.
Nada foi escrito no WordPress (sem dano editorial), mas o relatório deixou de ser
uma representação fiel do estado do sistema — quem opera passaria a decidir com
dado falso. É um problema de observabilidade/fidelidade, não de estilo.

Contrato verificado aqui, sem LLM e sem tokens:

  ``narrative``  -> PROSA em pt-BR: nenhum caractere CJK/coreano SOBRANDO. Os
                    valores literais de ferramenta que a prosa CITA são removidos
                    antes da checagem (um título legítimo em outra escrita é dado
                    de origem, não prosa do agente);
  ``evidence``   -> DADOS LITERAIS: campo esperado presente e igual byte a byte;
  ``citação``    -> o valor esperado aparece na PROSA exatamente como veio (não
                    pode ser traduzido, resumido, "corrigido" nem reformatado).
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Sequence

# Faixas de escrita CJK/coreana. Um caractere aqui SOBRANDO na prosa é violação;
# dentro de um VALOR de evidência é dado literal (permitido e preservado).
CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs
    (0x3400, 0x4DBF),    # CJK Extension A
    (0x20000, 0x2A6DF),  # CJK Extension B (raros, mas aparecem em títulos)
    (0x3040, 0x30FF),    # Hiragana + Katakana
    (0xAC00, 0xD7AF),    # Hangul Syllables
    (0x1100, 0x11FF),    # Hangul Jamo
    (0xFF00, 0xFFEF),    # Fullwidth forms (inclui pontuação CJK)
    (0x3000, 0x303F),    # pontuação CJK (。、「」等)
)

NARRATIVE_REQUIRED_KEYS = ("narrative",)


def cjk_characters(text: str) -> list[str]:
    """Caracteres CJK/coreanos presentes no texto, sem repetição e em ordem."""
    seen: list[str] = []
    for char in str(text or ""):
        code = ord(char)
        if any(start <= code <= end for start, end in CJK_RANGES):
            if char not in seen:
                seen.append(char)
    return seen


def has_cjk(text: str) -> bool:
    return bool(cjk_characters(text))


def strip_allowed_literals(text: str, literals: Iterable[str]) -> str:
    """Remove da prosa os valores literais citados (dado de origem, não prosa).

    É o que permite um `post_title` legítimo em outra escrita sem liberar o
    agente a escrever prosa em CJK: se o texto em CJK NÃO for exatamente um valor
    de ferramenta, ele permanece no resíduo e é acusado.
    """
    residue = str(text or "")
    for literal in literals:
        value = str(literal or "")
        if value:
            residue = residue.replace(value, " ")
    return residue


def _payload_text(report: Mapping[str, Any]) -> str:
    """Serialização estável do relatório para busca byte a byte."""
    return json.dumps(report, ensure_ascii=False, sort_keys=True, default=str)


def check_narrative_locale(narrative: str, *,
                           allowed_literals: Iterable[str] = ()) -> list[str]:
    """A PROSA (sem os literais citados) está livre de escrita CJK/coreana?"""
    residue = strip_allowed_literals(narrative, allowed_literals)
    offenders = cjk_characters(residue)
    if offenders:
        return [f"prosa_com_cjk:{''.join(offenders)}"]
    return []


def check_expected_fields(report: Mapping[str, Any],
                          expected: Mapping[str, Any] | None) -> list[str]:
    """Campos esperados: presentes, iguais byte a byte E citados literalmente.

    Byte a byte: acento, caixa, pontuação e ordem das palavras contam. Traduzir,
    resumir ou "melhorar" um valor de ferramenta é violação — mesmo que o texto
    resultante pareça mais adequado ao idioma da resposta.
    """
    violations: list[str] = []
    narrative = str(report.get("narrative") or "")
    evidence = dict(report.get("evidence") or {})
    for key, value in (expected or {}).items():
        text = str(value or "")
        if not text:
            continue
        if key not in evidence:
            violations.append(f"campo_ausente:{key}")
        elif str(evidence.get(key) or "") != text:
            violations.append(f"valor_alterado:{key}")
        if text not in narrative:
            violations.append(f"valor_nao_citado:{key}")
    return violations


def check_literal_values(report: Mapping[str, Any],
                         values: Sequence[str] | None) -> list[str]:
    """Valores soltos (sem campo): precisam aparecer literais em algum lugar."""
    payload = _payload_text(report)
    return [f"valor_nao_literal:{value}" for value in (values or ())
            if str(value or "").strip() and str(value) not in payload]


def check_evidence_verbatim(report: Mapping[str, Any],
                            expected: Mapping[str, Any] | None = None,
                            *, values: Sequence[str] | None = None) -> list[str]:
    """Composição dos dois níveis de fidelidade (campos + valores soltos)."""
    return (check_expected_fields(report, expected)
            + check_literal_values(report, values))


def validate_report(report: Mapping[str, Any], *,
                    expected: Mapping[str, Any] | None = None,
                    values: Sequence[str] | None = None) -> dict[str, Any]:
    """Valida o relatório: prosa pt-BR + evidência literal e citada.

    ``report`` = {"narrative": "<prosa pt-BR>", "evidence": {campo: valor}}.
    ``expected`` = valores de ferramenta que o relatório DEVE carregar e citar
    literais. ``values`` = literais que precisam aparecer no payload (sem campo).
    """
    narrative = str(report.get("narrative") or "")
    missing = [key for key in NARRATIVE_REQUIRED_KEYS if key not in report]
    violations: list[str] = [f"campo_ausente:{key}" for key in missing]
    if not narrative.strip():
        violations.append("prosa_vazia")
    literals = [str(v) for v in (expected or {}).values() if str(v or "").strip()]
    literals += [str(v) for v in (values or ()) if str(v or "").strip()]
    violations += check_narrative_locale(narrative, allowed_literals=literals)
    violations += check_evidence_verbatim(report, expected, values=values)
    evidence_fields_with_cjk = [key for key, value in (report.get("evidence") or {}).items()
                                if has_cjk(str(value or ""))]
    checks = {
        "narrative_present": bool(narrative.strip()),
        "narrative_pt_br": not cjk_characters(strip_allowed_literals(narrative, literals)),
        "evidence_verbatim": not any(v.startswith(("valor_alterado", "valor_nao_citado",
                                                   "valor_nao_literal"))
                                     for v in violations),
        "evidence_fields_with_cjk": evidence_fields_with_cjk,
        "quoted_literals": len(literals),
    }
    instruction = ""
    if violations:
        instruction = (
            "Reescreva SOMENTE a prosa (narrative) em português do Brasil e "
            "reproduza os valores de evidência exatamente como vieram das "
            "ferramentas (sem traduzir, resumir, corrigir acento/caixa ou "
            "reformatar). Revalide com o guard antes de enviar.")
    return {
        "ok": not violations,
        "violations": violations,
        "checks": checks,
        "retry_instruction": instruction,
        "cjk_in_narrative": cjk_characters(strip_allowed_literals(narrative, literals)),
    }


def build_draft(narrative: str, evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Monta o rascunho no formato aceito por :func:`validate_report`."""
    return {"narrative": str(narrative or ""), "evidence": dict(evidence or {})}
