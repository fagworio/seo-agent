"""Tests for M4 hardening — Google Trends provider (real adapter, mocked)."""

import json

import httpx
import pytest

from hermes_seo_agent.config import Config
from hermes_seo_agent.connectors.base import HttpClient
from hermes_seo_agent.services.market_intelligence import (
    NoopProvider,
    TrendsProvider,
    _parse_timeline,
    get_provider,
)


def _config(key="trends-key") -> Config:
    return Config(wordpress_url="http://localhost", trends_api_key=key)


def _provider(handler, config=None) -> TrendsProvider:
    p = TrendsProvider(config or _config())
    p._http = HttpClient(transport=httpx.MockTransport(handler))
    return p


def _timeline_response():
    return {"lines": [{"term": "gojo", "points": [
        {"date": "2026-06-01", "value": 40},
        {"date": "2026-07-01", "value": 50},
        {"date": "2026-08-01", "value": 70},
        {"date": "2026-09-01", "value": 90},
    ]}]}


def test_parse_timeline_formats():
    # schema oficial getGraph
    assert _parse_timeline(
        {"lines": [{"term": "gojo", "points": [
            {"date": "2026-01-01", "value": "50"}]}]}, "gojo"
    ) == [{"date": "2026-01-01", "value": 50.0}]
    # linhas de outro termo são ignoradas
    assert _parse_timeline(
        {"lines": [{"term": "outro", "points": [
            {"date": "2026-01-01", "value": 99}]}]}, "gojo"
    ) == []
    # formatos legados
    assert _parse_timeline({"interest_over_time": [{"date": "2026-01-01", "value": 10}]},
                           "k")[0]["value"] == 10.0
    assert _parse_timeline({"data": {"interest": [{"date": "2026-01-01", "value": 5}]}},
                           "k")[0]["value"] == 5.0
    # estrutura inesperada -> [] (nunca zero fabricado)
    assert _parse_timeline({"unexpected": [{"x": 1}]}, "k") == []


def test_keyword_metrics_uses_graph_endpoint():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        assert "/graph" in str(request.url)
        assert "key=trends-key" in str(request.url)
        assert "restrictions.geo=BR" in str(request.url)
        return httpx.Response(200, json=_timeline_response())

    p = _provider(handler)
    rows = p.keyword_metrics("gojo")
    assert rows[0]["keyword"] == "gojo"
    assert rows[0]["relative_interest_avg"] == 62.5
    assert rows[0]["relative_interest_max"] == 90.0
    assert "não volume absoluto" in rows[0]["note"]


def test_trend_signal_growing():
    def handler(request):
        return httpx.Response(200, json=_timeline_response())

    p = _provider(handler)
    sig = p.trend_signal("gojo")
    assert sig["trend"] == "growing"
    assert sig["delta_pct"] > 0


def test_trend_signal_insufficient_points_is_unknown():
    def handler(request):
        return httpx.Response(200, json={"timeline": [
            {"date": "2026-08-01", "value": 50},
            {"date": "2026-09-01", "value": 60},
        ]})

    p = _provider(handler)
    sig = p.trend_signal("gojo")
    assert sig["trend"] == "unknown"
    assert sig["delta_pct"] is None


def test_trends_http_error_becomes_missing_not_zero():
    def handler(request):
        return httpx.Response(403, json={"error": {"message": "quota"}})

    p = _provider(handler)
    with pytest.raises(Exception):
        p.keyword_metrics("gojo")  # erro propaga -> chamada falha, não vira 0


def test_get_provider_uses_trends_when_key_set():
    assert isinstance(get_provider(_config("k")), TrendsProvider)
    assert isinstance(get_provider(Config(wordpress_url="http://x")), NoopProvider)


def test_trends_evidence_cost_zero_and_origin():
    def handler(request):
        return httpx.Response(200, json=_timeline_response())

    p = _provider(handler)
    ev = p._evidence("gojo", method="keyword_metrics",
                     rows=p.keyword_metrics("gojo"), quota={"daily": {"used": 5}})
    assert ev["provider"] == "google_trends"
    assert ev["cost_cents"] == 0
    assert ev["quota"]["daily"]["used"] == 5
    assert ev["data_status"] == "available"
