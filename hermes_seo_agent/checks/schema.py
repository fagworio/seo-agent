"""Schema.org (JSON-LD) extraction + deterministic validation (Phase 5).

Extracts <script type="application/ld+json"> blocks from a page and validates
the minimal required fields per @type. Deterministic — no LLM.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..connectors.static_site import PageSnapshot

# Required fields per @type (minimal, per schema.org).
_REQUIRED_FIELDS: dict[str, list[str]] = {
    "Article": ["headline", "author", "datePublished"],
    "NewsArticle": ["headline", "author", "datePublished"],
    "BlogPosting": ["headline", "author", "datePublished"],
    "FAQPage": ["mainEntity"],
    "Product": ["name"],
    "Organization": ["name"],
    "WebSite": ["name"],
    "BreadcrumbList": ["itemListElement"],
}


def extract_json_ld(html: str) -> list[dict[str, Any]]:
    """All JSON-LD blocks in the page (best-effort parse of script tags)."""
    blocks: list[dict[str, Any]] = []
    pattern = re.compile(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(html or ""):
        raw = match.group(1).strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            blocks.extend(item for item in parsed if isinstance(item, dict))
        elif isinstance(parsed, dict):
            blocks.append(parsed)
    return blocks


def validate_schema(page: PageSnapshot) -> list[dict[str, Any]]:
    """Validate JSON-LD present on a page; return findings.

    - structured_data_invalid: malformed or missing required fields.
    - structured_data_missing: no JSON-LD at all (Article pages).
    """
    findings: list[dict[str, Any]] = []
    blocks = extract_json_ld(page.html if hasattr(page, "html") else "")
    if not blocks:
        # Only flag missing when the page looks like an article (has a title).
        if page.title:
            findings.append({
                "rule_id": "structured_data_missing",
                "url": page.url,
                "severity": "low",
                "detail": "no JSON-LD structured data found",
            })
        return findings

    for block in blocks:
        types = block.get("@type")
        if isinstance(types, str):
            types = [types]
        for type_name in types or []:
            required = _REQUIRED_FIELDS.get(type_name)
            if required is None:
                continue
            missing = [field for field in required if not block.get(field)]
            if missing:
                findings.append({
                    "rule_id": "structured_data_invalid",
                    "url": page.url,
                    "severity": "high",
                    "detail": f"{type_name} missing fields: {', '.join(missing)}",
                })
    return findings
