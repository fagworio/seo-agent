"""Title opportunity research — deterministic, grounded in GSC queries.

The "correct" title is not opinion: it is anchored on the actual queries that
bring impressions to the page (Search Console Search Analytics). These helpers
pick the best query and build a candidate title from it. The candidate is a
STARTING POINT for the agent/human — wording still benefits from judgment, but
the research (which keywords, which intent) is data, not guesswork.
"""

from __future__ import annotations

import re
from typing import Any

# Prepositions/articles that stay lowercase in a title-case candidate.
_SMALL = {"a", "o", "os", "as", "de", "da", "do", "das", "dos", "e", "em",
          "no", "na", "nos", "nas", "para", "com", "um", "uma", "uns", "umas",
          "que", "por", "até", "the", "of", "and", "in", "to"}


def pick_top_query(rows: list[dict[str, Any]]) -> str:
    """Choose the highest-value query: meaningful impressions, best position.

    Prefers queries with >=2 impressions; among them the best (lowest)
    average position, then most impressions. Falls back to the raw top row.
    """
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
    """Build a clean, title-cased candidate from a raw search query."""
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
