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
