"""Google Search Console connector (Phase 2).

- Search Analytics (query/date dimensions)
- URL Inspection (indexing status per URL)
- Sitemaps (list/submit)

Auth is injectable for tests: ``token_provider`` is a zero-arg callable
returning a bearer token. The default provider uses a Google service account
JSON via ``google-auth`` (optional extra ``[google]``); without it or without
credentials it fails with a clear message instead of guessing.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from ..config import Config
from .base import ConnectorError, HttpClient

_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
_BASE = "https://searchconsole.googleapis.com/webmasters/v3"
_BASE_V1 = "https://searchconsole.googleapis.com/v1"  # urlInspection lives here
_SA_MAX_PAGE_SIZE = 25_000
_SA_MAX_PAGES = 20


class SearchConsoleClient:
    def __init__(
        self,
        config: Config,
        *,
        token_provider: Callable[[], str] | None = None,
        http: HttpClient | None = None,
        budget: Any | None = None,
    ):
        self.config = config
        self.token_provider = token_provider or _default_token_provider(config)
        self.http = http or HttpClient(timeout=config.http_timeout, budget=budget)

    # -- auth ----------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        token = self.token_provider()
        if not token:
            raise ConnectorError("GSC token provider returned an empty token")
        return {"Authorization": f"Bearer {token}"}

    # -- Search Analytics ----------------------------------------------------

    def search_analytics(
        self,
        *,
        start_date: str,
        end_date: str,
        dimensions: tuple[str, ...] = ("query",),
        row_limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Rows: [{keys: [...], clicks, impressions, ctr, position}, ...]"""
        return self._sa_query(list(dimensions), start_date, end_date, row_limit)

    def search_analytics_discover_daily(
        self,
        *,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """Google Discover volume per day (search type=discover).

        The Search Analytics API only accepts the DATE dimension when a
        search type is set (page/query dimensions return HTTP 400), so
        Discover is site-wide only — never per URL. Strategic context:
        site momentum on Discover (accelerating/stable/losing reach).

        Rows: [{keys: [date], clicks, impressions, ctr}, ...] (no position —
        Discover has no position).
        """
        return self._sa_query(
            ["date"], start_date, end_date, 1000, search_type="discover"
        )

    def search_analytics_by_page(
        self,
        *,
        start_date: str,
        end_date: str,
        row_limit: int = 25_000,
    ) -> list[dict[str, Any]]:
        """Aggregated per-page rows (dimension=page): {keys:[page], clicks, impressions, ...}"""
        return self._sa_query(["page"], start_date, end_date, row_limit)

    def search_analytics_query_page(
        self,
        *,
        start_date: str,
        end_date: str,
        row_limit: int = 25_000,
    ) -> list[dict[str, Any]]:
        """Rows with BOTH dimensions: {keys:[query, page], impressions, clicks, ...}"""
        return self._sa_query(["query", "page"], start_date, end_date, row_limit)

    def search_analytics_page_device(
        self,
        *,
        start_date: str,
        end_date: str,
        row_limit: int = 25_000,
    ) -> list[dict[str, Any]]:
        """SEO-INC-014: página × dispositivo (MOBILE/DESKTOP/TABLET).

        Uma requisição traz o corte por device sem multiplicar a coleta de
        query×página — é o que permite julgar CTR mobile contra o próprio
        segmento mobile em vez de uma média que esconde o problema.
        """
        return self._sa_query(["page", "device"], start_date, end_date, row_limit)

    def top_queries(
        self,
        page_url: str,
        *,
        start_date: str,
        end_date: str,
        row_limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Top queries for ONE page (dimension=query filtered by page)."""
        return self._sa_query(
            ["query"], start_date, end_date, row_limit,
            filters=[{"dimension": "page", "operator": "equals", "expression": page_url}],
        )

    def page_metrics(
        self,
        page_url: str,
        *,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        """Aggregate metrics (clicks/impressions/ctr/position) for ONE page."""
        rows = self._sa_query(
            ["page"], start_date, end_date, 1,
            filters=[{"dimension": "page", "operator": "equals", "expression": page_url}],
        )
        if not rows:
            return {}
        row = rows[0]
        return {
            "impressions": float(row.get("impressions", 0)),
            "clicks": float(row.get("clicks", 0)),
            "ctr": float(row.get("ctr", 0)),
            "position": float(row.get("position", 0)),
        }

    def _sa_query(
        self,
        dimensions: list[str],
        start_date: str,
        end_date: str,
        row_limit: int,
        filters: list[dict[str, Any]] | None = None,
        search_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Coleta uma janela em páginas bounded e deduplica chaves repetidas.

        ``row_limit`` é o tamanho de cada página da API. O GSC aceita no
        máximo 25.000 linhas por chamada; até ``_SA_MAX_PAGES`` chamadas são
        feitas para cobrir janelas grandes sem criar um loop ilimitado. A
        paginação para quando uma página vem incompleta, como recomendado pela
        API, e usa ``startRow`` somente a partir da segunda chamada.
        """
        page_size = max(1, min(int(row_limit or 1), _SA_MAX_PAGE_SIZE))
        url = f"{_BASE}/sites/{_quoted(self.config.gsc_site_url)}/searchAnalytics/query"
        output: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for page in range(_SA_MAX_PAGES):
            payload: dict[str, Any] = {
                "startDate": start_date,
                "endDate": end_date,
                "dimensions": dimensions,
                "rowLimit": page_size,
            }
            if page:
                payload["startRow"] = page * page_size
            if search_type:
                # Search-type ("web"/"news"/"discover"/...) is a top-level
                # field, NOT a dimension filter; with a type set only DATE is
                # allowed.
                payload["type"] = search_type
            if filters:
                payload["dimensionFilterGroups"] = [{"filters": filters}]
            response = self.http.post(url, json_body=payload, headers=self._headers())
            if response.status_code != 200:
                raise ConnectorError(
                    f"searchAnalytics failed: HTTP {response.status_code} "
                    f"{response.text[:200]}"
                )
            data = response.json()
            rows = data.get("rows", []) if isinstance(data, dict) else []
            if not isinstance(rows, list) or not rows:
                break
            for row in rows:
                if not isinstance(row, dict):
                    continue
                keys = row.get("keys")
                if isinstance(keys, list):
                    identity = ("keys", json.dumps(keys, ensure_ascii=False,
                                                    separators=(",", ":")))
                else:
                    identity = ("row", json.dumps(row, ensure_ascii=False,
                                                   sort_keys=True,
                                                   separators=(",", ":")))
                if identity in seen:
                    continue
                seen.add(identity)
                output.append(row)
            if len(rows) < page_size:
                break
        return output

    # -- URL Inspection ------------------------------------------------------

    def inspect_url(self, url: str) -> dict[str, Any]:
        """URL Inspection API result for one URL (consumes budget).

        Per the v1 discovery doc, this method lives OUTSIDE webmasters/v3:
        POST https://searchconsole.googleapis.com/v1/urlInspection/index:inspect
        """
        payload = {"inspectionUrl": url, "siteUrl": self.config.gsc_site_url}
        response = self.http.post(
            f"{_BASE_V1}/urlInspection/index:inspect", json_body=payload, headers=self._headers()
        )
        if response.status_code != 200:
            raise ConnectorError(f"urlInspection failed for {url}: HTTP {response.status_code} {response.text[:200]}")
        data = response.json()
        return data.get("inspectionResult", data) if isinstance(data, dict) else {}

    # -- Sitemaps ------------------------------------------------------------

    def list_sitemaps(self) -> list[dict[str, Any]]:
        url = f"{_BASE}/sites/{_quoted(self.config.gsc_site_url)}/sitemaps"
        response = self.http.get(url, headers=self._headers())
        if response.status_code != 200:
            raise ConnectorError(f"list sitemaps failed: HTTP {response.status_code} {response.text[:200]}")
        data = response.json()
        return data.get("sitemap", []) if isinstance(data, dict) else []


def _quoted(site_url: str) -> str:
    from urllib.parse import quote

    return quote(site_url.rstrip("/"), safe="")


def _default_token_provider(config: Config,
                            scopes: list[str] | None = None) -> Callable[[], str]:
    """Lazy google-auth service-account provider; clear error when unconfigured.

    ``scopes`` defaulta para o escopo do Search Console; conectores de outras
    APIs (ex.: GA4 analytics.readonly) passam os próprios escopos para que o
    token JWT carregue a permissão certa — um token GSC NÃO autoriza GA4.
    """

    credentials = None

    def provide() -> str:
        nonlocal credentials
        if not config.google_credentials:
            raise ConnectorError(
                "GSC not configured: set GOOGLE_APPLICATION_CREDENTIALS to a "
                "service-account JSON with Search Console access"
            )
        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account
        except ImportError as exc:  # pragma: no cover
            raise ConnectorError(
                "google-auth is required for GSC: pip install 'hermes-seo-agent[google]'"
            ) from exc
        if credentials is None:
            credentials = service_account.Credentials.from_service_account_file(
                config.google_credentials, scopes=scopes or [_SCOPE]
            )
        if (not getattr(credentials, "valid", False)
                or getattr(credentials, "expired", False)
                or not getattr(credentials, "token", None)):
            credentials.refresh(Request())
        return credentials.token or ""

    return provide
