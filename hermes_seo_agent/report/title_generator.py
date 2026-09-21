"""FASE 15–16 — Gerador determinístico de título + LLM OPCIONAL (só redação).

A decisão (se altera, qual família, qual combinação, qual score) já foi tomada
pelo motor determinístico. Aqui só nascem as OPÇÕES de redação:

  * ``deterministic`` (padrão): templates + validador. Nenhum token gasto.
  * ``hybrid``: o LLM recebe um BRIEFING ESTRUTURADO (intenções já escolhidas,
    restrições e evidência) e devolve texto; o validador determinístico decide
    se o texto pode ser usado. A LLM nunca decide se altera, qual demanda
    existe, qual intenção é prioritária ou qual query vale.

Sem writer injetado não há chamada nenhuma: este módulo não importa provider de
LLM (o chamador passa ``writer``). Assim a análise continua 100% livre de
tokens, como exige o roadmap.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Sequence

from .query_families import (INTENT_TITLE_PHRASES, entity_preserved, expand_variants,
                             fold, intent_phrases, tokens)
from .title_engine import DEFAULT_MAX_LEN, MAX_SIGNIFICANT_TERMS

MODE_DETERMINISTIC = "deterministic"
MODE_HYBRID = "hybrid"
GENERATION_MODES = (MODE_DETERMINISTIC, MODE_HYBRID)

TEMPLATES: tuple[str, ...] = (
    "{entity}: {primary}",
    "{entity}: {primary} e {secondary}",
    # TRIO: sem um template de terceira intenção o motor podia pontuar uma
    # combinação de 3 e não ter como representá-la no título (FASE 7/15).
    "{entity}: {primary}, {secondary} e {tertiary}",
    "{primary} de {entity}",
    "{entity}: {primary} em {context}",
)

_PREPOSITIONS = {"a", "o", "os", "as", "de", "da", "do", "das", "dos", "e", "em",
                 "no", "na", "nos", "nas", "para", "com", "que", "por", "the",
                 "of", "and", "in", "to", "até"}
_TRUNCATION_MARKS = ("…", "...")
_NUMBER_RE = re.compile(r"\d+")


def phrase_for(intent: str) -> str:
    return INTENT_TITLE_PHRASES.get(intent, intent.replace("_", " "))


def _numbers(text: str) -> set[str]:
    return set(_NUMBER_RE.findall(str(text or "")))


def validate_candidate(
    title: str,
    *,
    entity: str = "",
    evidence_intents: Iterable[str] = (),
    current_title: str = "",
    evidence_numbers: Iterable[str] | None = None,
    max_len: int = DEFAULT_MAX_LEN,
    max_terms: int = MAX_SIGNIFICANT_TERMS,
) -> dict[str, Any]:
    """Validador determinístico das RESTRIÇÕES da FASE 15.

    Preserva entidade, limite configurável, não termina em preposição, não
    duplica palavra significativa, não introduz intenção sem evidência, não
    inventa número, não trunca frase no meio e não faz keyword stuffing.
    """
    clean = re.sub(r"\s+", " ", str(title or "").strip())
    violations: list[str] = []
    if not clean:
        return {"ok": False, "violations": ["titulo_vazio"], "title": ""}
    if len(clean) > int(max_len):
        violations.append(f"acima_do_limite({len(clean)}>{max_len})")

    title_variants = expand_variants(tokens(clean))
    if entity and not entity_preserved(entity, clean):
        # piso único de cobertura de entidade: "dragon" em "Dragon Quest" NÃO
        # preserva a entidade "Dragon Ball" (antes bastava qualquer token).
        violations.append("entidade_ausente")

    # intenção sem evidência: palavras de intenção no título precisam estar no
    # conjunto de evidência (ou já existirem no título atual — nesse caso não é
    # introdução, é preservação).
    allowed = set(evidence_intents or ())
    current_variants = expand_variants(tokens(current_title))
    current_labels = {label for label in INTENT_TITLE_PHRASES
                      if _phrase_in(label, current_variants)}
    for label in INTENT_TITLE_PHRASES:
        if label in allowed or label in current_labels:
            continue
        if _phrase_in(label, title_variants):
            violations.append(f"intencao_sem_evidencia:{label}")

    # números inexistentes (nunca inventar dado factual)
    known = _numbers(current_title) | {str(n) for n in (evidence_numbers or [])}
    invented = sorted(_numbers(clean) - known)
    if invented:
        violations.append("numero_inventado:" + ",".join(invented))

    words = clean.split()
    if any(mark in clean for mark in _TRUNCATION_MARKS):
        violations.append("frase_truncada")
    if words and fold(words[-1]).strip(".,!?;:") in _PREPOSITIONS:
        violations.append("termina_em_preposicao")

    significant = [t for t in tokens(clean) if t not in _PREPOSITIONS and len(t) > 2]
    duplicates = sorted({t for t in significant if significant.count(t) > 1})
    if duplicates:
        violations.append("palavra_duplicada:" + ",".join(duplicates))
    if len(set(significant)) > int(max_terms):
        violations.append("keyword_stuffing")

    if current_title and fold(clean) == fold(current_title):
        violations.append("igual_ao_titulo_atual")

    return {"ok": not violations, "violations": violations, "title": clean}


def _phrase_in(label: str, title_variants: set[str]) -> bool:
    phrases = [p for p in intent_phrases(label) if " " not in p] or list(intent_phrases(label))
    for phrase in phrases:
        terms = tokens(phrase)
        if terms and all(expand_variants([t]) & title_variants for t in terms):
            return True
    return False


def build_brief(*, entity: str, intents: Sequence[str], context: str = "",
                current_title: str = "", evidence: dict[str, Any] | None = None,
                max_len: int = DEFAULT_MAX_LEN) -> dict[str, Any]:
    """Briefing ESTRUTURADO do modo hybrid (a LLM não decide nada — só redige)."""
    return {
        "task": "redigir opções de <title> em pt-BR",
        "entity": entity,
        "intents": list(intents),
        "intent_phrases": [phrase_for(i) for i in intents],
        "context": context,
        "current_title": current_title,
        "max_length": int(max_len),
        "must_keep": ["entidade", "as intenções listadas"],
        "must_not": [
            "inventar números, datas ou fatos",
            "introduzir intenção sem evidência",
            "terminar em preposição",
            "repetir palavra significativa",
            "keyword stuffing",
            "truncar frase no meio",
        ],
        "evidence": dict(evidence or {}),
    }


def generate_candidates(
    *,
    entity: str,
    candidate: dict[str, Any] | None,
    context: str = "",
    current_title: str = "",
    evidence_intents: Iterable[str] = (),
    evidence_numbers: Iterable[str] | None = None,
    max_len: int = DEFAULT_MAX_LEN,
    mode: str = MODE_DETERMINISTIC,
    writer: Callable[[dict[str, Any]], Any] | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Opções de título determinísticas (e, opcionalmente, redigidas por LLM).

    Retorna {mode, brief, llm_used, candidates[], discarded[]}.
    """
    mode = (mode or MODE_DETERMINISTIC).lower()
    if mode not in GENERATION_MODES:
        mode = MODE_DETERMINISTIC
    intents = [str(i) for i in ((candidate or {}).get("intents") or [])]
    brief = build_brief(entity=entity, intents=intents, context=context,
                        current_title=current_title, evidence=evidence,
                        max_len=max_len)

    out: list[dict[str, Any]] = []
    if candidate:
        primary = phrase_for(intents[0]) if intents else ""
        secondary = phrase_for(intents[1]) if len(intents) > 1 else ""
        tertiary = phrase_for(intents[2]) if len(intents) > 2 else ""
        values = {
            "entity": entity,
            "primary": primary,
            "secondary": secondary,
            "tertiary": tertiary,
            "context": context,
        }
        for template in TEMPLATES:
            needed = re.findall(r"\{(\w+)\}", template)
            if any(not values.get(name) for name in needed):
                continue
            title = template.format(**values)
            check = validate_candidate(
                title, entity=entity, evidence_intents=intents,
                current_title=current_title, evidence_numbers=evidence_numbers,
                max_len=max_len)
            out.append({"title": check["title"], "template": template,
                        "intents": intents, "source": MODE_DETERMINISTIC,
                        "validation": check})

    llm_used = False
    if mode == MODE_HYBRID and callable(writer):
        llm_used = True
        try:
            produced = writer(brief) or []
        except Exception:  # noqa: BLE001 - redação opcional nunca derruba o run
            produced = []
        if isinstance(produced, str):
            produced = [produced]
        for text in produced:
            check = validate_candidate(
                str(text), entity=entity, evidence_intents=intents,
                current_title=current_title, evidence_numbers=evidence_numbers,
                max_len=max_len)
            out.append({"title": check["title"], "template": "llm",
                        "intents": intents, "source": MODE_HYBRID,
                        "validation": check})

    valid: list[dict[str, Any]] = []
    discarded: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in out:
        key = fold(item["title"])
        if key in seen:
            continue
        seen.add(key)
        (valid if item["validation"]["ok"] else discarded).append(item)
    valid.sort(key=lambda item: (len(item["title"]), item["template"]))
    return {
        "mode": mode,
        "brief": brief,
        "llm_used": llm_used,
        "candidates": valid,
        "discarded": discarded,
    }
