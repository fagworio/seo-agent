"""M5-V2 — constrói os sinais (R2/R3/R4) a partir do storage para o modelo.

Reaproveita o que o projeto já coleta (corpus, GSC, GA4, link graph) e produz os
dicts de sinal que ``rankability_v2`` consome. Determinístico, zero API externa.
"""
from __future__ import annotations

import re
from typing import Any

from ..report.semantic import expand_query
from ..report.topics import cluster_coverage, canonical_entity, normalize_entity

_QUESTION_WORDS = ("quem", "qual", "quais", "como", "quando", "onde", "quantos",
                   "quantas", "por que", "porque", "o que", "é", "são", "vale",
                   "melhor", "vale a pena", "existe")


def latest_window_pair(storage: Any) -> tuple[str, str]:
    """A janela VIGENTE dos sinais persistidos: par (window_start, window_end).

    Uma decisão = uma janela temporal. Filtrar só ``window_start`` (ou nada)
    somava coletas de 28d/7d/1d e inflava a tração da query.
    """
    row = storage.conn.execute(
        "SELECT window_start, window_end FROM query_pages "
        "ORDER BY window_end DESC, window_start DESC LIMIT 1").fetchone()
    if not row:
        return "", ""
    return str(row[0] or ""), str(row[1] or "")


def _window_clause(window_start: str | None,
                   window_end: str | None) -> tuple[str, list[Any]]:
    """Cláusula de janela para os sinais GSC (par completo quando conhecido)."""
    if not window_start:
        return "", []
    args: list[Any] = [window_start]
    clause = " AND window_start = ?"
    if window_end:
        args.append(window_end)
        clause += " AND window_end = ?"
    return clause, args


def _window_impressions(storage: Any, urls: list[str], entity: str,
                        window: str, window_end: str | None = None) -> float:
    if not urls or not window:
        return 0.0
    placeholders = ", ".join("?" * len(urls))
    clause, extra = _window_clause(window, window_end)
    row = storage.conn.execute(
        f"SELECT SUM(impressions) FROM query_pages WHERE url IN ({placeholders}) "
        f"AND query LIKE ?{clause}", (*urls, f"%{entity}%", *extra)).fetchone()
    return float(row[0] or 0.0) if row else 0.0


def _previous_window(storage: Any, window: str) -> tuple[str, str] | None:
    row = storage.conn.execute(
        "SELECT window_start, window_end FROM query_pages WHERE window_start < ? "
        "ORDER BY window_end DESC, window_start DESC LIMIT 1", (window,)
    ).fetchone()
    return (str(row[0]), str(row[1])) if row else None


def _cluster_positions(storage: Any, urls: list[str], entity: str,
                       window: str, window_end: str | None = None) -> list[float]:
    if not urls or not window:
        return []
    placeholders = ", ".join("?" * len(urls))
    clause, extra = _window_clause(window, window_end)
    rows = storage.conn.execute(
        f"SELECT position FROM query_pages WHERE url IN ({placeholders}) "
        f"AND query LIKE ?{clause} AND position IS NOT NULL",
        (*urls, f"%{entity}%", *extra)).fetchall()
    return [float(r[0]) for r in rows]


def _internal_edges(storage: Any, urls: list[str]) -> list[tuple[str, str]]:
    if not urls:
        return []
    urlset = set(urls)
    edges: list[tuple[str, str]] = []
    for src, tgt in storage.conn.execute(
        "SELECT DISTINCT source_url, target_url FROM internal_links"
    ).fetchall():
        if src in urlset and tgt in urlset:
            edges.append((src, tgt))
    return edges


def _cluster_counts(storage: Any, entity: str, urls: list[str],
                    entity_counts: dict[str, int] | None = None) -> dict[str, int]:
    """Contagens do cluster (P2): entities via mapa pré-construído (GROUP BY de
    entidades distintas, não 100k+ linhas por cluster) e sections/questions via
    leitura em lote (IN) das seções do cluster."""
    key = canonical_entity(entity)
    if entity_counts is not None:
        entities = entity_counts.get(key, 0)
    else:
        entities = sum(
            1 for r in storage.conn.execute(
                "SELECT entity FROM corpus_entities").fetchall()
            if canonical_entity(r[0]) == key)
    sections = 0
    questions = 0
    if urls:
        placeholders = ",".join("?" * len(urls))
        row = storage.conn.execute(
            f"SELECT COUNT(*) FROM corpus_sections WHERE url IN ({placeholders})",
            urls).fetchone()
        sections = int(row[0] or 0)
        # Perguntas via SQL (LIKE no heading) — evita baixar/normalizar dezenas
        # de milhares de headings por cluster (corpus_sections tem 100k+ linhas).
        q = storage.conn.execute(
            f"SELECT COUNT(*) FROM corpus_sections WHERE url IN ({placeholders}) "
            "AND (heading LIKE '%?%' OR heading LIKE '%quem%' "
            "OR heading LIKE '%quantos%' OR heading LIKE '%quantas%' "
            "OR heading LIKE '%como%' OR heading LIKE '%qual%' "
            "OR heading LIKE '%quais%' OR heading LIKE '%quando%' "
            "OR heading LIKE '%onde%')", urls).fetchone()
        questions = int(q[0] or 0)
    return {"entities": entities, "sections": sections, "questions": questions}


def _technical(storage: Any, urls: list[str], indexable_urls: int,
               posts: int) -> dict[str, Any]:
    """Determina sinais técnicos do cluster (default otimista; usa o que souber)."""
    if not urls:
        return {"indexable": True, "http_ok": True, "canonical_ok": True,
                "in_sitemap": True, "google_indexed": None, "cwv_ok": None}
    placeholders = ",".join("?" * len(urls))
    # status HTTP + canonical + indexabilidade a partir do corpus/inventory
    http_ok = True
    canonical_ok = True
    for row in storage.conn.execute(
        f"SELECT is_noindex, status_code, canonical FROM corpus_documents "
        f"WHERE url IN ({placeholders})", urls).fetchall():
        if row[1] is not None and row[1] >= 400:
            http_ok = False
        if row[2] is not None and row[2] and row[2] != "":
            # canonical presente (não verificamos desvio aqui — sinal fraco)
            pass
    cwv_ok = None
    try:
        snap = storage.conn.execute(
            f"SELECT cwv_json FROM page_snapshots WHERE url IN ({placeholders}) "
            "AND cwv_json IS NOT NULL AND cwv_json != '' LIMIT 1", urls).fetchone()
        if snap:
            import json as _json
            cwv = _json.loads(snap[0]) if snap[0] else {}
            if cwv.get("lcp") and cwv.get("lcp") > 2.5:
                cwv_ok = False
            elif cwv.get("lcp"):
                cwv_ok = True
    except Exception:
        cwv_ok = None
    indexable = bool(indexable_urls) or posts == 0
    return {"indexable": indexable, "http_ok": http_ok, "canonical_ok": canonical_ok,
            "in_sitemap": indexable, "google_indexed": None, "cwv_ok": cwv_ok}


def build_cluster_signals(storage: Any, entity: str, *, window_start: str | None = None,
                          window_end: str | None = None,
                          index: dict[str, Any] | None = None) -> dict[str, Any]:
    """Sinais do cluster (R2/R3/R4) a partir do storage.

    `index` (de :func:`hermes_seo_agent.report.topics.build_cluster_index`)
    permite reaproveitar os índices construídos uma vez por request (P3),
    evitando reconstruí-los a cada cluster.

    `window_end` acompanha `window_start` para a janela ser o PAR completo (uma
    decisão = uma janela): sem ele, coletas de períodos diferentes somavam.
    """
    cov = cluster_coverage(storage, entity, window_start=window_start,
                           window_end=window_end, index=index)
    urls = cov["urls"]
    ws = cov["window_start"]
    we = cov.get("window_end") or ""
    prev = _previous_window(storage, ws) if ws else None
    # P1: cluster_coverage já leu posições/impressões/cliques em lote — reutiliza.
    positions = cov.get("positions", [])
    edge_counts = (index or {}).get("entity_counts")
    counts = _cluster_counts(storage, entity, urls, entity_counts=edge_counts)
    edges = _internal_edges(storage, urls)

    cur_imp = cov.get("impressions") or 0.0
    momentum = None
    if prev:
        prev_imp = _window_impressions(storage, urls, entity, prev[0], prev[1])
        if prev_imp > 0:
            momentum = round((cur_imp - prev_imp) / prev_imp * 100, 1)

    ga4_status = cov.get("ga4_status", "missing")
    ga4_rate = None
    if ga4_status == "available" and cov.get("ga4_organic_sessions"):
        # proxy: sessões orgânicas do cluster como sinal qualitativo (0..0.6)
        ga4_rate = min((cov.get("ga4_organic_sessions") or 0) / 5000, 0.6)

    tech = _technical(storage, urls, cov["indexable_urls"], cov["posts"])

    return {
        "entity": canonical_entity(entity),
        "urls": urls,
        "posts": cov["posts"],
        "entities": counts["entities"],
        "sections": counts["sections"],
        "questions": counts["questions"],
        "positions": positions,
        "impressions": cov["impressions"],
        "clicks": cov["clicks"],
        "internal_page_edges": edges,
        "ga4_engagement_rate": ga4_rate,
        "site_engagement_rate": None,
        "momentum_delta_pct": momentum,
        **tech,
    }, cov


def build_query_signals(storage: Any, cluster_signals: dict[str, Any], query: str,
                        *, window_start: str | None = None,
                        window_end: str | None = None) -> dict[str, Any]:
    """Sinais da query (R1/R4): fit semântico, tração, facilidade observada.

    * Sinais semânticos NÃO medidos ficam ``None`` (desconhecido) — antes
      começavam em 0.0, o que fazia ausência de medição entrar como medição ruim
      e derrubava o rankability mesmo com a renormalização do ``semantic_fit``.
    * ``window_start``/``window_end`` restringem a tração a UMA janela: sem isso
      somava coletas de 28d/7d/1d da mesma query (tração inflada).
    """
    variants = expand_query(query)
    ent = canonical_entity(query)
    cluster_signals.setdefault("entity", ent)

    # fit semântico via hybrid_search (M7) -> melhor doc do cluster
    semantic: dict[str, Any] = {"entity_fit": None, "title_fit": None, "h1_fit": None,
                                "heading_fit": None, "body_fit": None,
                                "question_fit": None, "related_entity_fit": None}
    try:
        from ..report.semantic import hybrid_search
        hits = hybrid_search(storage, query, limit=10)
        best = hits[0] if hits else None
        if best:
            semantic["entity_fit"] = 1.0 if best.get("entity_hit") else 0.0
            semantic["body_fit"] = (best.get("semantic_score") or 0.0)
            semantic["title_fit"] = 0.9 if best.get("title") else 0.0
            semantic["heading_fit"] = min(
                best.get("section_hits", 0) * 0.3, 0.9)
    except Exception:
        pass

    # tração: query_pages da query (e variantes canônicas) no cluster, na janela
    impressions = clicks = 0.0
    position = None
    if cluster_signals.get("urls") and variants:
        placeholders = ", ".join("?" * len(cluster_signals["urls"]))
        clause, extra = _window_clause(window_start, window_end)
        for v in variants:
            row = storage.conn.execute(
                f"SELECT SUM(impressions), SUM(clicks), AVG(position) "
                f"FROM query_pages WHERE url IN ({placeholders}) "
                f"AND query LIKE ?{clause}",
                (*cluster_signals["urls"], f"%{v}%", *extra)
            ).fetchone()
            if row:
                impressions += row[0] or 0
                clicks += row[1] or 0
                if row[2] is not None and (position is None or row[2] < position):
                    position = float(row[2])

    dist = (cluster_signals.get("positions") or [])
    top10_share = _top10_share(dist)

    return {
        "keyword": query,
        "impressions": impressions,
        "clicks": clicks,
        "position": position,
        "semantic": semantic,
        "topic_authority": None,  # preenchido pelo chamador se quiser
        "related_top10_share": top10_share,
    }


def build_family_query_signals(storage: Any, cluster_signals: dict[str, Any],
                               family: dict[str, Any], *,
                               window_start: str | None = None,
                               window_end: str | None = None,
                               max_queries: int = 3) -> dict[str, Any]:
    """Sinais da FAMÍLIA: semântica ponderada por impressões das suas queries.

    O motor agregava a demanda por família, mas construía a semântica a partir
    de UMA query representante (``family["queries"][0]``). Aqui cada query da
    família (até ``max_queries``, por impressões) contribui com o seu fit e a
    média é ponderada pela tração — os campos continuam ``None`` quando nada foi
    medido. Tração e posição são somadas/melhoradas entre as queries.
    """
    queries = list(family.get("queries") or [])[: max(int(max_queries or 1), 1)]
    collected: list[tuple[float, dict[str, Any]]] = []
    for query in queries:
        signals = build_query_signals(storage, dict(cluster_signals), str(query),
                                      window_start=window_start, window_end=window_end)
        weight = float(signals.get("impressions") or 0) or 1.0
        collected.append((weight, signals))
    if not collected:
        return build_query_signals(storage, dict(cluster_signals), "", window_start=window_start,
                                   window_end=window_end)

    keys = ("entity_fit", "title_fit", "h1_fit", "heading_fit", "body_fit",
            "question_fit", "related_entity_fit")
    semantic: dict[str, Any] = {}
    for key in keys:
        total = weight_sum = 0.0
        for weight, signals in collected:
            value = (signals.get("semantic") or {}).get(key)
            if value is None:
                continue
            total += float(value) * weight
            weight_sum += weight
        semantic[key] = round(total / weight_sum, 4) if weight_sum else None
    impressions = sum(float(s.get("impressions") or 0) for _w, s in collected)
    clicks = sum(float(s.get("clicks") or 0) for _w, s in collected)
    positions = [float(s["position"]) for _w, s in collected
                 if s.get("position") is not None]
    return {
        "keyword": family.get("family_id") or family.get("family"),
        "impressions": impressions,
        "clicks": clicks,
        "position": min(positions) if positions else family.get("weighted_position"),
        "semantic": semantic,
        "topic_authority": None,
        "related_top10_share": (collected[0][1] or {}).get("related_top10_share", 0.0),
        "queries_measured": len(collected),
        "weighting": "impressões das queries da família",
    }


def _top10_share(positions: list[float]) -> float:
    if not positions:
        return 0.0
    return round(sum(1 for p in positions if p <= 10) / len(positions), 4)


def _question_score(heading: str) -> bool:
    return "?" in heading or any(w in normalize_entity(heading)
                                 for w in ("quantos", "quantas", "quem", "como",
                                           "qual", "quais", "quando", "onde"))


def resolve_cluster_entity(storage: Any, keyword: str,
                           index: dict[str, Any] | None = None) -> str:
    """Resolve uma keyword para a ENTIDADE do cluster mais próximo (por tokens).

    Ex.: "dragon ball daima temporada 2" -> "dragon ball". Determinístico.
    `index` (de :func:`hermes_seo_agent.report.topics.build_cluster_index`)
    evita reconstruir o topic graph a cada chamada (P3).
    """
    from .topics import build_topic_graph
    kw_terms = set(normalize_entity(keyword).split())
    if not kw_terms:
        return canonical_entity(keyword)
    best, best_score = canonical_entity(keyword), 0
    try:
        graph = build_topic_graph(storage, min_urls=1, index=index)
        for c in graph:
            ent_terms = set(normalize_entity(c["entity"]).split())
            overlap = len(kw_terms & ent_terms)
            # prefere a entidade que aparece por extenso na keyword
            if overlap > best_score or (overlap == best_score and best_score > 0
                                        and normalize_entity(c["entity"]) in kw_terms):
                best_score = overlap
                best = c["entity"]
    except Exception:
        pass
    return best
