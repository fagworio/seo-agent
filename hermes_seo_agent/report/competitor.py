"""R7 — Competitor Corpus (crawler determinístico, SÓ metadados editoriais).

Extrai de sitemap/RSS de concorrentes apenas sinais editoriais: URL, título
(derivado do slug), data de publicação e tópicos/entidades — SEM copiar
conteúdo. Resolve cada documento para os tópicos do NOSSO topic graph (para
comparação direta no Content Gap Engine) com fallback por slug. Zero LLM.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
from typing import Any

from ..connectors.base import ConnectorError, HttpClient
from .topics import ENTITY_ALIASES, canonical_entity, normalize_entity

_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_TOKEN_STOP = {"de", "da", "do", "das", "dos", "e", "em", "no", "na", "para",
               "com", "um", "uma", "que", "por", "sobre", "como", "o", "a",
               "os", "as", "the", "and", "of", "to", "em", "o", "a"}


def _slug_title(url: str, title: str = "") -> str:
    if title and title.strip():
        return title.strip()
    path = urlparse(url or "").path.rstrip("/")
    slug = path.split("/")[-1] if path else ""
    words = [w for w in re.split(r"[-_]+", slug) if w.lower() not in _TOKEN_STOP]
    return " ".join(words).title() or (url or "")


def _topic_tokens(text: str) -> set[str]:
    return {w for w in normalize_entity(text).split() if w not in _TOKEN_STOP}


def resolve_topic_keys(url: str, title: str, our_graph: list[dict[str, Any]],
                       *, max_keys: int = 3) -> list[str]:
    """Resolve um documento de concorrente para tópicos do NOSSO topic graph.

    Prioriza: (1) entidades de franquia (aliases) presentes no slug/título;
    (2) clusters do nosso graph com maior sobreposição de tokens; fallback:
    um tópico derivado de 2 tokens significativos do slug (sub-tópico).
    """
    text = normalize_entity(f"{_slug_title(url, title)} {url}")
    toks = _topic_tokens(text)
    keys: list[tuple[float, str]] = []

    # (1) aliases de franquia
    for alias, canon in ENTITY_ALIASES.items():
        if alias and alias in text:
            keys.append((1.0, canon))
    # (2) nosso topic graph: sobreposição de tokens
    for cluster in our_graph or []:
        ent = normalize_entity(cluster.get("entity", ""))
        if not ent:
            continue
        overlap = len(toks & set(ent.split()))
        if overlap >= 1:
            keys.append((float(overlap), cluster["entity"]))

    if keys:
        keys.sort(key=lambda k: (-k[0], k[1]))
        seen: list[str] = []
        for _score, key in keys:
            if key not in seen:
                seen.append(key)
            if len(seen) >= max_keys:
                break
        return seen

    # (3) fallback: sub-tópico a partir de tokens significativos do slug
    slug_tokens = [w for w in normalize_entity(urlparse(url).path).split()
                   if w not in _TOKEN_STOP][:3]
    if slug_tokens:
        return [" ".join(slug_tokens)]
    return []


def extract_entries(xml_text: str, domain: str, our_graph: list[dict[str, Any]],
                    *, is_index: bool = False) -> list[dict[str, Any]]:
    """Extrai entradas de um sitemap (urlset ou sitemapindex) determinístico."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ConnectorError(f"sitemap inválido: {exc}") from exc
    node = f"{_NS}sitemap" if is_index else f"{_NS}url"
    entries: list[dict[str, Any]] = []
    for el in root.iter(node):
        loc = el.find(f"{_NS}loc")
        if loc is None or not (loc.text or "").strip():
            continue
        url = loc.text.strip()
        lastmod = el.find(f"{_NS}lastmod")
        published_at = (lastmod.text or "").strip() if lastmod is not None else ""
        title = _slug_title(url)
        entries.append({
            "domain": domain,
            "url": url,
            "title": title,
            "published_at": published_at,
            "entities": resolve_topic_keys(url, title, our_graph),
        })
    return entries


def crawl_domain(domain: str, our_graph: list[dict[str, Any]], *,
                 http: HttpClient | None = None,
                 sitemap_url: str | None = None) -> list[dict[str, Any]]:
    """Baixa o sitemap do concorrente e devolve as entradas (metadados)."""
    http = http or HttpClient(user_agent="hermes-seo-agent/0.1 (competitor-corpus)")
    base = domain if domain.startswith("http") else f"https://{domain}"
    candidates = [sitemap_url] if sitemap_url else [
        f"{base}/sitemap_index.xml", f"{base}/wp-sitemap.xml", f"{base}/sitemap.xml",
    ]
    entries: list[dict[str, Any]] = []
    for url in candidates:
        try:
            resp = http.get(url)
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        text = resp.text
        if "<sitemapindex" in text:
            for child_url in _child_sitemaps(text):
                try:
                    child = http.get(child_url)
                except Exception:
                    continue
                if child.status_code == 200:
                    entries.extend(extract_entries(child.text, domain, our_graph))
        else:
            entries.extend(extract_entries(text, domain, our_graph))
    return entries


def _child_sitemaps(xml_text: str) -> list[str]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out = []
    for el in root.iter(f"{_NS}sitemap"):
        loc = el.find(f"{_NS}loc")
        if loc is not None and (loc.text or "").strip():
            out.append(loc.text.strip())
    return out
