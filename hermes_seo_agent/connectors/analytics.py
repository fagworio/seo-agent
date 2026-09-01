"""Google Analytics 4 Data API connector (Phase 3) — engagement signals.

Auth mirrors Search Console: injectable token provider (tests) or a service
account via google-auth (optional extra ``[google]``).
"""

from __future__ import annotations

from typing import Any, Callable

from ..config import Config
from .base import ConnectorError, HttpClient
from .search_console import _default_token_provider

_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
_BASE = "https://analyticsdata.googleapis.com/v1beta"


class AnalyticsClient:
    def __init__(
        self,
        config: Config,
        *,
        token_provider: Callable[[], str] | None = None,
        http: HttpClient | None = None,
    ):
        self.config = config
        if not config.ga4_property_id:
            raise ConnectorError("GA4 not configured: set GA4_PROPERTY_ID")
        self.property = f"properties/{config.ga4_property_id}"
        self.token_provider = token_provider or _default_token_provider(config)
        self.http = http or HttpClient(timeout=config.http_timeout)

    def _headers(self) -> dict[str, str]:
        token = self.token_provider()
        if not token:
            raise ConnectorError("GA4 token provider returned an empty token")
        return {"Authorization": f"Bearer {token}"}

    def page_engagement(
        self,
        *,
        start_date: str,
        end_date: str,
        row_limit: int = 25_000,
    ) -> list[dict[str, Any]]:
        """Per-page rows: {pagePath, sessions, engagedSessions, engagementRate}."""
        payload = {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "dimensions": [{"name": "pagePath"}],
            "metrics": [
                {"name": "sessions"},
                {"name": "engagedSessions"},
                {"name": "engagementRate"},
            ],
            "limit": row_limit,
        }
        url = f"{_BASE}/{self.property}:runReport"
        response = self.http.post(url, json_body=payload, headers=self._headers())
        if response.status_code != 200:
            raise ConnectorError(f"GA4 runReport failed: HTTP {response.status_code} {response.text[:200]}")
        data = response.json()
        rows = []
        for row in data.get("rows", []):
            dims = [d.get("value", "") for d in row.get("dimensionValues", [])]
            metrics = [m.get("value", "0") for m in row.get("metricValues", [])]
            rows.append(
                {
                    "page_path": dims[0] if dims else "",
                    "sessions": _float_or(metrics[0] if len(metrics) > 0 else "0"),
                    "engaged_sessions": _float_or(metrics[1] if len(metrics) > 1 else "0"),
                    "engagement_rate": _float_or(metrics[2] if len(metrics) > 2 else "0"),
                }
            )
        return rows


def _float_or(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
