"""Google PageSpeed Insights API connector (Phase 3)."""

from __future__ import annotations

from typing import Any

from ..config import Config
from .base import ConnectorError, HttpClient

_BASE = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


class PageSpeedClient:
    def __init__(self, config: Config, http: HttpClient | None = None):
        self.config = config
        self.http = http or HttpClient(timeout=config.http_timeout)

    def run(self, url: str, *, strategy: str = "mobile") -> dict[str, Any]:
        if not self.config.pagespeed_api_key:
            raise ConnectorError("PageSpeed not configured: set PAGESPEED_API_KEY")
        response = self.http.get(
            _BASE,
            params={
                "url": url,
                "strategy": strategy,
                "key": self.config.pagespeed_api_key,
                "category": "performance",
            },
        )
        if response.status_code != 200:
            raise ConnectorError(f"PageSpeed failed for {url}: HTTP {response.status_code} {response.text[:200]}")
        data = response.json()
        return data if isinstance(data, dict) else {}

    @staticmethod
    def cwv_values(result: dict[str, Any]) -> dict[str, float]:
        """Extract LCP/CLS/INP from the lighthouseResult.audits section.

        PSI units: LCP in ms, CLS unitless, INP in ms. Normalized to the same
        units CrUX uses (LCP seconds) so cwv_findings can compare uniformly.
        """
        audits = (result.get("lighthouseResult") or {}).get("audits") or {}
        values: dict[str, float] = {}
        mapping = {
            "largest-contentful-paint": "lcp",
            "cumulative-layout-shift": "cls",
            "interaction-to-next-paint": "inp",
        }
        for audit_id, metric in mapping.items():
            numeric = audits.get(audit_id, {}).get("numericValue")
            if isinstance(numeric, (int, float)):
                value = round(float(numeric), 3)
                if metric == "lcp":
                    value = round(value / 1000, 3)  # ms -> s
                values[metric] = value
        return values
