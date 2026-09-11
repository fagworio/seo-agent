"""Regressão #3: corpo de páginas vai para cache de DISCO, não para o SQLite.

Muitas páginas×HTML inflavam o http_cache (BLOB). Páginas agora guardam no
SQLite apenas ETag/Last-Modified/content_hash e o corpo gzip em arquivo no disco
(config.http_cache_dir). Sitemaps (pequenos, usados com frequência) continuam no
SQLite.
"""
import dataclasses
import gzip

import httpx

from hermes_seo_agent.config import Config
from hermes_seo_agent.connectors.base import HttpClient
from hermes_seo_agent.connectors.static_site import StaticSiteClient
from hermes_seo_agent.storage.db import Storage


def _cfg(tmp_path) -> Config:
    return Config(
        wordpress_url="http://x",
        sitemap_url="https://x.com/sitemap_index.xml",
        sqlite_path=str(tmp_path / "cache.db"),
        http_cache_dir=str(tmp_path / "http_cache"),
        google_credentials="", ga4_property_id="",
    )


def test_page_over_byte_limit_is_rejected(tmp_path):
    """Limite de bytes é enforçado (anti resposta gigante)."""
    from hermes_seo_agent.connectors.base import ConnectorError

    cfg = _cfg(tmp_path)
    cfg = dataclasses.replace(cfg, max_page_bytes=100)  # limite minúsculo

    def handler(request):
        return httpx.Response(200, text="x" * 5000,
                              headers={"content-length": "5000"})

    http = HttpClient(transport=httpx.MockTransport(handler))
    with Storage(cfg.sqlite_path) as store:
        static = StaticSiteClient(cfg, http=http, cache_store=store)
        try:
            static.fetch_page("https://x.com/p/")
            raised = False
        except ConnectorError:
            raised = True
        assert raised, "resposta acima de max_page_bytes deve ser rejeitada"
        static.close()


def test_page_body_goes_to_disk_not_sqlite(tmp_path):
    cfg = _cfg(tmp_path)
    body = "<html><head><title>P</title></head><body>oi</body></html>"

    def handler(request):
        return httpx.Response(200, text=body, headers={"etag": '"1"'})

    http = HttpClient(transport=httpx.MockTransport(handler))
    with Storage(cfg.sqlite_path) as store:
        static = StaticSiteClient(cfg, http=http, cache_store=store)
        page = static.fetch_page("https://x.com/p/")
        assert page.status_code == 200
        cached = store.get_http_cache("https://x.com/p/")
        # no SQLite: só metadados (body None), mas corpo no disco
        assert cached is not None
        assert cached["body"] is None
        assert cached["content_hash"]
        disk = static._disk_read("https://x.com/p/")
        assert disk is not None
        assert gzip.decompress(disk).decode() == body
        static.close()


def test_sitemap_body_stays_in_sqlite(tmp_path):
    cfg = _cfg(tmp_path)
    body = ("<?xml version='1.0'?>"
            "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
            "<url><loc>https://x.com/a/</loc></url></urlset>")

    def handler(request):
        return httpx.Response(200, text=body, headers={"etag": '"s"'})

    http = HttpClient(transport=httpx.MockTransport(handler))
    with Storage(cfg.sqlite_path) as store:
        static = StaticSiteClient(cfg, http=http, cache_store=store)
        urls = static.fetch_sitemap("https://x.com/sitemap_index.xml")
        assert urls == ["https://x.com/a/"]
        cached = store.get_http_cache("https://x.com/sitemap_index.xml")
        assert cached is not None
        assert cached["body"] is not None  # sitemap continua no SQLite
        static.close()


def test_page_304_rebuilds_from_disk(tmp_path):
    cfg = _cfg(tmp_path)
    body = "<html><head><title>P</title></head><body>oi</body></html>"

    def handler(request):
        # primeira: 200 com ETag; depois: 304 se o ETag for enviado
        if request.headers.get("If-None-Match") == '"1"':
            return httpx.Response(304, text="")
        return httpx.Response(200, text=body, headers={"etag": '"1"'})

    http = HttpClient(transport=httpx.MockTransport(handler))
    with Storage(cfg.sqlite_path) as store:
        static = StaticSiteClient(cfg, http=http, cache_store=store)
        p1 = static.fetch_page("https://x.com/p/")
        assert p1.status_code == 200
        # segunda: 304 -> reconstrói a partir do disco e devolve 200
        p2 = static.fetch_page("https://x.com/p/")
        assert p2.status_code == 200
        assert p2.html == body
        static.close()
