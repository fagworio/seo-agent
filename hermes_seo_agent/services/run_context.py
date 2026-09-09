"""Shared per-cycle connector context.

Connectors, the SQLite handle and expensive inventories are created/loaded once
per scheduler cycle and reused by commands that participate in that cycle. This
is what makes "every external dataset is collected at most once per cycle" work:
``posts()``/``sitemap_urls()`` return the same in-memory list, and the connectors
share a single ``Storage`` (instead of each HTTP request opening its own
``Storage`` + schema + migration, which was a large overhead).
"""
from __future__ import annotations

from typing import Any


class RunContext:
    def __init__(self, config: Any, storage: Any | None = None):
        self.config = config
        self._storage = storage
        self._wp = None
        self._static = None
        self._gsc = None
        self._ga4 = None
        self._posts = None
        self._sitemap_urls = None
        self._sitemap_entries = None
        # cache de datasets por janela (start, end) — a MESMA coleta GSC/GA4 é
        # reutilizada pelas etapas do ciclo (demand/title-opportunities/post-audit).
        self._gsc_by_page: dict[tuple[str, str, int], Any] = {}
        self._gsc_query_pages: dict[tuple[str, str, int], Any] = {}
        self._ga4_organic: dict[tuple[str, str, int, str, bool], Any] = {}

    def storage(self):
        if self._storage is None:
            from ..storage.db import Storage
            self._storage = Storage(self.config.sqlite_path)
        return self._storage

    def wordpress(self):
        if self._wp is None:
            from ..connectors.wordpress import WordPressClient
            self._wp = WordPressClient(self.config)
        return self._wp

    def static(self):
        if self._static is None:
            from ..connectors.static_site import StaticSiteClient
            # Passa o Storage compartilhado: _cached_get deixa de abrir um
            # Storage (schema+migração+commit) por request HTTP.
            self._static = StaticSiteClient(self.config, cache_store=self.storage())
        return self._static

    def search_console(self):
        if self._gsc is None and self.config.google_credentials:
            from ..connectors.search_console import SearchConsoleClient
            self._gsc = SearchConsoleClient(self.config)
        return self._gsc

    def analytics(self):
        if self._ga4 is None and self.config.ga4_property_id:
            from ..connectors.analytics import AnalyticsClient
            self._ga4 = AnalyticsClient(self.config)
        return self._ga4

    def posts(self):
        if self._posts is None:
            self._posts = self.wordpress().list_posts(status="publish")
        return self._posts

    def sitemap_entries(self):
        if self._sitemap_entries is None:
            self._sitemap_entries = self.static().all_sitemap_entries()
        return self._sitemap_entries

    def sitemap_urls(self):
        if self._sitemap_urls is None:
            self._sitemap_urls = [loc for loc, _ in self.sitemap_entries()]
        return self._sitemap_urls

    # -- cache de datasets GSC/GA4 por janela (P5) --------------------------

    def gsc_by_page(self, start: str, end: str, row_limit: int = 25_000):
        key = (start, end, row_limit)
        if key not in self._gsc_by_page:
            if self.search_console() is not None:
                self._gsc_by_page[key] = self._gsc.search_analytics_by_page(
                    start_date=start, end_date=end, row_limit=row_limit)
            else:
                self._gsc_by_page[key] = []
        return self._gsc_by_page[key]

    def gsc_query_pages(self, start: str, end: str, row_limit: int = 25_000):
        key = (start, end, row_limit)
        if key not in self._gsc_query_pages:
            if self.search_console() is not None:
                self._gsc_query_pages[key] = self._gsc.search_analytics_query_page(
                    start_date=start, end_date=end, row_limit=row_limit)
            else:
                self._gsc_query_pages[key] = []
        return self._gsc_query_pages[key]

    def ga4_organic(self, start: str, end: str, *, row_limit: int = 25_000,
                    expected_domain: str = ""):
        key = (start, end, row_limit, expected_domain, False)
        if key not in self._ga4_organic:
            if self.analytics() is not None:
                self._ga4_organic[key] = self._ga4.organic_landing_performance(
                    start_date=start, end_date=end, row_limit=row_limit,
                    expected_domain=expected_domain)
            else:
                self._ga4_organic[key] = {"rows": [], "row_count": 0,
                                          "unmatched": [], "quota": {}}
        return self._ga4_organic[key]

    def close(self):
        for client in (self._wp, self._static, self._gsc, self._ga4):
            if client is not None and hasattr(client, "close"):
                client.close()
        if self._storage is not None:
            self._storage.close()
            self._storage = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
