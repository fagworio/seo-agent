"""Tests for GA4 A0 — data contract, typed metrics, normalization, pagination."""

import json

import httpx
import pytest

from hermes_seo_agent.config import load_config
from hermes_seo_agent.connectors.analytics import AnalyticsClient, _typed_metric
from hermes_seo_agent.connectors.base import ConnectorError, HttpClient


def _make_config(monkeypatch):
    for key in ("WORDPRESS_URL", "WORDPRESS_APP_USER", "WORDPRESS_APP_PASSWORD",
                "DRY_RUN", "GSC_SITE_URL", "GOOGLE_APPLICATION_CREDENTIALS",
                "SEO_ENV_FILE", "SQLITE_PATH", "GA4_PROPERTY_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SEO_ENV_FILE", "/nonexistent")
    monkeypatch.setenv("SQLITE_PATH", "/tmp/seo-test-ga4.db")
    monkeypatch.setenv("GA4_PROPERTY_ID", "123456789")
    return load_config()


def _client(config, handler):
    http = HttpClient(transport=httpx.MockTransport(handler))
    return AnalyticsClient(config, token_provider=lambda: "fake-token", http=http)


def _organic_row(landing="https://www.unicorniohater.com.br/post/",
                 sessions="100", engaged="60", rate="0.6",
                 time="1234", events="5"):
    return {
        "dimensionValues": [{"value": landing}],
        "metricValues": [
            {"value": sessions}, {"value": engaged}, {"value": rate},
            {"value": time}, {"value": events},
        ],
    }


def _report_response(rows, row_count=None):
    return {
        "rowCount": str(row_count if row_count is not None else len(rows)),
        "rows": rows,
        "propertyQuota": {"tokensPerDay": {"consumed": 1, "remaining": 100}},
    }


def test_organic_report_contract(monkeypatch):
    """Filtro orgânico + métricas tipadas + URL canônica."""
    config = _make_config(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["dimensions"] == [{"name": "landingPagePlusQueryString"}]
        filtro = body["dimensionFilter"]["filter"]
        assert filtro["fieldName"] == "sessionDefaultChannelGroup"
        assert filtro["stringFilter"]["value"] == "Organic Search"
        return httpx.Response(200, json=_report_response([
            _organic_row(),
            _organic_row(landing="https://www.unicorniohater.com.br/post/?utm=x#frag",
                         sessions="0", engaged="0", rate="0"),
        ]))

    client = _client(config, handler)
    result = client.organic_landing_performance(start_date="2026-01-01",
                                                end_date="2026-01-28")
    assert result["row_count"] == 2
    row = result["rows"][0]
    assert row["url"] == "https://www.unicorniohater.com.br/post/"
    assert row["sessions"] == 100.0
    assert row["engaged_sessions"] == 60.0
    assert row["engagement_rate"] == 0.6
    assert row["measurement_status"] == "available"
    # query string removida, trailing slash normalizada, zero REAL preservado
    assert result["rows"][1]["url"] == "https://www.unicorniohater.com.br/post/"
    assert result["rows"][1]["sessions"] == 0.0
    assert result["rows"][1]["measurement_status"] == "available"
    assert result["quota"]["tokensPerDay"]["remaining"] == 100


def test_missing_metric_is_none_not_zero(monkeypatch):
    """Dado ausente NUNCA vira 0 artificial: value=None, status=missing."""
    config = _make_config(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_report_response([
            {
                "dimensionValues": [{"value": "https://www.unicorniohater.com.br/a/"}],
                "metricValues": [
                    {"value": "50"}, {}, {"value": "0.5"},
                    {"value": "999"}, {"value": "1"},
                ],
            },
        ]))

    client = _client(config, handler)
    row = client.organic_landing_performance(
        start_date="2026-01-01", end_date="2026-01-28"
    )["rows"][0]
    assert row["sessions"] == 50.0
    assert row["engaged_sessions"] is None          # ausente -> None
    assert row["measurement_status"] == "partial"   # mix available/missing


def test_typed_metric_statuses():
    assert _typed_metric("10") == {"value": 10.0, "status": "available"}
    assert _typed_metric("0") == {"value": 0.0, "status": "available"}   # zero real
    assert _typed_metric(None) == {"value": None, "status": "missing"}
    assert _typed_metric("") == {"value": None, "status": "missing"}
    assert _typed_metric("abc") == {"value": None, "status": "invalid"}


def test_normalize_landing(monkeypatch):
    config = _make_config(monkeypatch)
    client = _client(config, lambda req: httpx.Response(200, json=_report_response([])))
    assert client.normalize_landing("/post/")["url"] == \
        "https://www.unicorniohater.com.br/post/"
    assert client.normalize_landing("/post/?utm=x#f")["url"] == \
        "https://www.unicorniohater.com.br/post/"
    assert client.normalize_landing("https://www.unicorniohater.com.br/post")["url"] == \
        "https://www.unicorniohater.com.br/post/"
    # domínio inesperado -> registrado como unmatched (não descartado em silêncio)
    bad = client.normalize_landing("https://other-domain.com/post/")
    assert bad["valid"] is False
    assert "domain mismatch" in bad["reason"]


def test_unmatched_are_reported_not_dropped(monkeypatch):
    config = _make_config(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_report_response([
            _organic_row("https://www.unicorniohater.com.br/ok/"),
            _organic_row("https://evil.example.com/other/"),
        ]))

    client = _client(config, handler)
    result = client.organic_landing_performance(
        start_date="2026-01-01", end_date="2026-01-28",
        known_urls={"https://www.unicorniohater.com.br/ok/"},
    )
    assert len(result["rows"]) == 1
    assert result["rows"][0]["matched_sitemap"] is True
    assert result["unmatched"] == [
        {"landing": "https://evil.example.com/other/",
         "reason": "domain mismatch: evil.example.com != www.unicorniohater.com.br"}
    ]


def test_pagination_uses_rowcount_and_offset(monkeypatch):
    """Paginação por limit/offset até cobrir rowCount."""
    config = _make_config(monkeypatch)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body.get("offset"))
        offset = body.get("offset", 0)
        rows = [_organic_row(f"https://www.unicorniohater.com.br/p{i}/") for i in range(2)]
        return httpx.Response(200, json=_report_response(rows, row_count=4))

    client = _client(config, handler)
    result = client._paginate(
        {"dateRanges": [], "dimensions": [{"name": "landingPagePlusQueryString"}],
         "metrics": [{"name": m} for m in ("sessions", "engagedSessions",
                                           "engagementRate", "engagementTime",
                                           "keyEvents")]},
        row_limit=2,
    )
    assert result["row_count"] == 4
    assert len(result["rows"]) == 4   # 2 páginas de 2
    assert calls == [0, 2]


def test_page_engagement_no_organic_filter(monkeypatch):
    config = _make_config(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "dimensionFilter" not in body
        return httpx.Response(200, json=_report_response([
            {"dimensionValues": [{"value": "/post/"}],
             "metricValues": [{"value": "10"}, {"value": "5"}, {"value": "0.5"},
                              {"value": "100"}, {"value": "0"}]},
        ]))

    client = _client(config, handler)
    result = client.page_engagement(start_date="2026-01-01", end_date="2026-01-28")
    assert result["rows"][0]["page_path"] == "/post/"
    assert result["rows"][0]["sessions"] == 10.0


def test_status_report(monkeypatch):
    config = _make_config(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_report_response([
            _organic_row(),
        ]))

    client = _client(config, handler)
    status = client.status(start_date="2026-01-01", end_date="2026-01-28")
    assert status["configured"] is True
    assert status["property_id"] == "123456789"
    assert status["rows_returned"] == 1
    assert status["canonical_urls"] == 1
    assert status["quota"]["tokensPerDay"]["remaining"] == 100


def test_ga4_requires_property_id(monkeypatch):
    monkeypatch.delenv("GA4_PROPERTY_ID", raising=False)
    monkeypatch.setenv("SEO_ENV_FILE", "/nonexistent")
    config = load_config()
    with pytest.raises(ConnectorError):
        AnalyticsClient(config, token_provider=lambda: "t")
