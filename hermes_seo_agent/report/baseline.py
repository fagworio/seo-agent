"""Baseline PRÓPRIO do site (SEO-INC-013/014): percentis de CTR por contexto.

Substitui benchmarks externos por comportamento observado do próprio
UnicornioHater. Completamente determinístico — nada de IA.

Contexto PRIMÁRIO: faixa de posição × faixa de impressões (as duas dimensões
que o Search Console entrega e que mais explicam CTR). SEMPRE calculado.

SEGMENTO opcional (só usado quando tem amostra suficiente, senão cai no
primário — evita fragmentar o baseline em buckets de 1-2 páginas):
  content_type — listicle / explicacao / noticia / guia / outro (do título)
  entity_class — game / franchise / term (entidade dominante do corpus)
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

POSITION_BANDS: tuple[tuple[float, float, str], ...] = (
    (1, 3, "1-3"), (3, 5, "3-5"), (5, 10, "5-10"), (10, 20, "10-20"),
    (20, 1e9, "20+"),
)
IMPRESSION_BANDS: tuple[tuple[float, float, str], ...] = (
    (1, 500, "imp<500"), (500, 2000, "imp500-2k"), (2000, 1e9, "imp2k+"),
)
MIN_CTX_SAMPLE = 5       # abaixo disso o bucket não sustenta conclusão
MIN_SEGMENT_SAMPLE = 8   # segmento exige amostra maior (é mais fino)
# Piso de materialidade do P75 do segmento: abaixo disto a "captura" das
# comparáveis é ruído do GSC (os buckets degenerados do acervo ficam em <=0,1%;
# os que têm captura real ficam >=0,4%). Usado só no veredicto
# `below_comparable` — a anomalia RELATIVA da página dentro do segmento.
MIN_COMPARABLE_CTR = 0.004

# Tipo de conteúdo pelo título — determinístico, sem IA.
_CONTENT_PATTERNS: tuple[tuple[str, str], ...] = (
    # listicle: "10 melhores", "os 10 vilões", "ordem e sequência", ranking
    ("listicle", r"\b\d{1,2}\s+(melhores|maiores|piores|mais|curiosidades|fatos|"
                 r"coisas|jogos|s[eé]ries|filmes|animes|vil[oõ]es|personagens|"
                 r"motivos|dicas|erros)|\b(os|as)\s+\d{1,2}\b|"
                 r"\b(ordem e sequ[êe]ncia|ranking)\b"),
    # guia: intent de AÇÃO (assistir/jogar/baixar/como fazer)
    ("guia", r"\b(como|onde assistir|onde jogar|vale a pena|guia|tutorial|"
             r"passo a passo|requisitos)\b"),
    # explicação: pergunta respondida, perfil, origem/história, título da obra
    ("explicacao", r"\b(quem (é|foi|s[ãa]o)|quantos anos|qual a|quais s[ãa]o|"
                   r"o que (é|foi|significa)|onde fica|por que|porque|"
                   r"diferen[çc]a entre|origem e|tudo (sobre|o que)|"
                   r"poderes|fraqueza|explicad[oa]|entend[ae]|hist[óo]ria de|"
                   r"[ée] irm[ãa]o|s[ãa]o irm[ãa]os|significado)\b"),
    ("noticia", r"\b(estreia|estrear|lan[çc]amento|lan[çc]a|trailer|confirma|"
                r"confirmad[oa]|anuncia|revela|chega|ganha|ganhou|novo|nova|"
                r"atualiza|vaza|data de|adiad[oa])\b"),
)


def content_type(title: Any) -> str:
    """listicle | explicacao | noticia | guia | outro | unknown."""
    text = str(title or "").strip().lower()
    if not text:
        return "unknown"
    for label, pattern in _CONTENT_PATTERNS:
        if re.search(pattern, text):
            return label
    return "outro"


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
    """Chave do contexto primário (posição × impressões)."""
    return f"{_band(position, POSITION_BANDS)}|{_band(impressions, IMPRESSION_BANDS)}"


def segment_key(content: Any, entity: Any) -> str:
    """Chave do segmento (tipo de conteúdo × classe de entidade)."""
    return f"{content or 'unknown'}|{entity or 'unknown'}"


def _bucket_summary(ctrs: list[float]) -> dict[str, Any]:
    return {"n": len(ctrs), "p10": _percentile(ctrs, 0.10),
            "p25": _percentile(ctrs, 0.25), "p50": _percentile(ctrs, 0.50),
            "p75": _percentile(ctrs, 0.75)}


def build_baseline(storage: Any, *, window_end: str | None = None,
                   min_impressions: int = 100,
                   with_segments: bool = True) -> dict[str, Any]:
    """Percentis de CTR por contexto (+ segmentos), das janelas já coletadas.

    Somente páginas com volume mínimo entram (ruído não vira baseline).
    """
    rows = storage.conn.execute(
        "SELECT url, SUM(impressions) AS i, SUM(clicks) AS c, AVG(position) AS p "
        "FROM query_pages WHERE window_end = COALESCE(?, "
        "(SELECT MAX(window_end) FROM query_pages)) "
        "GROUP BY url HAVING i >= ?",
        (window_end, min_impressions),
    ).fetchall()

    from .align import current_title  # import tardio: evita ciclo de módulos

    # Lookups em LOTE (1 query cada): com 1 query por URL o build levava ~10s.
    _titles = _titles_by_path(storage) if with_segments else {}
    _entities = _entity_class_by_path(storage) if with_segments else {}

    contexts: dict[str, list[float]] = defaultdict(list)
    segments: dict[str, list[float]] = defaultdict(list)
    for url, impressions, clicks, position in rows:
        try:
            imp = float(impressions or 0)
            clk = float(clicks or 0)
        except (TypeError, ValueError):
            continue
        if imp <= 0:
            continue
        ctr = clk / imp
        contexts[context_key(position, imp)].append(ctr)
        if with_segments:
            from ..inventory.reconcile import normalize_url as _nurl
            path = _nurl(str(url))
            title = _titles.get(path) or current_title(storage, str(url))
            entity = _entities.get(path, "unknown")
            segments[segment_key(content_type(title), entity)].append(ctr)

    return {
        "window_end": window_end or "",
        "min_impressions": min_impressions,
        "pages": len(rows),
        "contexts": {k: _bucket_summary(v) for k, v in sorted(contexts.items())},
        "segments": {k: _bucket_summary(v) for k, v in sorted(segments.items())},
    }


def _titles_by_path(storage: Any) -> dict[str, str]:
    """{path: título} em UMA query (corpus tem prioridade sobre a captura)."""
    from ..inventory.reconcile import normalize_url

    out: dict[str, str] = {}
    try:
        rows = storage.conn.execute(
            "SELECT url, seo_title, title FROM corpus_documents").fetchall()
    except Exception:  # noqa: BLE001
        return out
    for url, seo_title, title in rows:
        value = str(seo_title or title or "").strip()
        if value:
            out[normalize_url(str(url))] = value
    return out


def _entity_class_by_path(storage: Any) -> dict[str, str]:
    """{path: classe dominante} em UMA query (game > franchise > term)."""
    from ..inventory.reconcile import normalize_url

    best: dict[str, tuple[int, str]] = {}
    prio = {"game": 3, "franchise": 2, "term": 1}
    try:
        rows = storage.conn.execute(
            "SELECT url, entity_type, COUNT(*) AS n FROM corpus_entities "
            "GROUP BY url, entity_type").fetchall()
    except Exception:  # noqa: BLE001
        return {}
    for url, entity_type, n in rows:
        path = normalize_url(str(url))
        score = int(n or 0) * 10 + prio.get(str(entity_type), 0)
        current = best.get(path)
        if current is None or score > current[0]:
            best[path] = (score, str(entity_type or "unknown"))
    return {path: value[1] for path, value in best.items()}


def dominant_entity_class(storage: Any, url: str) -> str:
    """game | franchise | term — classe da entidade mais citada na página."""
    from ..inventory.reconcile import normalize_url

    needle = f"%{normalize_url(url).rstrip('/')}%"
    try:
        rows = storage.conn.execute(
            "SELECT entity_type, COUNT(*) AS n, url FROM corpus_entities "
            "WHERE url LIKE ? GROUP BY entity_type, url "
            "ORDER BY CASE entity_type WHEN 'game' THEN 1 WHEN 'franchise' THEN 2 "
            "ELSE 3 END, n DESC LIMIT 20",
            (needle,),
        ).fetchall()
    except Exception:  # noqa: BLE001
        return "unknown"
    path = normalize_url(url)
    for entity_type, _n, row_url in rows:
        if normalize_url(str(row_url)) == path:
            return str(entity_type or "unknown")
    return "unknown"


def device_split(storage: Any, url: str) -> dict[str, Any]:
    """CTR por dispositivo + o gap mobile−desktop (SEO-INC-014).

    É a pista acionável mais direta quando existe: se o mobile captura muito
    menos que o desktop na MESMA página, o problema é de experiência/formato
    mobile — não de título.
    """
    rows: list[dict[str, Any]] = []
    if hasattr(storage, "device_metrics_for_url"):
        try:
            rows = storage.device_metrics_for_url(url)
        except Exception:  # noqa: BLE001
            rows = []
    by_device = {str(r.get("device") or "").lower(): r for r in rows}
    gap = None
    mob, desk = by_device.get("mobile") or {}, by_device.get("desktop") or {}
    try:
        m_imp = float(mob.get("impressions") or 0)
        d_imp = float(desk.get("impressions") or 0)
        if m_imp >= 50 and d_imp >= 50:
            gap = round(float(mob.get("ctr") or 0) - float(desk.get("ctr") or 0), 5)
    except (TypeError, ValueError):
        gap = None
    return {"devices": by_device, "mobile_minus_desktop": gap,
            "mobile_impressions": float(mob.get("impressions") or 0),
            "desktop_impressions": float(desk.get("impressions") or 0)}


def classify_ctr(ctr: Any, bucket: dict[str, Any] | None, *,
                 min_sample: int = MIN_CTX_SAMPLE) -> str:
    """Onde o CTR cai dentro do próprio contexto.

    below_p10 | low | typical | high | above_p75 | unknown
    """
    if bucket is None or int(bucket.get("n") or 0) < min_sample:
        return "unknown"
    try:
        value = float(ctr)
    except (TypeError, ValueError):
        return "unknown"
    p10, p25, p50, p75 = (bucket.get(k) for k in ("p10", "p25", "p50", "p75"))
    if p10 is not None and value < p10:
        return "below_p10"
    # SEO-INC-017b: caso degenerado do próprio acervo. Quando o P10 do segmento
    # é 0 (≥10% das comparáveis capta ~0) mas EXISTE captura comparável
    # MATERIAL (P75 ≥ MIN_COMPARABLE_CTR), a página que não capta nada é a
    # anomalia RELATIVA: o problema não é "o site inteiro", é esta página frente
    # às suas comparáveis. Fica num veredicto PRÓPRIO (não `below_p10`) para não
    # confundir com `ctr_zero_sitewide` — onde o segmento INTEIRO não capta.
    if (p10 is not None and float(p10) <= 0 and value <= 0
            and float(p75 or 0) >= MIN_COMPARABLE_CTR):
        return "below_comparable"
    if p25 is not None and value < p25:
        return "low"
    if p75 is not None and value > p75:
        return "above_p75"
    if p50 is not None and value >= p50:
        return "high"
    return "typical"


def ctr_verdict(storage: Any, *, position: Any, impressions: Any, ctr: Any,
                baseline: dict[str, Any] | None = None,
                content: str | None = None,
                entity: str | None = None) -> dict[str, Any]:
    """Classifica o CTR contra o baseline do PRÓPRIO contexto/segmento.

    Prefere o segmento (tipo × entidade) quando ele tem amostra suficiente;
    senão cai no contexto primário (posição × impressões). O resultado sempre
    informa qual nível foi usado (`level`), para o diagnóstico ser auditável.
    """
    base = baseline if baseline is not None else build_baseline(storage)
    key = context_key(position, impressions)
    bucket = (base.get("contexts") or {}).get(key)
    level = "context"

    seg_key = segment_key(content, entity)
    seg_bucket = (base.get("segments") or {}).get(seg_key)
    if seg_bucket and int(seg_bucket.get("n") or 0) >= MIN_SEGMENT_SAMPLE:
        # O segmento é mais específico: só usamos se ele próprio sustenta
        # (posição × impressões continua como fallback auditável).
        bucket = seg_bucket
        level = "segment"

    return {"context": key, "segment": seg_key, "level": level,
            "bucket": bucket or {},
            "sample_size": int((bucket or {}).get("n") or 0),
            "verdict": classify_ctr(ctr, bucket,
                                    min_sample=MIN_SEGMENT_SAMPLE if level == "segment"
                                    else MIN_CTX_SAMPLE),
            "baseline_window": base.get("window_end") or ""}
