"""Google CrUX API connector (Phase 3) — field Core Web Vitals by origin/URL."""

from __future__ import annotations

from typing import Any

from ..config import Config
from .base import ConnectorError, HttpClient

_BASE = "https://chromeuxreport.googleapis.com/v1/records:queryRecord"


class CruxClient:
    def __init__(self, config: Config, http: HttpClient | None = None):
        self.config = config
        self.http = http or HttpClient(timeout=config.http_timeout)

    def query_origin(self, origin: str, *, form_factor: str | None = "PHONE") -> dict[str, Any]:
        """CrUX record for an origin; form_factor None = aggregate."""
        return self._query({"origin": origin}, form_factor=form_factor)

    def query_url(self, url: str, *, form_factor: str | None = "PHONE") -> dict[str, Any]:
        """CrUX record for a URL; form_factor None = aggregate."""
        return self._query({"url": url}, form_factor=form_factor)

    def origin_cwv(self, origin: str) -> dict[str, float]:
        """Robust CWV for an origin: PHONE first, aggregate fills metric gaps.

        The CrUX API is eventually-consistent: PHONE buckets occasionally miss
        a metric. Retry aggregated and merge (PHONE values win).
        """
        expected = {"lcp", "cls", "inp"}
        values = CruxClient.cwv_values(self.query_origin(origin, form_factor="PHONE"))
        if expected.issubset(values):
            return values
        aggregate = CruxClient.cwv_values(self.query_origin(origin, form_factor=None))
        for key, value in aggregate.items():
            values.setdefault(key, value)
        return values

    def _query(self, payload: dict[str, Any], *, form_factor: str | None = "PHONE") -> dict[str, Any]:
        if not self.config.crux_api_key:
            raise ConnectorError("CrUX not configured: set CRUX_API_KEY")
        body: dict[str, Any] = {
            **payload,
            "metrics": [
                "largest_contentful_paint", "cumulative_layout_shift",
                "interaction_to_next_paint",
            ],
        }
        if form_factor is not None:
            body["formFactor"] = form_factor
        response = self.http.post(
            _BASE,
            params={"key": self.config.crux_api_key},
            json_body=body,
        )
        if response.status_code == 404:
            raise ConnectorError("CrUX: no field data for this record (404)")
        if response.status_code != 200:
            raise ConnectorError(f"CrUX failed: HTTP {response.status_code} {response.text[:200]}")
        data = response.json()
        return data if isinstance(data, dict) else {}

    @staticmethod
    def cwv_values(record: dict[str, Any]) -> dict[str, float]:
        """Extract p75 LCP/CLS/INP from a CrUX record.

        CrUX returns LCP/INP p75 as numbers (ms) and CLS p75 as a STRING
        (e.g. "0.31") — coerce both. Normalized to the canonical units used by
        checks.cwv: LCP seconds, CLS unitless, INP milliseconds.
        """
        metrics = (record.get("record") or {}).get("metrics") or {}
        values: dict[str, float] = {}
        mapping = {
            "largest_contentful_paint": "lcp",
            "cumulative_layout_shift": "cls",
            "interaction_to_next_paint": "inp",
        }
        for crux_key, metric in mapping.items():
            raw = ((metrics.get(crux_key) or {}).get("percentiles") or {}).get("p75")
            if raw is None:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            value = round(value, 3)
            if metric == "lcp":
                value = round(value / 1000, 3)  # ms -> s
            values[metric] = value
        return values
