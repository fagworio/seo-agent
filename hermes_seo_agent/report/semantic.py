"""M7 — Semântica leve e híbrida (determinística, sem IA obrigatória).

Evolui a correspondência puramente lexical/FTS do corpus para capturar
INTENÇÃO:

  * expansão de consulta: aliases de franquias (topics.py), normalização de
    acentos/plural, formas perguntativas (ex.: "idade do luffy" →
    "luffy idade", "quantos anos tem o luffy");
  * busca híbrida: FTS5 na consulta + FTS5 nas expansões + matching por
    entidade (M3) + coocorrência em títulos/H2/seções;
  * cada resultado explica POR QUE casou (termos expandidos, entidade,
    seção) — nada de caixa-preta.

Critério M7: o editor entende por que a sugestão é "expandir esta URL" em
vez de "criar outro post parecido" — porque o corpus encontra a SEÇÃO que
já cobre a intenção mesmo com vocabulário diferente.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from .topics import ENTITY_ALIASES, canonical_entity, normalize_entity

# formas perguntativas -> termo curto (para expansão de consulta)
_QUESTION_VERBS = {
    "quanto", "quantos", "qual", "quais", "quem", "como", "quando", "onde",
    "por que", "porque", "o que", "que", "tem", "tem o", "são", "é", "sao",
    "e", "será", "sera", "a", "o", "as", "os", "de", "do", "da", "dos",
    "das", "em", "no", "na", "para", "pra",
}
# sufixos de singular/plural a considerar equivalentes
_PLURAL_SUFFIXES = ("s", "es", "ns", "is", "ões", "oes", "ais")

# sinônimos leves por domínio (determinísticos, adicionar conforme o acervo)
_DOMAIN_SYNONYMS: dict[str, str] = {
    "personagem": "personagens",
    "personagens": "personagem",
    "idade": "anos",
    "anos": "idade",
    "poderes": "habilidades",
    "habilidades": "poderes",
    "temporada": "episódios",
    "episódios": "temporada",
}


def expand_query(keyword: str, *, max_variants: int = 12) -> list[str]:
    """Gera variantes de busca para a consulta (determinístico).

    Inclui: a consulta original, a forma normalizada, aliases de franquias
    (tanto o alias quanto o target canônico), forma perguntativa encurtada,
    pares significativos, sinônimos de domínio e singular/plural. Sem IA.
    """
    kw = (keyword or "").strip()
    if not kw:
        return []
    variants: list[str] = [kw]
    seen = {_norm(kw)}

    norm = normalize_entity(kw)  # minúsculas, sem acento
    if norm and _norm(norm) not in seen:
        variants.append(norm)
        seen.add(_norm(norm))

    # aliases: se a consulta É um alias, adiciona o target canônico; se contém
    # o canônico, adiciona os aliases conhecidos.
    canon = canonical_entity(kw)
    if canon != norm:
        variants.append(canon)
        seen.add(_norm(canon))
    elif canon == norm and canon in ENTITY_ALIASES.values():
        for alias in ENTITY_ALIASES:
            if ENTITY_ALIASES[alias] == canon and _norm(alias) not in seen:
                variants.append(alias)
                seen.add(_norm(alias))

    # sinônimos de domínio aplicados ANTES de gerar pares (ex.: anos -> idade)
    synonymized = norm
    for word, synonym in _DOMAIN_SYNONYMS.items():
        synonymized = synonymized.replace(word, synonym)
    if synonymized != norm and _norm(synonymized) not in seen:
        variants.append(synonymized)
        seen.add(_norm(synonymized))

    # forma perguntativa -> termos principais (remove verbos de pergunta)
    words = [w for w in norm.split() if w not in _QUESTION_VERBS]
    words_syn = [w for w in synonymized.split() if w not in _QUESTION_VERBS]
    if len(words) >= 2:
        shortened = " ".join(words)
        if _norm(shortened) not in seen:
            variants.append(shortened)
            seen.add(_norm(shortened))
        # pares significativos adjacentes (ex.: "luffy idade")
        for i in range(len(words) - 1):
            pair = f"{words[i]} {words[i + 1]}"
            if _norm(pair) not in seen:
                variants.append(pair)
                seen.add(_norm(pair))
        # par da última palavra com a primeira palavra de conteúdo
        # (ex.: "luffy anos" de "quantos anos tem o luffy")
        first = words_syn[0] if words_syn else words[0]
        last = words[-1]
        rev = f"{last} {first}"
        if _norm(rev) not in seen and last != first:
            variants.append(rev)
            seen.add(_norm(rev))

    # singular/plural alternativo da última palavra significativa
    if words:
        last = words[-1]
        for suffix in _PLURAL_SUFFIXES:
            if last.endswith(suffix):
                alt_last = last[: -len(suffix)]
                if len(alt_last) >= 3:
                    alt = f"{' '.join(words[:-1])} {alt_last}".strip()
                    if _norm(alt) not in seen:
                        variants.append(alt)
                        seen.add(_norm(alt))
                break

    return variants[:max_variants]


def hybrid_search(storage: Any, keyword: str, *, limit: int = 10
                  ) -> list[dict[str, Any]]:
    """Busca híbrida: FTS na consulta + FTS nas expansões + entidade + seção.

    Retorna docs com score explicado:
      {url, title, snippet, semantic_score, matched_variants, via}
    """
    variants = expand_query(keyword)
    # FTS por variante (BM25), acumulando docs
    scores: dict[str, dict[str, Any]] = {}
    for variant in variants:
        for doc in storage.corpus_search(variant, limit=20):
            url = doc["url"]
            entry = scores.setdefault(url, {
                "url": url, "title": doc.get("title", ""),
                "snippet": doc.get("snippet", ""),
                "matched_variants": [], "fts_hits": 0, "entity_hit": False,
                "section_hits": 0,
            })
            entry["matched_variants"].append(variant)
            entry["fts_hits"] += 1
            if not entry["snippet"] and doc.get("snippet"):
                entry["snippet"] = doc["snippet"]

    # entidade (M3): docs do cluster da entidade canônica
    ent = canonical_entity(keyword)
    try:
        from .topics import build_topic_graph
        graph = build_topic_graph(storage, min_urls=1)
        cluster = next((c for c in graph if c["entity"] == ent), None)
        if cluster:
            for url in cluster["urls"]:
                entry = scores.setdefault(url, {
                    "url": url, "title": "", "snippet": "",
                    "matched_variants": [], "fts_hits": 0, "entity_hit": True,
                    "section_hits": 0,
                })
                entry["entity_hit"] = True
    except Exception:
        pass

    # seções (M2): headings que casam com termos da consulta
    kw_terms = set(normalize_entity(keyword).split())
    for url, entry in scores.items():
        sections = storage.corpus_sections_for_url(url)
        for sec in sections:
            heading_norm = normalize_entity(sec.get("heading", ""))
            if kw_terms & set(heading_norm.split()):
                entry["section_hits"] += 1
        entry["semantic_score"] = _semantic_score(entry)

    results = sorted(scores.values(),
                     key=lambda e: (e["semantic_score"], e["fts_hits"]),
                     reverse=True)
    return results[:limit]


def _semantic_score(entry: dict[str, Any]) -> float:
    """Score híbrido explicável (0..1). Componentes:

      * FTS: 0.15 por variante casada (cap 0.45);
      * entidade: 0.35 se o doc pertence ao cluster da entidade;
      * seção: 0.10 por seção com heading que casa (cap 0.20).
    """
    score = min(entry["fts_hits"] * 0.15, 0.45)
    if entry.get("entity_hit"):
        score += 0.35
    score += min(entry.get("section_hits", 0) * 0.10, 0.20)
    return round(score, 2)


def _norm(text: str) -> str:
    return normalize_entity(text)
