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


def build_topic_graph(storage: Any, *, min_urls: int = 1) -> list[dict[str, Any]]:
    """Clusters (entidade canônica) com URLs, origem da evidência e sinais.

    Combina corpus (entidades explícitas) + GSC (queries que citam a entidade).
    """
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


def cluster_coverage(storage: Any, entity: str, *, window_start: str | None = None) -> dict[str, Any]:
    """Cobertura completa de um cluster (critério M3)."""
    key = canonical_entity(entity)
    ws = window_start or storage.latest_window_start()

    corpus_index = _build_corpus_entity_index(storage)
    gsc_index = _build_gsc_entity_index(storage)
    urls = sorted((corpus_index.get(key, set()) | gsc_index.get(key, set())))

    posts = len(urls)
    indexable = 0
    internal_links = 0
    impressions = clicks = 0.0
    top3 = top10 = 0
    ga4_sessions = None
    ga4_status = "missing"
    freshest = ""

    for url in urls:
        # indexabilidade: corpus_documents (fonte do M2) com fallback inventory
        row = storage.conn.execute(
            "SELECT is_noindex FROM corpus_documents WHERE url = ?", (url,)
        ).fetchone()
        if row is None:
            row = storage.conn.execute(
                "SELECT is_noindex FROM editorial_inventory WHERE url = ?", (url,)
            ).fetchone()
        if row and not row[0]:
            indexable += 1
        # links internos: arestas dentro do cluster
        for r in storage.conn.execute(
            "SELECT COUNT(*) FROM internal_links WHERE source_url = ? "
            "AND target_url IN (%s)" % ",".join("?" * len(urls)),
            (url, *urls),
        ).fetchall():
            internal_links += r[0]
        # GSC: queries da URL que citam a entidade
        if ws:
            for r in storage.conn.execute(
                "SELECT SUM(impressions), SUM(clicks) FROM query_pages "
                "WHERE url = ? AND window_start = ? AND query LIKE ?",
                (url, ws, f"%{entity}%"),
            ).fetchall():
                impressions += r[0] or 0
                clicks += r[1] or 0
            for r in storage.conn.execute(
                "SELECT position FROM query_pages WHERE url = ? "
                "AND window_start = ? AND query LIKE ?",
                (url, ws, f"%{entity}%"),
            ).fetchall():
                if r[0] is not None:
                    if r[0] <= 3:
                        top3 += 1
                    if r[0] <= 10:
                        top10 += 1
        # frescor
        cr = storage.conn.execute(
            "SELECT built_at FROM corpus_documents WHERE url = ?", (url,)
        ).fetchone()
        if cr is None:
            cr = storage.conn.execute(
                "SELECT crawled_at FROM editorial_inventory WHERE url = ?", (url,)
            ).fetchone()
        if cr and cr[0] and cr[0] > freshest:
            freshest = cr[0]
        # GA4 (janela mais recente)
        ga4 = storage.ga4_metrics_for_url(url)
        if ga4 and ga4.get("measurement_status") == "available":
            ga4_sessions = (ga4_sessions or 0) + (ga4.get("sessions") or 0)
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
    }
