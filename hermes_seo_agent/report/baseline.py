"""Baseline PRÓPRIO do site (SEO-INC-013): percentis de CTR por contexto.

Substitui benchmarks externos ("posição 1-3 = 20% de CTR") por comportamento
observado do próprio UnicornioHater. Completamente determinístico — nada de IA,
nada de curva de CTR importada de terceiros.

Contexto = faixa de posição × faixa de impressões (as duas dimensões que o
Search Console entrega e que mais explicam CTR). Cada bucket guarda P10/P25/
P50/P75 e o n (tamanho de amostra), para a anomalia ser julgada contra o
comportamento do próprio segmento e não contra um número arbitrário.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

POSITION_BANDS: tuple[tuple[float, float, str], ...] = (
    (1, 3, "1-3"), (3, 5, "3-5"), (5, 10, "5-10"), (10, 20, "10-20"),
    (20, 1e9, "20+"),
)
IMPRESSION_BANDS: tuple[tuple[float, float, str], ...] = (
    (1, 500, "imp<500"), (500, 2000, "imp500-2k"), (2000, 1e9, "imp2k+"),
)
MIN_CTX_SAMPLE = 5   # abaixo disso o bucket não sustenta conclusão


def _band(value: Any, bands: tuple[tuple[float, float, str], ...]) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "unknown"
    for lo, hi, label in bands:
        if lo <= v < hi:
            return label
    return bands[-1][2]


def _percentile(values: list[float], q: float) -> float | None:
    """Percentil com interpolação linear (stdlib puro)."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 6)
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * frac, 6)


def context_key(position: Any, impressions: Any) -> str:
    """Chave do contexto (estável, aparece no JSON)."""
    return f"{_band(position, POSITION_BANDS)}|{_band(impressions, IMPRESSION_BANDS)}"


def build_baseline(storage: Any, *, window_end: str | None = None,
                   min_impressions: int = 100) -> dict[str, Any]:
    """Percentis de CTR por contexto, a partir das janelas já coletadas.

    Usa a janela mais recente por padrão; passa `window_end` para comparar
    períodos. Somente páginas com volume mínimo entram (ruído não vira baseline).
    """
    rows = storage.conn.execute(
        "SELECT url, SUM(impressions) AS i, SUM(clicks) AS c, AVG(position) AS p "
        "FROM query_pages WHERE window_end = COALESCE(?, "
        "(SELECT MAX(window_end) FROM query_pages)) "
        "GROUP BY url HAVING i >= ?",
        (window_end, min_impressions),
    ).fetchall()

    buckets: dict[str, list[float]] = defaultdict(list)
    for _url, impressions, clicks, position in rows:
        try:
            imp = float(impressions or 0)
            clk = float(clicks or 0)
        except (TypeError, ValueError):
            continue
        if imp <= 0:
            continue
        buckets[context_key(position, imp)].append(clk / imp)

    out: dict[str, Any] = {}
    for key, ctrs in sorted(buckets.items()):
        out[key] = {
            "n": len(ctrs),
            "p10": _percentile(ctrs, 0.10),
            "p25": _percentile(ctrs, 0.25),
            "p50": _percentile(ctrs, 0.50),
            "p75": _percentile(ctrs, 0.75),
        }
    return {"window_end": window_end or "", "min_impressions": min_impressions,
            "pages": len(rows), "contexts": out}


def classify_ctr(ctr: Any, bucket: dict[str, Any] | None) -> str:
    """Onde o CTR cai dentro do próprio contexto.

    below_p10 | low | typical | high | above_p75 | unknown
    """
    if bucket is None or int(bucket.get("n") or 0) < MIN_CTX_SAMPLE:
        return "unknown"
    try:
        value = float(ctr)
    except (TypeError, ValueError):
        return "unknown"
    p10, p25, p50, p75 = (bucket.get(k) for k in ("p10", "p25", "p50", "p75"))
    if p10 is not None and value < p10:
        return "below_p10"
    if p25 is not None and value < p25:
        return "low"
    if p75 is not None and value > p75:
        return "above_p75"
    if p50 is not None and value >= p50:
        return "high"
    return "typical"


def ctr_verdict(storage: Any, *, position: Any, impressions: Any, ctr: Any,
                baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classifica o CTR da página contra o baseline do PRÓPRIO contexto."""
    base = baseline if baseline is not None else build_baseline(storage)
    key = context_key(position, impressions)
    bucket = (base.get("contexts") or {}).get(key)
    return {"context": key, "bucket": bucket or {},
            "verdict": classify_ctr(ctr, bucket),
            "baseline_window": base.get("window_end") or ""}
