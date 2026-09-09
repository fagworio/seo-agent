"""Regressão #5: RunContext reutiliza a coleta GSC/GA4 do ciclo.

demand/title-opportunities/post-audit consultam a MESMA janela; com o cache do
RunContext a fonte externa é chamada UMA vez por ciclo (não uma por etapa).
"""
from types import SimpleNamespace

from hermes_seo_agent.services.run_context import RunContext


def test_run_context_reuses_gsc_query_pages(monkeypatch):
    class FakeGSC:
        def __init__(self, config):
            self.calls = 0

        def search_analytics_query_page(self, *, start_date, end_date, row_limit=25_000):
            self.calls += 1
            return [{"keys": ["q", "u"], "impressions": 5}]

        def search_analytics_by_page(self, *, start_date, end_date, row_limit=25_000):
            self.calls += 1
            return [{"keys": ["u"], "impressions": 5}]

    monkeypatch.setattr(
        "hermes_seo_agent.connectors.search_console.SearchConsoleClient", FakeGSC)

    cfg = SimpleNamespace(google_credentials="x", ga4_property_id="", sqlite_path=":memory:")
    ctx = RunContext(cfg)
    gsc = ctx.search_console()
    r1 = ctx.gsc_query_pages("2026-01-01", "2026-01-28")
    r2 = ctx.gsc_query_pages("2026-01-01", "2026-01-28")
    assert gsc.calls == 1, "mesma janela (start,end) deve reutilizar a coleta do ciclo"
    assert r1 == r2
    ctx.close()


def test_run_context_caches_different_windows_separately(monkeypatch):
    class FakeGSC:
        def __init__(self, config):
            self.calls = 0

        def search_analytics_query_page(self, *, start_date, end_date, row_limit=25_000):
            self.calls += 1
            return [{"keys": [start_date], "url": "u", "impressions": 1}]

        def search_analytics_by_page(self, *, start_date, end_date, row_limit=25_000):
            self.calls += 1
            return [{"keys": [start_date], "impressions": 1}]

    monkeypatch.setattr(
        "hermes_seo_agent.connectors.search_console.SearchConsoleClient", FakeGSC)

    cfg = SimpleNamespace(google_credentials="x", ga4_property_id="", sqlite_path=":memory:")
    ctx = RunContext(cfg)
    ctx.gsc_query_pages("2026-01-01", "2026-01-28")
    ctx.gsc_query_pages("2026-02-01", "2026-02-28")
    assert ctx._gsc_query_pages.keys() >= {("2026-01-01", "2026-01-28", 25_000),
                                           ("2026-02-01", "2026-02-28", 25_000)}
    ctx.close()
