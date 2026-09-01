"""Sitemap diff tool — deterministic set operations between URL lists.

Usage (CLI): ``hermes-seo-agent diff-sitemap URL_A URL_B``
Pure function: ``sitemap_diff(a, b)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..inventory.reconcile import normalize_url


@dataclass
class SitemapDiff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    common: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "added": len(self.added),
            "removed": len(self.removed),
            "common": len(self.common),
        }


def sitemap_diff(a: list[str], b: list[str]) -> SitemapDiff:
    """Compare two URL lists normalized to path-space.

    - added:   in b but not in a
    - removed: in a but not in b
    - common:  in both
    """
    key_a = {normalize_url(u) for u in a}
    key_b = {normalize_url(u) for u in b}
    return SitemapDiff(
        added=sorted(key_b - key_a),
        removed=sorted(key_a - key_b),
        common=sorted(key_a & key_b),
    )
