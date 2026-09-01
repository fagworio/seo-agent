"""Editorial E4 — contextual, advisory internal-link suggestions."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from ..tools.link_graph import is_editorial_target

_STOP = {"o", "a", "os", "as", "de", "da", "do", "das", "dos", "e", "em", "no", "na", "para", "com", "um", "uma", "que", "por", "sobre", "como", "qual", "quais", "quanto", "quando", "onde", "quem"}


def _tokens(value: str) -> set[str]:
    words = re.findall(r"[a-zà-ú]{3,}", (value or "").lower())
    return {word for word in words if word not in _STOP}


def _context_tokens(url: str, context: dict[str, Any]) -> set[str]:
    fallback = urlparse(url).path.strip("/").replace("-", " ")
    return _tokens(" ".join([context.get("title", ""), context.get("h1", ""), *context.get("h2s", []), fallback]))


def _excerpt(text: str, terms: set[str]) -> str:
    for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
        if len(_tokens(sentence) & terms) >= min(2, len(terms)):
            return sentence.strip()[:240]
    return ""


def _anchor(context: dict[str, Any], terms: set[str]) -> str:
    title = context.get("title", "") or context.get("h1", "")
    if title:
        return " ".join(title.split()[:10])
    return " ".join(sorted(terms)[:5])


def suggest_interlinks(*, sources: list[str], targets: list[str], existing_out: dict[str, set[str]],
                       contexts: dict[str, dict[str, Any]] | None = None,
                       limit_per_source: int = 3, max_total: int = 100) -> list[dict[str, Any]]:
    """Suggest links only when page context establishes a thematic relation."""
    contexts = contexts or {}
    suggestions: list[dict[str, Any]] = []
    in_links = _in_link_counts(existing_out)
    target_tokens = {target: _context_tokens(target, contexts.get(target, {})) for target in targets}
    for source in sources:
        source_context = contexts.get(source, {})
        if source_context.get("is_noindex") or source_context.get("status_code", 200) >= 400:
            continue
        source_tokens = _context_tokens(source, source_context)
        if not source_tokens:
            continue
        candidates: list[tuple[int, int, str, set[str]]] = []
        for target in targets:
            target_context = contexts.get(target, {})
            if target == source or target in existing_out.get(source, set()) or not is_editorial_target(target):
                continue
            if target_context.get("is_noindex") or target_context.get("status_code", 200) >= 400:
                continue
            canonical = target_context.get("canonical", "")
            if canonical and canonical.rstrip("/") != target.rstrip("/"):
                continue
            shared = source_tokens & target_tokens[target]
            if len(shared) >= 2:
                candidates.append((len(shared), in_links.get(target, 0), target, shared))
        candidates.sort(key=lambda candidate: (-candidate[0], candidate[1], candidate[2]))
        for shared_count, target_in_links, target, shared in candidates[:limit_per_source]:
            excerpt = _excerpt(source_context.get("body_text", ""), shared)
            suggestions.append({"source_url": source, "target_url": target,
                                "reason": f"relação temática por {shared_count} termos: {', '.join(sorted(shared)[:4])}; destino com {target_in_links} links de entrada",
                                "anchor": _anchor(contexts.get(target, {}), shared),
                                "context_excerpt": excerpt,
                                "editorial_note": "inserir apenas se o trecho realmente se beneficiar do aprofundamento"})
        if len(suggestions) >= max_total:
            break
    return suggestions


def _in_link_counts(existing_out: dict[str, set[str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for targets in existing_out.values():
        for target in targets:
            counts[target] = counts.get(target, 0) + 1
    return counts
