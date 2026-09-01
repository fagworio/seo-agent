"""Reconciliation logic — pure, deterministic, unit-testable.

The public domain is the static site (www.unicorniohater.com.br); WordPress
links carry the internal host (e.g. wordpress.dvl.to:8080 or
prod.unicorniohater.com.br). Reconciliation maps both onto one canonical
path-space before comparing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class ReconcileReport:
    wp_posts: list[dict] = field(default_factory=list)
    sitemap_urls: list[str] = field(default_factory=list)
    static_urls: list[str] = field(default_factory=list)
    in_sitemap: list[str] = field(default_factory=list)
    missing_from_sitemap: list[str] = field(default_factory=list)
    orphan_in_sitemap: list[str] = field(default_factory=list)
    wp_static_mismatch: list[dict] = field(default_factory=list)
    static_orphan: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "wp_posts": len(self.wp_posts),
            "sitemap_urls": len(self.sitemap_urls),
            "static_urls": len(self.static_urls),
            "in_sitemap": len(self.in_sitemap),
            "missing_from_sitemap": len(self.missing_from_sitemap),
            "orphan_in_sitemap": len(self.orphan_in_sitemap),
            "wp_static_mismatch": len(self.wp_static_mismatch),
            "static_orphan": len(self.static_orphan),
        }


def normalize_url(url: str) -> str:
    """Canonical comparison key — PATH-ONLY, host-independent.

    The WordPress host (wordpress.dvl.to:8080 / prod.unicorniohater.com.br)
    differs from the static host (www.unicorniohater.com.br); only the path
    (slug) is stable across surfaces. Scheme stripped, trailing slash
    normalized, query/fragment dropped."""
    parsed = urlparse(url or "")
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") + "/"
    return path


def wp_link_to_static(wp_link: str, static_host: str) -> str:
    """Map a WordPress post link to its expected static-site URL."""
    parsed = urlparse(wp_link or "")
    path = parsed.path or "/"
    scheme = parsed.scheme or "https"
    return f"{scheme}://{static_host.rstrip('/')}{path}"


def reconcile(
    wp_posts: list[dict],
    sitemap_urls: list[str],
    *,
    static_urls: list[str] | None = None,
    static_host: str = "www.unicorniohater.com.br",
) -> ReconcileReport:
    """Three-way reconciliation.

    - wp_posts: list of dicts with at least ``link``.
    - sitemap_urls: URLs from the static site sitemap tree.
    - static_urls: optional list of URLs actually rendered by the static site.
    """
    report = ReconcileReport(
        wp_posts=wp_posts,
        sitemap_urls=sitemap_urls,
        static_urls=static_urls or [],
    )

    sitemap_keys = {normalize_url(u) for u in sitemap_urls}

    # WP post paths (path-space only, since hosts differ WP vs static).
    wp_paths: dict[str, dict] = {}
    for post in wp_posts:
        link = post.get("link") or ""
        path = normalize_url(link)
        wp_paths.setdefault(path, []).append(post)

    for key in sorted(wp_paths):
        if key in sitemap_keys:
            report.in_sitemap.append(key)
        else:
            report.missing_from_sitemap.append(key)

    # Static mismatch: WP post whose expected static URL is not rendered.
    if static_urls:
        static_keys = {normalize_url(u) for u in static_urls}
        for post in wp_posts:
            expected = wp_link_to_static(post.get("link") or "", static_host)
            if normalize_url(expected) not in static_keys:
                report.wp_static_mismatch.append(
                    {"wp_link": post.get("link"), "expected_static": expected}
                )
        for key in sorted(static_keys - sitemap_keys):
            report.static_orphan.append(key)

    # Sitemap entries with no WP counterpart (path-space).
    wp_keys = set(wp_paths)
    for key in sorted(sitemap_keys - wp_keys):
        report.orphan_in_sitemap.append(key)

    return report
