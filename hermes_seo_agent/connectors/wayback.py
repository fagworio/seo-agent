"""Wayback Machine connector (Phase 5) — archive evidence before removals.

Used by the safety model: before any approval_required removal decision, the
agent checks whether a URL has archived history (never delete without knowing
what exists). Deterministic, free, no key required.
"""

from __future__ import annotations

from typing import Any

from ..config import Config
from .base import ConnectorError, HttpClient

_AVAILABILITY = "https://archive.org/wayback/available"
_CDX = "https://web.archive.org/cdx/search/cdx"


class WaybackClient:
    def __init__(self, config: Config, http: HttpClient | None = None):
        self.config = config
        self.http = http or HttpClient(timeout=config.http_timeout)

    def availability(self, url: str) -> dict[str, Any]:
        """Latest archived snapshot of a URL (null when never archived)."""
        response = self.http.get(
            _AVAILABILITY, params={"url": url}, headers={"Accept": "application/json"}
        )
        if response.status_code != 200:
            raise ConnectorError(f"Wayback availability failed: HTTP {response.status_code}")
        data = response.json()
        snapshot = ((data or {}).get("archived_snapshots") or {}).get("closest") or {}
        if not snapshot or not snapshot.get("url"):
            return {"url": url, "archived": False, "snapshot_url": None, "timestamp": None}
        return {
            "url": url,
            "archived": True,
            "snapshot_url": snapshot.get("url"),
            "timestamp": snapshot.get("timestamp"),
            "status": snapshot.get("status"),
        }

    def snapshot_count(self, url: str, *, limit: int = 10_000) -> int:
        """Number of archived snapshots for a URL (CDX API)."""
        response = self.http.get(
            _CDX,
            params={"url": url, "output": "json", "limit": str(limit), "fl": "timestamp"},
        )
        if response.status_code != 200:
            raise ConnectorError(f"Wayback CDX failed: HTTP {response.status_code}")
        rows = response.json()
        # CDX returns [["timestamp", ...], ["20260101...", ...], ...]
        return max(0, len(rows) - 1) if isinstance(rows, list) else 0

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> "WaybackClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
