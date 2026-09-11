"""Canonical + meta title/description checks (deterministic)."""

from __future__ import annotations

import html
import re

from ..connectors.static_site import PageSnapshot

# Sufixo de site name que o template do Eleventy adiciona ao <title> renderizado
# ("<título> — UnicornioHater"). Ele NAO faz parte do titulo editavel
# (rank_math_title) — medir o <title> cru gerava title_too_long fantasma em
# todo post cujo rank_math <=65 chars (59 + sufixo 17 = 76 > 65). O Google
# usa o rank_math_title como titulo SERP e exibe o site name em separado.
_SITE_NAME_SUFFIX = re.compile(r"\s*[—–-]\s*UnicornioHater\s*$", re.IGNORECASE)


def _strip_site_name(title: str) -> str:
    """Remove o site name do template E desescapa entidades HTML.

    O WP REST entrega title.rendered com entidades (&#8216;); o render
    (autoescape do nunjucks) escapa de novo -> &amp;#8216; no <title>, que
    infla o comprimento em ~10 chars por apóstrofo e gerava title_too_long
    FALSO (título real de 54 chars medido como 78). Unescape duplo defensivo
    cobre os dois níveis.
    """
    text = html.unescape(html.unescape(title or ""))
    return _SITE_NAME_SUFFIX.sub("", text).strip()


def canonical_findings(page: PageSnapshot, *, expected_canonical: str = "") -> list[dict[str, str]]:
    """Return canonical-related findings for one page."""
    findings: list[dict[str, str]] = []
    if not page.canonical:
        findings.append({"rule_id": "canonical_missing", "detail": "page has no rel=canonical"})
        return findings

    if expected_canonical:
        normalized_expected = _normalize(expected_canonical)
        normalized_actual = _normalize(page.canonical)
        if normalized_actual and normalized_actual != normalized_expected:
            findings.append(
                {
                    "rule_id": "canonical_conflict",
                    "detail": f"canonical {page.canonical} != expected {expected_canonical}",
                }
            )
    return findings


def meta_findings(page: PageSnapshot) -> list[dict[str, str]]:
    """Return title/meta-description findings for one page."""
    findings: list[dict[str, str]] = []
    title = _strip_site_name(page.title)
    if not title:
        findings.append({"rule_id": "title_missing", "detail": "page has no <title>"})
    elif len(title) > 65:
        findings.append(
            {"rule_id": "title_too_long", "detail": f"title has {len(title)} chars (> 65)"}
        )

    if not page.meta_description:
        findings.append({"rule_id": "meta_missing", "detail": "page has no meta description"})
    elif len(page.meta_description) > 165:
        findings.append(
            {
                "rule_id": "meta_too_long",
                "detail": f"meta description has {len(page.meta_description)} chars (> 165)",
            }
        )
    return findings


def duplicate_title_findings(pages: list[PageSnapshot]) -> list[dict[str, str]]:
    """Group pages by normalized title; report duplicates (deterministic hash)."""
    buckets: dict[str, list[str]] = {}
    for page in pages:
        key = _normalize(page.title)
        if key:
            buckets.setdefault(key, []).append(page.url)
    findings = []
    for _title, urls in buckets.items():
        if len(urls) > 1:
            findings.append(
                {
                    "rule_id": "title_duplicate",
                    "detail": f"{len(urls)} pages share the same title",
                    "urls": urls,
                }
            )
    return findings


def _normalize(value: str) -> str:
    import re

    value = (value or "").strip().lower()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"[^a-z0-9\u00e0-\u00ff ]", "", value)
    return value.strip()
