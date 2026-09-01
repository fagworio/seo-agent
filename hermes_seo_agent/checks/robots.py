"""robots.txt checks (deterministic)."""

from __future__ import annotations

from ..connectors.static_site import RobotsRules


def sitemap_urls_blocked(
    robots: RobotsRules,
    sitemap_urls: list[str],
    *,
    exclude_prefixes: tuple[str, ...] = ("/wp-", "/feed", "/author", "/category"),
) -> list[dict[str, str]]:
    """Return sitemap URLs blocked by robots.txt (ignoring admin/feed noise)."""
    blocked: list[dict[str, str]] = []
    for url in sitemap_urls:
        from urllib.parse import urlparse

        path = urlparse(url).path
        if path.startswith(exclude_prefixes):
            continue
        if robots.is_blocked(url):
            blocked.append({"url": url, "rule": _matching_rule(robots, url)})
    return blocked


def _matching_rule(robots: RobotsRules, url: str) -> str:
    from urllib.parse import urlparse

    path = urlparse(url).path
    for rule in robots.disallow:
        if rule == "/" and path != "/":
            return rule
        if rule and path.startswith(rule):
            return rule
    return ""
