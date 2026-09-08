"""F3/F4 — Inteligência por página: Search Intelligence e Semantic Coverage.

Determinístico, sem LLM. Lê GSC (query_pages) e corpus (título/H1/corpo/seções)
para responder: há espaço para avançar? (F3) o conteúdo cobre a intenção? (F4).
"""
from __future__ import annotations

from typing import Any

SCORE_WEIGHTS = {"entity": 0.25, "title": 0.15, "h1": 0.15, "heading": 0.15,
                 "body": 0.15, "question": 0.05, "related": 0.10}


def _prev_window(storage: Any, window: str) -> str | None:
    rows = storage.conn.execute(
        "SELECT DISTINCT window_start FROM query_pages WHERE window_start < ? "
        "ORDER BY window_start DESC LIMIT 1", (window,)).fetchall()
    return rows[0][0] if rows else None


def _query_metrics(storage: Any, url: str, window: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    rows = storage.conn.execute(
        "SELECT query, clicks, impressions, ctr, position FROM query_pages "
        "WHERE url = ? AND window_start = ? AND position IS NOT NULL "
        "ORDER BY impressions DESC", (url, window)).fetchall()
    for r in rows:
        out[r[0]] = {"clicks": r[1] or 0, "impressions": r[2] or 0,
                     "ctr": r[3], "position": r[4]}
    return out


def _distribution(positions: list[float]) -> dict[str, int]:
    d = {"top3": 0, "top10": 0, "top20": 0, "top50": 0, "rest": 0}
    for p in positions:
        if p <= 3:
            d["top3"] += 1
        elif p <= 10:
            d["top10"] += 1
        elif p <= 20:
            d["top20"] += 1
        elif p <= 50:
            d["top50"] += 1
        else:
            d["rest"] += 1
    return d


def search_intelligence(storage: Any, url: str, topic_authority_score: float | None = None,
                        ) -> dict[str, Any]:
    """F3 — Search Intelligence por página (distribuição + query table + resumo)."""
    ws = storage.latest_window_start()
    empty = {"summary": {}, "queries": [], "distribution": {"top3": 0, "top10": 0, "top20": 0, "top50": 0, "rest": 0}, "window": ws or ""}
    if not ws:
        return empty
    prev_ws = _prev_window(storage, ws)
    cur = _query_metrics(storage, url, ws)
    prev = _query_metrics(storage, url, prev_ws) if prev_ws else {}
    positions = [m["position"] for m in cur.values() if m["position"] is not None]
    queries = []
    for query, m in sorted(cur.items(), key=lambda kv: -kv[1]["impressions"]):
        p = prev.get(query, {})
        delta = (p.get("position") - m["position"]) if (p.get("position") is not None and m["position"] is not None) else None
        imp_delta = (m["impressions"] - p["impressions"]) if p else None
        trend = ("growing" if imp_delta is not None and imp_delta > 0
                 else "declining" if imp_delta is not None and imp_delta < 0 else "stable")
        room = 0.0
        if m["position"] is not None:
            pos_gap = max(0.0, min((m["position"] - 1) / 19, 1.0))
            ctr_gap = 1.0 if (m.get("ctr") is None) else 0.5
            room = round(pos_gap * 0.6 + ctr_gap * 0.4, 3)
        queries.append({"query": query, "clicks": m["clicks"], "impressions": m["impressions"],
                        "ctr": m["ctr"], "position": m["position"], "delta_position": delta,
                        "trend": trend, "headroom": room,
                        "rankability": topic_authority_score})
    total_imp = sum(m["impressions"] for m in cur.values())
    prev_imp = sum(m["impressions"] for m in prev.values())
    positions_clean = [p for p in positions if p is not None]
    avg_pos = round(sum(positions_clean) / len(positions_clean), 1) if positions_clean else None
    return {
        "window": ws,
        "summary": {
            "clicks": sum(m["clicks"] for m in cur.values()),
            "impressions": total_imp,
            "avg_position": avg_pos,
            "impr_delta_pct": round((total_imp - prev_imp) / prev_imp * 100, 1) if prev_imp else None,
        },
        "distribution": _distribution(positions),
        "queries": queries,
    }


def _page_doc(storage: Any, url: str) -> dict[str, Any]:
    row = storage.conn.execute(
        "SELECT title, h1, body_text FROM corpus_documents WHERE url = ?", (url,)).fetchone()
    if row is None:
        return {"title": "", "h1": "", "body_text": ""}
    return {"title": row[0] or "", "h1": row[1] or "", "body_text": row[2] or ""}


def _term_coverage(terms: set[str], text: str) -> float:
    if not terms:
        return 0.0
    return len(terms & set(text.lower().split())) / len(terms)


def semantic_coverage(storage: Any, url: str, entity: str | None = None) -> dict[str, Any]:
    """F4 — cobertura semântica da página em relação às suas queries de topo."""
    doc = _page_doc(storage, url)
    ws = storage.latest_window_start()
    queries = _query_metrics(storage, url, ws) if ws else {}
    top_terms: set[str] = set()
    for q in list(queries)[:8]:
        top_terms |= {w for w in q.lower().split() if len(w) > 3}
    body = f"{doc['title']} {doc['h1']} {doc['body_text']}"
    parts = {
        "entity": 1.0 if (entity and entity.split()[0] in body.lower()) else 0.0,
        "title": _term_coverage(top_terms, doc["title"]),
        "h1": _term_coverage(top_terms, doc["h1"]),
        "heading": _heading_coverage(storage, url, top_terms),
        "body": _term_coverage(top_terms, doc["body_text"]),
        "question": 0.5 if any("?" in q or "como " in q or "qual " in q for q in queries) else 0.0,
        "related": 0.5,
    }
    coverage = sum(parts[k] * SCORE_WEIGHTS[k] for k in SCORE_WEIGHTS)
    covered = [q for q in queries if _term_coverage({w for w in q.lower().split() if len(w) > 3}, body) >= 0.25]
    gaps = [q for q in queries if q not in covered][:6]
    return {"coverage": round(coverage, 3), "components": {k: round(v, 3) for k, v in parts.items()},
            "covered": sorted(covered)[:8], "gaps": gaps}


def _heading_coverage(storage: Any, url: str, top_terms: set[str]) -> float:
    try:
        sections = storage.corpus_sections_for_url(url)
    except Exception:
        return 0.0
    if not top_terms:
        return 0.0
    match = 0
    for sec in sections:
        heading = (sec.get("heading") or "").lower()
        if top_terms & set(heading.split()):
            match += 1
    return round(min(match / max(len(sections), 1), 1.0), 3) if sections else 0.0
