"""Google Analytics 4 Data API connector (A0 — contrato de dados).

Dois relatórios EXPLÍCITOS, com métricas tipadas (float | None) e
measurement_status — nunca transforma dado ausente em "0 sessões" ou
"0% de engajamento":

  * organic_landing_performance: landingPagePlusQueryString + filtro de
    tráfego orgânico (sessionDefaultChannelGroup == 'Organic Search');
  * page_engagement: consumo geral da página (pagePath), opcional/separado.

Contrato de robustez:
  * landing pages normalizadas para URL canônica (sem query/fragmento,
    trailing slash consistente, domínio validado);
  * URLs sem correspondência (domínio inesperado / path vazio) são
    REGISTRADAS em `unmatched`, nunca descartadas em silêncio;
  * paginação por limit + offset usando rowCount devolvido pela API;
  * quota da property capturada (returnPropertyQuota).

Auth espelha Search Console: token provider injetável (testes) ou service
account via google-auth (extra ``[google]``).
"""

from __future__ import annotations

from typing import Any, Callable

from ..config import Config
from .base import ConnectorError, HttpClient
from .search_console import _default_token_provider

_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
_BASE = "https://analyticsdata.googleapis.com/v1beta"
_ORGANIC_CHANNEL = "Organic Search"

# status de medição por linha — available | missing | invalid | partial
MEASUREMENT_STATUSES = ("available", "missing", "invalid", "partial")

_ORGANIC_METRICS = (
    "sessions",
    "engagedSessions",
    "engagementRate",
    "userEngagementDuration",
    "keyEvents",
)


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
        # Token com escopo analytics.readonly — o provider do GSC emitiria
        # webmasters.readonly, que NÃO autoriza a GA4 Data API.
        self.token_provider = token_provider or _default_token_provider(
            config, scopes=[_SCOPE]
        )
        self.http = http or HttpClient(timeout=config.http_timeout)

    # -- low-level -----------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        token = self.token_provider()
        if not token:
            raise ConnectorError("GA4 token provider returned an empty token")
        return {"Authorization": f"Bearer {token}"}

    def _run_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{_BASE}/{self.property}:runReport"
        response = self.http.post(url, json_body=payload, headers=self._headers())
        if response.status_code != 200:
            raise ConnectorError(
                f"GA4 runReport failed: HTTP {response.status_code} {response.text[:200]}"
            )
        return response.json()

    def _paginate(self, base_payload: dict[str, Any], *, row_limit: int) -> dict[str, Any]:
        """Collect ALL rows via limit+offset pagination, using rowCount as total."""
        page_size = min(max(row_limit, 1), 250_000)
        rows: list[dict[str, Any]] = []
        row_count = 0
        quota: dict[str, Any] = {}
        offset = 0
        while True:
            payload = {**base_payload, "limit": page_size, "offset": offset,
                       "returnPropertyQuota": True}
            data = self._run_report(payload)
            row_count = int(data.get("rowCount", 0) or 0)
            quota = data.get("propertyQuota") or quota
            batch = self._parse_rows(data, base_payload["dimensions"],
                                     base_payload["metrics"])
            rows.extend(batch)
            offset += page_size
            if not batch or offset >= row_count:
                break
        return {"rows": rows, "row_count": row_count, "quota": quota}

    def _parse_rows(self, data: dict[str, Any], dims: list[dict[str, str]],
                    metrics: list[dict[str, str]]) -> list[dict[str, Any]]:
        metric_names = [m["name"] for m in metrics]
        parsed: list[dict[str, Any]] = []
        for row in data.get("rows", []):
            dim_values = [d.get("value", "") for d in row.get("dimensionValues", [])]
            metric_values = row.get("metricValues", [])
            metric_map: dict[str, Any] = {}
            for i, name in enumerate(metric_names):
                raw = metric_values[i].get("value") if i < len(metric_values) else None
                metric_map[name] = _typed_metric(raw)
            parsed.append({
                "dimensions": dim_values,
                "metrics": metric_map,
            })
        return parsed

    # -- relatórios ----------------------------------------------------------

    def organic_landing_performance(
        self,
        *,
        start_date: str,
        end_date: str,
        row_limit: int = 25_000,
        known_urls: set[str] | None = None,
        expected_domain: str = "",
    ) -> dict[str, Any]:
        """Landing pages com tráfego ORGÂNICO apenas.

        Retorna {rows, row_count, unmatched, quota}. Cada row:
          {url, domain_valid, matched_sitemap, sessions, engaged_sessions,
           engagement_rate, engagement_time, key_events, measurement_status}
        """
        payload = {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "dimensions": [{"name": "landingPagePlusQueryString"}],
            "metrics": [{"name": m} for m in _ORGANIC_METRICS],
            "dimensionFilter": {
                "filter": {
                    "fieldName": "sessionDefaultChannelGroup",
                    "stringFilter": {"matchType": "EXACT", "value": _ORGANIC_CHANNEL},
                }
            },
        }
        result = self._paginate(payload, row_limit=row_limit)
        rows: list[dict[str, Any]] = []
        unmatched: list[dict[str, str]] = []
        for raw in result["rows"]:
            dims = raw["dimensions"]
            landing = dims[0] if dims else ""
            norm = self.normalize_landing(landing, expected_domain=expected_domain)
            if not norm["valid"]:
                unmatched.append({"landing": landing, "reason": norm["reason"]})
                continue
            m = raw["metrics"]
            statuses = [v["status"] for v in m.values()]
            measurement_status = _row_status(statuses)
            rows.append({
                "url": norm["url"],
                "domain_valid": True,
                "matched_sitemap": bool(known_urls is not None
                                        and norm["url"] in known_urls),
                "sessions": m["sessions"]["value"],
                "engaged_sessions": m["engagedSessions"]["value"],
                "engagement_rate": m["engagementRate"]["value"],
                "engagement_time": m["userEngagementDuration"]["value"],
                "key_events": m["keyEvents"]["value"],
                "measurement_status": measurement_status,
            })
        return {
            "rows": rows,
            "row_count": result["row_count"],
            "unmatched": unmatched,
            "quota": result["quota"],
        }

    def page_engagement(
        self,
        *,
        start_date: str,
        end_date: str,
        row_limit: int = 25_000,
    ) -> dict[str, Any]:
        """Consumo geral da página (TODOS os canais) — opcional e separado."""
        payload = {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "dimensions": [{"name": "pagePath"}],
            "metrics": [{"name": m} for m in _ORGANIC_METRICS],
        }
        result = self._paginate(payload, row_limit=row_limit)
        rows = []
        for raw in result["rows"]:
            dims = raw["dimensions"]
            m = raw["metrics"]
            statuses = [v["status"] for v in m.values()]
            rows.append({
                "page_path": dims[0] if dims else "",
                "sessions": m["sessions"]["value"],
                "engaged_sessions": m["engagedSessions"]["value"],
                "engagement_rate": m["engagementRate"]["value"],
                "engagement_time": m["userEngagementDuration"]["value"],
                "key_events": m["keyEvents"]["value"],
                "measurement_status": _row_status(statuses),
            })
        return {"rows": rows, "row_count": result["row_count"], "quota": result["quota"]}

    # -- status (A0: credencial, property, período, linhas, unmatched, quota) --

    def status(self, *, start_date: str, end_date: str) -> dict[str, Any]:
        """Diagnóstico da coleta: configuração + amostra da property."""
        result = self.organic_landing_performance(
            start_date=start_date, end_date=end_date, row_limit=100,
        )
        return {
            "configured": True,
            "property_id": self.config.ga4_property_id,
            "token_ok": True,
            "window": {"start": start_date, "end": end_date},
            "rows_returned": result["row_count"],
            "canonical_urls": len(result["rows"]),
            "unmatched": result["unmatched"],
            "quota": result["quota"],
        }

    # -- normalização (A0) ---------------------------------------------------

    def normalize_landing(self, landing: str, *, expected_domain: str = "") -> dict[str, Any]:
        """Landing page -> URL canônica.

        Regras: remove query string e fragmento; normaliza trailing slash;
        valida domínio (vazio = aceita path relativo, usa expected_domain).
        Nunca descarta: inválido volta com `reason` para registro.
        """
        value = (landing or "").strip()
        if not value:
            return {"valid": False, "url": "", "reason": "empty"}
        domain = expected_domain or self.config.static_site_url
        if value.startswith("/"):
            # path relativo do GA4 (pagePath/landingPagePlusQueryString)
            url = f"{domain.rstrip('/')}{_clean_path(value)}"
            return {"valid": True, "url": url, "reason": ""}
        # URL absoluta: valida o domínio
        from urllib.parse import urlsplit
        parts = urlsplit(value)
        expected_host = urlsplit(domain).netloc
        if parts.netloc != expected_host:
            return {"valid": False, "url": "",
                    "reason": f"domain mismatch: {parts.netloc} != {expected_host}"}
        if parts.scheme not in {"http", "https"}:
            return {"valid": False, "url": "", "reason": f"bad scheme: {parts.scheme}"}
        return {"valid": True, "url": f"{parts.scheme}://{parts.netloc}{_clean_path(parts.path)}",
                "reason": ""}


def _clean_path(path: str) -> str:
    """Remove query/fragmento e normaliza trailing slash (um único)."""
    path = (path or "").split("?")[0].split("#")[0]
    if not path:
        return "/"
    if not path.startswith("/"):
        path = "/" + path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path + "/"


def _typed_metric(raw: Any) -> dict[str, Any]:
    """float | None com status: available | missing | invalid.

    Valor ausente/None -> (None, missing); não-numérico -> (None, invalid);
    numérico (incluindo 0 REAL) -> (float, available). Zero real NUNCA vira
    missing — só quando a API não devolve o valor.
    """
    if raw is None or raw == "":
        return {"value": None, "status": "missing"}
    try:
        return {"value": float(raw), "status": "available"}
    except (TypeError, ValueError):
        return {"value": None, "status": "invalid"}


def _row_status(statuses: list[str]) -> str:
    """partial quando algumas métricas da linha estão indisponíveis/inválidas."""
    if not statuses:
        return "missing"
    if all(s == "available" for s in statuses):
        return "available"
    if all(s != "available" for s in statuses):
        return "invalid" if all(s == "invalid" for s in statuses) else "missing"
    return "partial"
