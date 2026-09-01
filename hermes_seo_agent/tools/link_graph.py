"""Editorial E0 — internal link graph (deterministic).

Builds a graph of internal links from crawled pages: for each URL, which
internal URLs it points to, which URLs point to it, and which pages are
orphans (no editorial in-links). Utility links (nav, footer, wp assets,
scripts) are excluded from the calculation.

Only paths within the crawled set are counted for in/out; the graph is
"within the crawl sample" and that is documented in the report.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from urllib.parse import urljoin, urlparse

from ..inventory.reconcile import normalize_url

# Paths that are navigation/utility, never editorial context.
UTILITY_PREFIXES = (
    "/assets/", "/wp-", "/autor/", "/contato/", "/politica-", "/buscar/",
    "/categorias/", "/tag/", "/feed", "/cdn-cgi/", "/categoria/",
    "/sobre/", "/termos", "/privacy",
)
# Assets/extensions that are never editorial destinations.
_NON_EDITORIAL_SUFFIXES = (
    ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".eot", ".pdf", ".xml", ".json",
)


def is_editorial_target(url: str) -> bool:
    """True when a URL is a plausible editorial page (not asset/utility)."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    if path == "/" or path == "":
        return True  # home is editorial-ish (hub)
    if path.endswith(_NON_EDITORIAL_SUFFIXES):
        return False
    if path.startswith(UTILITY_PREFIXES):
        return False
    if "?" in path or "#" in path:
        return False
    return True


def resolve_links(source_url: str, links: list[str]) -> list[str]:
    """Absolute internal URLs from a page's href list (deterministic)."""
    resolved: list[str] = []
    for href in links:
        try:
            absolute = urljoin(source_url, href)
        except ValueError:
            continue
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        resolved.append(absolute)
    return resolved


def build_graph(pages: list[Any]) -> dict[str, Any]:
    """pages: list of objects with .url and .links (PageSnapshot-like).

    Returns edges (source -> targets), in/out counts, orphans and hubs.
    """
    page_keys = {normalize_url(p.url): p.url for p in pages}
    edges: dict[str, set[str]] = defaultdict(set)

    for page in pages:
        src_key = normalize_url(page.url)
        for href in resolve_links(page.url, page.links):
            if not is_editorial_target(href):
                continue
            target_key = normalize_url(href)
            if target_key == src_key:
                continue
            # only count edges to pages present in the crawled set
            if target_key in page_keys:
                edges[src_key].add(target_key)

    in_counts: dict[str, int] = defaultdict(int)
    out_counts: dict[str, int] = {}
    for src_key, targets in edges.items():
        out_counts[src_key] = len(targets)
        for target_key in targets:
            in_counts[target_key] += 1

    orphans = [page_keys[k] for k in page_keys if in_counts.get(k, 0) == 0]
    hubs = sorted(
        ((page_keys[k], count) for k, count in in_counts.items()),
        key=lambda pair: -pair[1],
    )[:10]

    return {
        "crawled_pages": len(pages),
        "edges": {k: sorted(v) for k, v in edges.items()},
        "in_counts": dict(in_counts),
        "out_counts": out_counts,
        "orphans": sorted(orphans),
        "hubs": hubs,
    }
