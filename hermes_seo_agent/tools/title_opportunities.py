"""Title opportunity research — strategic, GSC + Google Trends grounded.

The old generator turned the raw top GSC query into a title-cased fragment
("gojo" -> "Gojo", "highie" -> "Highie") — often WORSE than the current
title. The strategic generator makes a data-driven decision:

1. It keeps the page's ENTITY (the work/subject already in the title — the
   indexed identity that must not be lost).
2. It scores the page's real GSC queries by statistical value: position,
   impressions (log), CTR, and — when Trends answers — market interest and
   momentum (rising/falling) in the last 90 days.
3. It only proposes a title when a high-value query is NOT already covered
   by the current title (no candidate = current title already optimal).
4. The candidate is built by injecting the missing keyword into the current
   title, never by replacing it with a bare fragment.

This is the "crossing of SEO data with Google connections" (Search Console +
Trends) for the title decision — the keyword choice is a statistic, not an
opinion.
"""

from __future__ import annotations

import math
import re
from typing import Any

# Prepositions/articles that stay lowercase in a title-case candidate.
_SMALL = {"a", "o", "os", "as", "de", "da", "do", "das", "dos", "e", "em",
          "no", "na", "nos", "nas", "para", "com", "um", "uma", "uns", "umas",
          "que", "por", "até", "the", "of", "and", "in", "to"}
# Words that carry no keyword value (skip when checking coverage).
_STOP = _SMALL | {"como", "qual", "quais", "quanto", "quantos", "quando",
                  "onde", "porque", "serie", "sao", "foi", "era", "tem", "ter"}


def pick_top_query(rows: list[dict[str, Any]]) -> str:
    """Legacy: highest-value raw query (kept for backward compatibility)."""
    if not rows:
        return ""
    meaningful = [r for r in rows if float(r.get("impressions", 0)) >= 2]
    pool = meaningful or rows
    pool = sorted(
        pool,
        key=lambda r: (float(r.get("position", 100)), -float(r.get("impressions", 0))),
    )
    return (pool[0].get("keys") or [""])[0]


def candidate_title(query: str, *, max_len: int = 60) -> str:
    """Legacy: title-case of a raw query (kept for backward compatibility)."""
    query = re.sub(r"\s+", " ", (query or "").strip())
    if not query:
        return ""
    words = query.split()
    out: list[str] = []
    for index, word in enumerate(words):
        lower = word.lower()
        if index == 0 or lower not in _SMALL:
            out.append(word.capitalize())
        else:
            out.append(lower)
    title = " ".join(out)
    if len(title) > max_len:
        title = title[:max_len].rstrip()
    return title


# --------------------------------------------------------------------------
# Strategic generator (GSC x Trends)
# --------------------------------------------------------------------------

def discover_momentum(
    daily_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Site-wide Google Discover signal from daily rows.

    Returns {impressions, clicks, active_days, momentum} where momentum is
    +1 (Discover accelerating: second half > first half +15%), -1 (losing
    reach) or 0 (stable). Discover is site-wide only (the API forbids
    page/query dimensions under the type filter) — this signal tells the
    agent WHEN discovery-style titles/content are worth prioritizing.
    """
    impressions = sum(float(r.get("impressions", 0)) for r in daily_rows)
    clicks = sum(float(r.get("clicks", 0)) for r in daily_rows)
    active = sum(1 for r in daily_rows if float(r.get("impressions", 0)) > 0)
    n = len(daily_rows)
    if n >= 6:
        half = max(n // 2, 1)
        recent = sum(float(r.get("impressions", 0)) for r in daily_rows[-half:])
        previous = sum(float(r.get("impressions", 0)) for r in daily_rows[: n - half])
        if previous <= 0:
            momentum = 1 if recent > 0 else 0
        else:
            delta = (recent - previous) / previous
            momentum = 1 if delta > 0.15 else (-1 if delta < -0.15 else 0)
    else:
        momentum = 0
    return {
        "impressions": round(impressions),
        "clicks": round(clicks),
        "active_days": active,
        "momentum": momentum,
    }


def _tokens(text: str) -> set[str]:
    """Significant lowercase tokens (no stopwords, no punctuation)."""
    words = re.findall(r"[a-zà-ú0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in _STOP}


def entity_of(current_title: str) -> str:
    """The indexed identity of the page: text before ':' or the first ' — '.

    "Hughie Campbell: poderes e tudo sobre The Boys — UnicornioHater"
    -> "Hughie Campbell". Keeps entity first in any candidate.
    """
    title = re.sub(r"\s+", " ", (current_title or "").strip())
    title = re.split(r"\s+[—–-]\s+", title)[0].strip()
    if ":" in title:
        title = title.split(":", 1)[0].strip()
    return title or title.strip()


def _query_value(row: dict[str, Any], trends: dict[str, Any] | None) -> float:
    """Statistical value of a GSC query row, enriched by Trends.

    GSC part: log10(impressions) * position_factor * (1 + ctr).
    Trends part (optional): interest 0..100 normalized + momentum bonus.
    """
    impressions = max(float(row.get("impressions", 0)), 1.0)
    position = max(float(row.get("position", 10)), 1.0)
    ctr = max(float(row.get("ctr", 0)), 0.0)
    position_factor = 1.0 / math.sqrt(position)  # pos 1 = 1.0, pos 10 = 0.32
    gsc = math.log10(impressions + 1) * position_factor * (1.0 + ctr * 5)
    if trends:
        interest = trends.get("interest")
        if isinstance(interest, (int, float)):
            gsc *= 1.0 + min(float(interest) / 100.0, 1.0) * 0.6
        momentum = trends.get("momentum", 0)
        gsc *= 1.0 + float(momentum) * 0.25
    return gsc


def _covered(query: str, current_title: str) -> bool:
    """True when the current title already covers the query keywords.

    Coverage = fraction of significant query tokens present in the title.
    Tokens of <=3 chars (acronyms like "mha", "ps5") are ambiguous and never
    count as missing. A query is covered at >=50%: "eri mha idade" vs
    "Quantos anos tem Eri em My Hero Academia?" -> eri present, idade absent,
    mha ignored => 1/2 = 50% => covered (the intent is already answered).
    """
    q_tokens = _tokens(query)
    if not q_tokens:
        return True
    title_tokens = _tokens(current_title)
    hits = sum(1 for t in q_tokens if t in title_tokens)
    # Missing tokens of <=3 chars (acronyms "mha"/"ps5") never count as a
    # gap; missing longer tokens do. Covered at >=50% of the required set.
    missing_long = [t for t in q_tokens if t not in title_tokens and len(t) > 3]
    required = hits + len(missing_long)
    if required == 0:
        return True
    return hits >= required * 0.5


def strategic_title(
    current_title: str,
    queries: list[dict[str, Any]],
    trends: dict[str, dict[str, Any]] | None = None,
    *,
    max_len: int = 60,
) -> dict[str, Any] | None:
    """Data-driven title decision for one page.

    ``queries``: GSC query rows [{keys:[q], impressions, position, ctr}].
    ``trends``: {query: {interest, momentum}} from GoogleTrendsClient (may be
    partial — missing queries get neutral trends).

    Returns None when the current title already covers the best uncovered
    high-value query, or when no query beats the threshold (current title is
    optimal). Otherwise a dict:
      {title, keyword, rationale, score, trends}
    """
    title_clean = re.sub(r"\s+", " ", (current_title or "").strip())
    if not queries or not title_clean:
        return None
    trends = trends or {}
    entity = entity_of(title_clean)

    scored: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for row in queries:
        query = (row.get("keys") or [""])[0]
        if not query:
            continue
        tr = trends.get(query, {"interest": None, "momentum": 0})
        value = _query_value(row, tr)
        scored.append((value, row, tr))
    scored.sort(key=lambda x: x[0], reverse=True)

    # Best query that is NOT already covered by the current title.
    for value, row, tr in scored:
        query = (row.get("keys") or [""])[0]
        if _covered(query, title_clean):
            continue
        impressions = float(row.get("impressions", 0))
        position = float(row.get("position", 0))
        ctr = float(row.get("ctr", 0))
        # Statistical threshold: meaningful demand worth a title change.
        if impressions < 5 or position > 30:
            continue
        q_tokens = _tokens(query)
        # Fragments of a single word ("gojo", "highie", "eri") are usually
        # typos or bare entities already covered — never propose them.
        if len(q_tokens) < 2:
            continue
        keyword = candidate_title(query, max_len=40)
        keyword = re.sub(r"\s*—.*$", "", keyword).strip()
        if not keyword:
            continue
        # Build: ENTITY: description + keyword (drop the brand if it does
        # not fit; brand has zero search value). Remove keyword tokens the
        # title already carries (entity/description) to avoid repetition.
        description = title_clean
        if ":" in title_clean:
            description = title_clean.split(":", 1)[1].strip()
        description = re.sub(r"\s+[—–-]\s+.*$", "", description).strip()
        covered_words = _tokens(f"{entity} {description}")
        kw_words = [w for w in keyword.split() if w.lower() not in covered_words]
        if not kw_words:
            continue
        kw_extra = " ".join(kw_words)
        candidate = f"{entity}: {description} {kw_extra}".strip()
        if len(candidate) > max_len:
            # Shorter: ENTITY: keyword (entity is the indexed identity).
            candidate = f"{entity}: {kw_extra}".strip()
        if len(candidate) > max_len:
            candidate = candidate[: max_len - 1].rstrip() + "…"
        if not candidate or candidate.lower() == title_clean.lower():
            return None
        momentum_txt = {1: "em alta", 0: "estavel", -1: "em queda"}.get(
            int(tr.get("momentum", 0)), "estavel"
        )
        interest_txt = (
            f"{tr['interest']:.0f}/100 no Google Trends"
            if isinstance(tr.get("interest"), (int, float))
            else "sem dado de Trends"
        )
        rationale = (
            f"query '{query}': {impressions:.0f} impressoes, posicao "
            f"{position:.1f}, CTR {ctr*100:.1f}%; {interest_txt} "
            f"({momentum_txt} 90d)"
        )
        return {
            "title": candidate,
            "keyword": query,
            "rationale": rationale,
            "score": round(value, 3),
            "trends": tr,
            "gsc": {"impressions": impressions, "position": position,
                    "ctr": ctr},
        }
    return None
