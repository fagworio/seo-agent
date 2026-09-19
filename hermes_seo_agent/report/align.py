"""Alinhamento query × título para o DIAGNÓSTICO (SEO-INC-012).

Reusa o MESMO critério de cobertura do gerador (`title_opportunities._covered`)
para o diagnóstico não divergir da decisão de oportunidade: se o gerador
considera a query coberta, o diagnóstico também considera — senão o pipeline
se contradiz (bloqueia reescrever e ao mesmo tempo acusa gap).

Host-agnóstico: as fontes guardam a mesma página em hosts diferentes
(`corpus_documents` em prod.*, `query_pages`/`page_snapshots` em www.*), então
toda busca casa por PATH (normalize_url), nunca por URL literal.
"""

from __future__ import annotations

from typing import Any

from ..inventory.reconcile import normalize_url
from ..tools.title_opportunities import _covered


def _lookup(storage: Any, sql: str, url: str) -> tuple | None:
    """Primeira linha cujo PATH normalizado bate com o da URL pedida."""
    path = normalize_url(url)
    needle = f"%{path.rstrip('/')}%"
    try:
        rows = storage.conn.execute(sql, (needle,)).fetchall()
    except Exception:  # noqa: BLE001 — diagnóstico nunca derruba a medição
        return None
    for row in rows:
        if normalize_url(str(row[-1])) == path:
            return row
    return None


def current_title(storage: Any, url: str) -> str:
    """Título SEO atual pela fonte MAIS RECENTE (SEO-INC-016).

    Antes o `corpus_documents` era autoridade absoluta. Com o rebuild do corpus
    limitado a 1.000 itens por ciclo, ele pode ficar temporariamente ATRASADO —
    e o diagnóstico usaria o título antigo, acusando `query_title_gap` num
    título que o agente acabou de corrigir (churn por evidência stale).

    Ordem: maior ``built_at``/``captured_at`` vence; sem timestamp, a captura da
    página (que reflete o site no ar) tem precedência; corpus por último.
    """
    candidatos: list[tuple[str, str]] = []

    row = _lookup(
        storage,
        "SELECT seo_title, title, built_at, url FROM corpus_documents "
        "WHERE url LIKE ? ORDER BY built_at DESC LIMIT 20",
        url,
    )
    if row and (row[0] or row[1]):
        candidatos.append((str(row[2] or ""), str(row[0] or row[1])))

    row = _lookup(
        storage,
        "SELECT title, captured_at, url FROM page_snapshots "
        "WHERE title IS NOT NULL AND title != '' AND url LIKE ? "
        "ORDER BY captured_at DESC LIMIT 20",
        url,
    )
    if row and row[0]:
        candidatos.append((str(row[1] or ""), str(row[0])))

    if not candidatos:
        return ""
    com_ts = [c for c in candidatos if c[0]]
    if com_ts:
        com_ts.sort(key=lambda c: c[0], reverse=True)
        return com_ts[0][1]
    return candidatos[-1][1]  # captura (site no ar) > corpus


def top_query(storage: Any, url: str) -> str:
    """Query de valor: a de maior impressão na janela mais recente."""
    path = normalize_url(url)
    needle = f"%{path.rstrip('/')}%"
    try:
        rows = storage.conn.execute(
            "SELECT query, SUM(impressions) AS i, url FROM query_pages "
            "WHERE url LIKE ? AND window_end = (SELECT MAX(window_end) FROM query_pages) "
            "GROUP BY query, url ORDER BY i DESC LIMIT 40",
            (needle,),
        ).fetchall()
    except Exception:  # noqa: BLE001
        return ""
    for query, _imp, row_url in rows:
        if normalize_url(str(row_url)) == path:
            return str(query)
    return ""


def query_alignment(storage: Any, url: str) -> dict[str, Any]:
    """Alinhamento query × título + evidência citável.

    Devolve `aligned` (bool | None), `query`, `title` e `coverage` — o
    diagnóstico cita o dado, não uma opinião.
    """
    query = top_query(storage, url)
    title = current_title(storage, url)
    if not query or not title:
        return {"aligned": None, "query": query, "title": title, "coverage": None}
    aligned = bool(_covered(query, title))
    return {"aligned": aligned, "query": query, "title": title,
            "coverage": "covered" if aligned else "gap"}
