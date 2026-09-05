"""Google Trends connector — market-demand signal for title decisions.

Fail-soft by design: Trends is an ENRICHMENT layer over GSC data. If Trends
is unreachable/rate-limited (common from datacenter IPs) every call returns
None and the caller falls back to GSC-only scoring — the pipeline never
breaks because Trends is down.

Score semantics (interest_over_time, geo=BR):
  - ``interest(term)``: 0..100 relative interest over the window (100 =
    peak of the batch). Batch size <= 5 terms per payload (Google limit).
  - ``momentum(term)``: last-2-weeks average vs previous period of the same
    window -> +1 rising, 0 stable, -1 falling. Statistical decision aid:
    a rising keyword is worth more in the title than a falling one.
"""

from __future__ import annotations

import time
from typing import Any

from .base import ConnectorError


class GoogleTrendsClient:
    """Thin wrapper around pytrends with per-run cache and fail-soft calls."""

    def __init__(self, *, geo: str = "BR", window_days: int = 90,
                 hl: str = "pt-BR", timeout: tuple[int, int] = (5, 15)) -> None:
        self.geo = geo
        self.window = f"today {window_days}-d"
        self.hl = hl
        self.timeout = timeout
        self._cache: dict[str, dict[str, Any]] = {}
        self._client: Any | None = None

    # -- internals ------------------------------------------------------
    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from pytrends.request import TrendReq
            except ImportError as exc:  # pragma: no cover - env-dependent
                raise ConnectorError("pytrends nao instalado") from exc
            self._client = TrendReq(hl=self.hl, tz=180, timeout=self.timeout)
        return self._client

    def _fetch(self, terms: list[str]) -> dict[str, dict[str, Any]]:
        """One batch of <=5 terms -> {term: {interest, momentum}}."""
        out: dict[str, dict[str, Any]] = {}
        if not terms:
            return out
        try:
            pt = self._get_client()
            pt.build_payload(terms, timeframe=self.window, geo=self.geo)
            df = pt.interest_over_time()
        except Exception as exc:  # noqa: BLE001 - fail-soft on any Trends error
            raise ConnectorError(f"Google Trends indisponivel: {exc}") from exc
        if df is None or df.empty:
            return {t: {"interest": 0, "momentum": 0} for t in terms}
        total = df[terms].sum().to_dict()
        n = max(len(df), 1)
        half = max(n // 2, 1)
        for term in terms:
            if term not in df.columns:
                out[term] = {"interest": 0, "momentum": 0}
                continue
            series = df[term]
            interest = float(total.get(term, 0)) / n  # 0..100 average
            recent = float(series.tail(half).mean())
            previous = float(series.head(n - half).mean())
            if previous <= 0:
                momentum = 1 if recent > 0 else 0
            else:
                delta = (recent - previous) / previous
                momentum = 1 if delta > 0.15 else (-1 if delta < -0.15 else 0)
            out[term] = {"interest": round(interest, 1), "momentum": momentum}
        return out

    # -- public (fail-soft) ---------------------------------------------
    def batch_interest(self, terms: list[str]) -> dict[str, dict[str, Any]]:
        """Interest+momentum for terms, cached per term, batches of 5."""
        terms = [t.strip() for t in (terms or []) if t and t.strip()]
        terms = list(dict.fromkeys(terms))
        result: dict[str, dict[str, Any]] = {}
        pending: list[str] = []
        for term in terms:
            if term in self._cache:
                result[term] = self._cache[term]
            else:
                pending.append(term)
        for i in range(0, len(pending), 5):
            chunk = pending[i : i + 5]
            try:
                fetched = self._fetch(chunk)
                for term, data in fetched.items():
                    self._cache[term] = data
                    result[term] = data
            except ConnectorError:
                # Fail-soft: missing terms get a neutral score; caller keeps
                # GSC-only scoring for them.
                for term in chunk:
                    neutral = {"interest": None, "momentum": 0}
                    self._cache[term] = neutral
                    result[term] = neutral
            time.sleep(0.3)  # be gentle with the undocumented endpoint
        return result
