"""M2 — seleção de fonte do corpus editorial.

Prefere a API do WordPress (evita o bot-fight do Cloudflare no sitemap
estático e usa o CONTEÚDO PRINCIPAL do post, sem o chroma do site). Fallback
para o sitemap estático (comportamento legado, inalterado). Determinístico.
"""
from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any, Callable

from ..config import Config
from ..connectors.base import ConnectorError
from ..connectors.static_site import StaticSiteClient
from ..connectors.wordpress import WordPressClient

_TAG = re.compile(r"<[^>]+>")
_H2 = re.compile(r"<h2[^>]*>(.*?)</h2>", re.I | re.S)


def _html_text(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub(" ", html or "")).strip()


def _h2_texts(html: str) -> list[str]:
    out: list[str] = []
    for m in _H2.finditer(html or ""):
        text = re.sub(r"\s+", " ", _TAG.sub(" ", m.group(1))).strip()
        if text:
            out.append(text)
    return out[:10]


class CorpusSource:
    """Fonte de conteúdo do corpus: lista de URLs + fetch(url) -> PageSnapshot-like."""

    def __init__(self, *, name: str, urls: list[str],
                 fetch: Callable[[str], Any], client: Any):
        self.name = name
        self.urls = urls
        self.fetch = fetch
        self._client = client

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass


def corpus_source(config: Config) -> CorpusSource:
    """Escolhe a fonte: API do WordPress primeiro; sitemap estático por fallback."""
    if config.wordpress_url and config.wordpress_api_base:
        try:
            wp = WordPressClient(config)
            posts = wp.list_posts(status="publish", fields="id,link,modified")
            links = [(p.get("link", "").strip().rstrip("/"), p.get("id"))
                     for p in posts if p.get("link")]
            by_url = {u: pid for u, pid in links}

            def _post_snapshot(url: str) -> SimpleNamespace:
                pid = by_url.get(url.rstrip("/"))
                if pid is None:
                    raise ConnectorError(f"URL não é um post publicado do WordPress: {url}")
                post = wp.get_post(int(pid), context="edit")
                title = ((post.get("title") or {}).get("rendered") or "").strip()
                raw = ((post.get("content") or {}).get("rendered") or "")
                return SimpleNamespace(
                    url=url, status_code=200, title=title,
                    h1=[title] if title else [],
                    h2s=_h2_texts(raw),
                    body_text=_html_text(raw),
                    canonical=(post.get("link") or url),
                )

            if links:
                return CorpusSource(name="wordpress", urls=[u for u, _ in links],
                                    fetch=_post_snapshot, client=wp)
            wp.close()
        except Exception:
            pass

    # Fallback: sitemap estático (comportamento legado).
    static = StaticSiteClient(config)
    urls = static.all_sitemap_urls()
    return CorpusSource(name="static", urls=urls, fetch=static.fetch_page, client=static)
