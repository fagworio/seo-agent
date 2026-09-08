"""M3 — Tópicos, entidades e clusters (determinístico, sem IA obrigatória).

Sai da correspondência puramente lexical sem depender de NLP:

  * normalização determinística: acentos, caixa, aliases de franquias,
    singular/plural básico;
  * topic_graph: clusters a partir de entidades do corpus + coocorrência em
    títulos/H2 + queries GSC;
  * cobertura por cluster: posts, indexáveis, links internos, impressões/
    cliques, Top3/Top10, frescor e GA4 (quando disponível).

Critério M3: o agente explica POR QUE uma pauta pertence — ou não — ao
território editorial do site.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Aliases de franquias/obras -> entidade canônica do território.
ENTITY_ALIASES: dict[str, str] = {
    "jjk": "jujutsu kaisen",
    "aot": "attack on titan",
    "shingeki": "attack on titan",
    "dbs": "dragon ball",
    "mha": "my hero academia",
    "bnha": "my hero academia",
    "op": "one piece",
    "hxh": "hunter x hunter",
    "fma": "fullmetal alchemist",
    "csm": "chainsaw man",
    "mob": "mob psycho",
    "jojo": "jojo's bizarre adventure",
    "jjba": "jojo's bizarre adventure",
    "kny": "demon slayer",
    "ds": "demon slayer",
    "mcu": "marvel",
    "dcu": "dc",
    "sw": "star wars",
    "the boys": "the boys",
    "heman": "he-man",
    "masters of the universe": "he-man",
}


def normalize_entity(text: str) -> str:
    """Normaliza um termo para chave de cluster: minúsculas, sem acentos,
    espaços colapsados, singular básico (s/z finais)."""
    s = (text or "").lower().strip()
    s = "".join(c for c in unicodedata.normalize("NFKD", s)
                if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def canonical_entity(term: str) -> str:
    """Resolve aliases para a entidade canônica; senão retorna o termo normalizado."""
    norm = normalize_entity(term)
    return ENTITY_ALIASES.get(norm, norm)


def _build_corpus_entity_index(storage: Any) -> dict[str, set[str]]:
    """entidade canônica -> {urls} a partir de corpus_entities."""
    index: dict[str, set[str]] = {}
    rows = storage.conn.execute(
        "SELECT url, entity, entity_type FROM corpus_entities"
    ).fetchall()
    for url, entity, etype in rows:
        key = canonical_entity(entity)
        index.setdefault(key, set()).add(url)
    return index


def _build_gsc_entity_index(storage: Any) -> dict[str, set[str]]:
    """entidade canônica -> {urls} a partir de queries GSC (query contém a entidade)."""
    index: dict[str, set[str]] = {}
    ws = storage.latest_window_start()
    if not ws:
        return index
    rows = storage.conn.execute(
        "SELECT query, url FROM query_pages WHERE window_start = ?", (ws,)
    ).fetchall()
    for query, url in rows:
        q = normalize_entity(query)
        for entity, _ in ENTITY_ALIASES.items():
            if q and (entity in q or f" {entity} " in f" {q} "):
                index.setdefault(canonical_entity(entity), set()).add(url)
        # termos capitalizados de 2+ palavras que aparecem inteiros na query
        for m in re.finditer(r"\b([a-z]+(?: [a-z]+){1,3})\b", q):
            term = m.group(1)
            if term in ENTITY_ALIASES:
                index.setdefault(canonical_entity(term), set()).add(url)
    return index


def _build_corpus_entity_counts(storage: Any) -> dict[str, int]:
    """entidade canônica -> nº total de linhas de corpus_entities (P2).

    Canonicaliza apenas as entidades DISTINTAS (GROUP BY), não as 100k+ linhas,
    e é construída 1x por request (P3). Mantém a semântica de `_cluster_counts`.
    """
    counts: dict[str, int] = {}
    for entity, cnt in storage.conn.execute(
        "SELECT entity, COUNT(*) FROM corpus_entities GROUP BY entity").fetchall():
        key = canonical_entity(entity)
        counts[key] = counts.get(key, 0) + int(cnt)
    return counts


def build_cluster_index(storage: Any) -> dict[str, Any]:
    """Índices do topic graph construídos UMA vez por request (P3).

    Evita reconstruir os índices de corpus/GSC (100k+ linhas) a cada cluster e
    evita refazer `latest_window_start`/`latest_ga4_window` por chamada.
    """
    return {
        "corpus_index": _build_corpus_entity_index(storage),
        "entity_counts": _build_corpus_entity_counts(storage),
        "gsc_index": _build_gsc_entity_index(storage),
        "window": storage.latest_window_start(),
        "ga4_window": storage.latest_ga4_window(),
    }


def build_topic_graph(storage: Any, *, min_urls: int = 1,
                      index: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Clusters (entidade canônica) com URLs, origem da evidência e sinais.

    Combina corpus (entidades explícitas) + GSC (queries que citam a entidade).
    `index` opcional (de :func:`build_cluster_index`) permite reaproveitar os
    índices construídos uma vez (P3), evitando refazer a varredura do corpus.
    """
    if index is not None:
        corpus_index = index["corpus_index"]
        gsc_index = index["gsc_index"]
    else:
        corpus_index = _build_corpus_entity_index(storage)
        gsc_index = _build_gsc_entity_index(storage)
    all_keys = set(corpus_index) | set(gsc_index)
    clusters: list[dict[str, Any]] = []
    for key in sorted(all_keys):
        corpus_urls = corpus_index.get(key, set())
        gsc_urls = gsc_index.get(key, set())
        urls = corpus_urls | gsc_urls
        if len(urls) < min_urls:
            continue
        clusters.append({
            "entity": key,
            "urls": sorted(urls),
            "corpus_urls": len(corpus_urls),
            "gsc_query_urls": len(gsc_urls),
            "evidence": {
                "corpus_entities": len(corpus_urls) > 0,
                "gsc_queries": len(gsc_urls) > 0,
            },
        })
    clusters.sort(key=lambda c: -len(c["urls"]))
    return clusters


def cluster_coverage(storage: Any, entity: str, *, window_start: str | None = None,
                     index: dict[str, Any] | None = None) -> dict[str, Any]:
    """Cobertura completa de um cluster (critério M3).

    Batch por cluster (P1): em vez de 8-10 queries POR URL, faz ~5 queries
    agregadas (IN) + uma passada Python leve. `index` (de
    :func:`build_cluster_index`) evita reconstruir os índices de corpus/GSC e
    refazer latest_window/latest_ga4_window por chamada (P3).
    """
    key = canonical_entity(entity)
    ws = window_start or (index or {}).get("window") or storage.latest_window_start()
    if index is None:
        index = build_cluster_index(storage)
    corpus_index = index["corpus_index"]
    gsc_index = index["gsc_index"]
    urls = sorted((corpus_index.get(key, set()) | gsc_index.get(key, set())))

    posts = len(urls)
    indexable = 0
    internal_links = 0
    impressions = clicks = 0.0
    top3 = top10 = 0
    positions: list[float] = []
    ga4_sessions = None
    ga4_status = "missing"
    freshest = ""

    if urls:
        ph = ",".join("?" * len(urls))

        # indexabilidade + frescor (P1): corpus_documents com fallback
        # editorial_inventory, em uma leitura por tabela — sem N+1. O frescor
        # repete a preferência do original (corpus built_at, senão inventory
        # crawled_at) por URL, para não sobrevalorizar quando a URL está em ambos.
        doc_meta: dict[str, tuple[Any, Any]] = {
            r[0]: (r[1], r[2]) for r in storage.conn.execute(
                f"SELECT url, is_noindex, built_at FROM corpus_documents "
                f"WHERE url IN ({ph})", urls).fetchall()}
        inv_meta: dict[str, tuple[Any, Any]] = {
            r[0]: (r[1], r[2]) for r in storage.conn.execute(
                f"SELECT url, is_noindex, crawled_at FROM editorial_inventory "
                f"WHERE url IN ({ph})", urls).fetchall()}
        for url in urls:
            row = doc_meta.get(url)
            if row is None:
                row = inv_meta.get(url)
            if row is not None and not row[0]:
                indexable += 1
            ts = (row[1] if row is not None else None) or ""
            if ts and ts > freshest:
                freshest = ts

        # links internos: arestas dentro do cluster.
        # CUIDADO: `source_url IN (...) AND target_url IN (...)` com listas
        # grandes faz o SQLite expandir em um loop aninhado O(n²) no autoindex
        # (93M probes p/ 9667 URLs) — medido 34s numa tabela de 546 linhas.
        # Faz-se uma leitura indexada por target_url (idx_il_target) e filtra o
        # source em Python (pouquíssimas linhas).
        uset = set(urls)
        rows = storage.conn.execute(
            f"SELECT source_url FROM internal_links WHERE target_url IN ({ph})",
            urls).fetchall()
        internal_links = sum(1 for (src,) in rows if src in uset)

        # GSC: impressões/cliques e posições do cluster na janela (uma query cada)
        if ws:
            row = storage.conn.execute(
                f"SELECT SUM(impressions), SUM(clicks) FROM query_pages "
                f"WHERE url IN ({ph}) AND window_start = ? AND query LIKE ?",
                (*urls, ws, f"%{entity}%")).fetchone()
            impressions = float(row[0] or 0)
            clicks = float(row[1] or 0)
            for (pos,) in storage.conn.execute(
                f"SELECT position FROM query_pages WHERE url IN ({ph}) "
                "AND window_start = ? AND query LIKE ? AND position IS NOT NULL",
                (*urls, ws, f"%{entity}%")).fetchall():
                if pos is not None:
                    positions.append(float(pos))
                    if pos <= 3:
                        top3 += 1
                    if pos <= 10:
                        top10 += 1

        # GA4 (janela mais recente) — uma única leitura para o cluster
        ga4_ws = (index or {}).get("ga4_window") or storage.latest_ga4_window()
        if ga4_ws:
            for u, status_, sessions_ in storage.conn.execute(
                f"SELECT url, measurement_status, sessions FROM ga4_page_metrics "
                f"WHERE url IN ({ph}) AND window_start = ? AND source_scope = "
                "'organic_landing'", (*urls, ga4_ws)).fetchall():
                if status_ == "available":
                    ga4_sessions = (ga4_sessions or 0) + (sessions_ or 0)
                    ga4_status = "available"

    return {
        "entity": key,
        "posts": posts,
        "indexable_urls": indexable,
        "internal_links": internal_links,
        "impressions": round(impressions, 1),
        "clicks": round(clicks, 1),
        "top3_queries": top3,
        "top10_queries": top10,
        "freshest_crawl": freshest,
        "ga4_organic_sessions": ga4_sessions,
        "ga4_status": ga4_status,
        "window_start": ws or "",
        "urls": urls,
        "positions": positions,
    }
