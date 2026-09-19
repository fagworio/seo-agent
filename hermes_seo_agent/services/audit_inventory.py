"""SEO-INC-003/015: inventário incremental de URLs para o audit.

O audit antigo andava um CURSOR sobre o sitemap ("próximas 500 posições") e um
fingerprint global decidia se valia a pena andar. Isso tem dois defeitos de
escala: (a) o post que mudou pode nem estar nas 500 sorteadas; (b) com o TTL de
24h, cobrir 19 mil URLs levava semanas.

Aqui a comparação é por URL: o estado barato (WordPress ``modified`` + sitemap
``lastmod``) é confrontado com ``url_audit_state``. O que mudou vira ``dirty``
com um motivo, e o audit passa a consumir uma fila de URLs relevantes.

SEO-INC-015 (custo por ciclo): a primeira versão fazia por post
1 SELECT + 1 UPSERT + 1 COMMIT — medido em **1.900 commits para 1.900 posts**
(projeção ~19 mil commits por ciclo de 18.971). Agora o estado inteiro vem em
um SELECT, a comparação é em memória, apenas as URLs que realmente mudaram
entram no lote, e a gravação é um único ``executemany`` + um ``commit``.
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


def _classify(state: dict[str, Any] | None, *, wp_modified: str, lastmod: str,
              in_sitemap: bool) -> str:
    """Motivo do dirty ("" quando nada relevante mudou)."""
    if state is None:
        return DIRTY_NEW
    if wp_modified and state["wp_modified"] and wp_modified != state["wp_modified"]:
        return DIRTY_WP_MODIFIED
    if in_sitemap and lastmod and state["sitemap_lastmod"] and lastmod != state["sitemap_lastmod"]:
        return DIRTY_SITEMAP_MODIFIED
    if not in_sitemap:
        return DIRTY_MISSING_SITEMAP
    return ""


def sync_audit_inventory(
    storage: Any,
    posts: list[dict[str, Any]],
    sitemap_entries: Iterable[tuple[str, str]],
    *,
    static_host: str,
) -> dict[str, int]:
    """Marca dirty (novo/modificado/sem sitemap) e devolve o resumo do delta.

    Escrita em lote (SEO-INC-015): só as URLs cujo estado realmente mudou
    entram no UPSERT; o resto é contabilizado em memória e não toca o banco.
    """
    sitemap = _sitemap_index(sitemap_entries)
    # 1 SELECT grande em vez de ~19 mil `WHERE url = ?`.
    states = (storage.get_all_url_audit_states()
              if hasattr(storage, "get_all_url_audit_states") else {})
    resumo = {
        "known": 0, "written": 0, DIRTY_NEW: 0, DIRTY_WP_MODIFIED: 0,
        DIRTY_SITEMAP_MODIFIED: 0, DIRTY_MISSING_SITEMAP: 0, "unchanged": 0,
    }
    vistos: set[str] = set()
    mudancas: list[dict[str, Any]] = []

    for post in posts:
        link = str(post.get("link") or "")
        if not link:
            continue
        url = wp_link_to_static(link, static_host)
        key = normalize_url(url)
        if not key or key in vistos:
            continue
        vistos.add(key)

        lastmod = sitemap.get(key, "")
        in_sitemap = key in sitemap
        wp_modified = str(post.get("modified") or "")
        state = states.get(key)
        reason = _classify(state, wp_modified=wp_modified, lastmod=lastmod,
                           in_sitemap=in_sitemap)

        resumo["known"] += 1
        if reason:
            resumo[reason] = resumo.get(reason, 0) + 1
            mudancas.append({
                "url": url, "wp_post_id": post.get("id"),
                "wp_modified": wp_modified, "sitemap_lastmod": lastmod,
                "dirty": True, "dirty_reason": reason,
            })
            continue

        resumo["unchanged"] += 1
        # Unchanged não escreve — só se o estado local divergir (ex.: lastmod
        # novo sem mudança de conteúdo). Aí atualiza sem marcar dirty.
        if (state is None or state["wp_modified"] != wp_modified
                or state["sitemap_lastmod"] != lastmod):
            mudancas.append({
                "url": url, "wp_post_id": post.get("id"),
                "wp_modified": wp_modified, "sitemap_lastmod": lastmod,
                "dirty": bool(state and state.get("dirty")),
                "dirty_reason": (state or {}).get("dirty_reason") or "",
            })

    batch = getattr(storage, "upsert_url_audit_states_batch", None)
    if callable(batch):
        resumo["written"] = int(batch(mudancas) or 0)
    else:  # compatibilidade: storages antigos gravam um a um
        for row in mudancas:
            storage.upsert_url_audit_state(**row)
        resumo["written"] = len(mudancas)
    return resumo
