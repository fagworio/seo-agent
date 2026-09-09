"""Shared per-cycle connector context.

Connectors and expensive inventories are created/loaded once per scheduler
cycle and reused by commands that participate in that cycle.
"""
from __future__ import annotations

from typing import Any


class RunContext:
    def __init__(self, config: Any):
        self.config = config
        self._wp = None
        self._static = None
        self._gsc = None
        self._ga4 = None
        self._posts = None
        self._sitemap_urls = None

    def wordpress(self):
        if self._wp is None:
            from ..connectors.wordpress import WordPressClient
            self._wp = WordPressClient(self.config)
        return self._wp

    def static(self):
        if self._static is None:
            from ..connectors.static_site import StaticSiteClient
            self._static = StaticSiteClient(self.config)
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

    def sitemap_urls(self):
        if self._sitemap_urls is None:
            self._sitemap_urls = self.static().all_sitemap_urls()
        return self._sitemap_urls

    def close(self):
        for client in (self._wp, self._static, self._gsc, self._ga4):
            if client is not None and hasattr(client, "close"):
                client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
