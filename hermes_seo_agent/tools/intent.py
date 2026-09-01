"""Editorial E1 — demand base: query normalization + intent classification.

Deterministic rules only: normalize obvious query variations (accents, case,
spaces) and classify intent (question / comparison / news / brand /
informational). No model calls.
"""

from __future__ import annotations

import re
import unicodedata

_QUESTION_PREFIXES = (
    "como ", "o que", "qual ", "quanto", "por que", "porque", "quando",
    "onde ", "quem ", "para que", "sera que", "será que", "pode ", "é ", "e ",
    "tem ", "existe ", "quais ",
)
_COMPARISON_WORDS = ("vs", "versus", "melhor", "top", "comparacao", "diferenca", " ou ")
_NEWS_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_BRAND = ("unicorniohater", "unicórniohater")
_ACCENTS = {
    "á": "a", "à": "a", "ã": "a", "â": "a", "é": "e", "ê": "e", "í": "i",
    "ó": "o", "ô": "o", "õ": "o", "ú": "u", "ü": "u", "ç": "c",
}


def normalize_query(query: str) -> str:
    """Lowercase, strip accents, collapse whitespace, drop trailing '?'."""
    q = (query or "").strip().lower()
    q = "".join(_ACCENTS.get(ch, ch) for ch in q)
    q = re.sub(r"\s+", " ", q)
    q = q.rstrip("?")
    return q.strip()


def classify_intent(query: str) -> str:
    """One of: question | comparison | news | brand | informational | unknown."""
    had_question_mark = (query or "").strip().endswith("?")
    q = normalize_query(query)
    if not q:
        return "unknown"

    if any(word in q for word in _BRAND):
        return "brand"

    if any(word in q for word in _COMPARISON_WORDS):
        return "comparison"

    if _NEWS_YEAR.search(q) or any(kw in q for kw in ("lancamento", "trailer", "chega", "estreia")):
        return "news"

    if had_question_mark or any(q.startswith(prefix) for prefix in _QUESTION_PREFIXES):
        return "question"

    if len(q.split()) >= 2:
        return "informational"

    return "unknown"


def group_variations(queries: list[str]) -> dict[str, list[str]]:
    """Group obvious query variations (same normalized key)."""
    groups: dict[str, list[str]] = {}
    for query in queries:
        key = normalize_query(query)
        groups.setdefault(key, []).append(query)
    return groups
