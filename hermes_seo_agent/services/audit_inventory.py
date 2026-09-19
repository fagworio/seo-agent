"""SEO-INC-003: inventário incremental de URLs para o audit.

O audit antigo andava um CURSOR sobre o sitemap ("próximas 500 posições") e um
fingerprint global decidia se valia a pena andar. Isso tem dois defeitos de
escala: (a) o post que mudou pode nem estar nas 500 sorteadas; (b) com o TTL de
24h, cobrir 19 mil URLs levava semanas.

Aqui a comparação é por URL: o estado barato (WordPress ``modified`` + sitemap
``lastmod``) é confrontado com ``url_audit_state``. O que mudou vira ``dirty``
com um motivo, e o audit passa a consumir uma fila de URLs relevantes.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..inventory.reconcile import normalize_url, wp_link_to_static

# Motivos de dirty (ordem de prioridade usada por Storage.get_urls_for_audit).
DIRTY_NEW = "new_url"
DIRTY_WP_MODIFIED = "wordpress_modified"
DIRTY_SITEMAP_MODIFIED = "sitemap_modified"
DIRTY_MISSING_SITEMAP = "missing_from_sitemap"


def _sitemap_index(sitemap_entries: Iterable[tuple[str, str]]) -> dict[str, str]:
    """path (normalizado) -> lastmod do sitemap."""
    out: dict[str, str] = {}
    for loc, lastmod in sitemap_entries:
        key = normalize_url(loc)
        if key:
            out[key] = lastmod or ""
    return out


def sync_audit_inventory(
    storage: Any,
    posts: list[dict[str, Any]],
    sitemap_entries: Iterable[tuple[str, str]],
    *,
    static_host: str,
) -> dict[str, int]:
    """Marca dirty (novo/modificado/sem sitemap) e devolve o resumo do delta."""
    sitemap = _sitemap_index(sitemap_entries)
    resumo = {
        "known": 0, "new_url": 0, DIRTY_WP_MODIFIED: 0,
        DIRTY_SITEMAP_MODIFIED: 0, DIRTY_MISSING_SITEMAP: 0, "unchanged": 0,
    }
    vistos: set[str] = set()
    for post in posts:
        link = str(post.get("link") or "")
        if not link:
            continue
        url = wp_link_to_static(link, static_host)
        key = normalize_url(url)
        if not key or key in vistos:
            continue
        vistos.add(key)

        state = storage.get_url_audit_state(url)
        lastmod = sitemap.get(key, "")
        in_sitemap = key in sitemap
        wp_modified = str(post.get("modified") or "")

        reason = ""
        if state is None:
            reason = DIRTY_NEW
        elif wp_modified and state["wp_modified"] and wp_modified != state["wp_modified"]:
            reason = DIRTY_WP_MODIFIED
        elif in_sitemap and lastmod and state["sitemap_lastmod"] and lastmod != state["sitemap_lastmod"]:
            reason = DIRTY_SITEMAP_MODIFIED
        elif not in_sitemap:
            reason = DIRTY_MISSING_SITEMAP

        storage.upsert_url_audit_state(
            url=url,
            wp_post_id=post.get("id"),
            wp_modified=wp_modified,
            sitemap_lastmod=lastmod,
            dirty=bool(reason),
            dirty_reason=reason,
        )
        resumo["known"] += 1
        if reason:
            resumo[reason] = resumo.get(reason, 0) + 1
        else:
            resumo["unchanged"] += 1
    return resumo
