"""Regressão #8: ExecutionBudget no HttpClient conta e bloqueia o excesso."""
import httpx

from hermes_seo_agent.connectors.base import HttpClient
from hermes_seo_agent.services.budget import BudgetExceeded, ExecutionBudget, make_budget


def test_budget_counts_bytes_retries_and_duration():
    budget = ExecutionBudget(max_calls=100)

    def handler(request):
        return httpx.Response(200, content=b"x" * 64)

    http = HttpClient(transport=httpx.MockTransport(handler), budget=budget)
    http.get("https://x.com/a/")
    http.get("https://x.com/b/")
    stats = budget.stats()
    assert stats["calls"] == 2
    assert stats["bytes"] == 128
    assert stats["by_kind"].get("get") == 2
    assert stats["duration_s"] >= 0


def test_budget_blocks_when_limit_reached():
    budget = ExecutionBudget(max_calls=1)
    hits = {"n": 0}

    def handler(request):
        hits["n"] += 1
        return httpx.Response(200, text="ok")

    http = HttpClient(transport=httpx.MockTransport(handler), budget=budget)
    http.get("https://x.com/a/")  # 1 chamada (dentro do limite)
    try:
        http.get("https://x.com/b/")  # 2ª → estoura
        raised = False
    except BudgetExceeded:
        raised = True
    assert raised, "a 2ª chamada deve estourar o orçamento (max_calls=1)"
    # PRE-FLIGHT: a chamada bloqueada NÃO chega na rede (handler só 1 vez).
    assert hits["n"] == 1, "a chamada que excede o teto não pode sair na rede"


def test_stats_separates_http_304_from_avoided_calls():
    """HTTP 304 reusa o corpo, mas a requisição ACONTECEU — não é chamada evitada;
    chamadas realmente evitadas são as de cache de dataset."""
    b = ExecutionBudget(max_calls=0)
    b.hit("http_304")
    b.hit("http_304")
    b.hit("dataset_cache_hit")
    stats = b.stats()
    assert stats["http_304"] == 2
    assert stats["cache_hits"] == 1


def test_make_budget_measures_when_zero_but_never_blocks():
    """max_calls=0 deve MEDIR (telemetria) e nunca bloquear — não virar None."""
    from types import SimpleNamespace
    cfg = SimpleNamespace(max_external_calls=0)
    b = make_budget(cfg)
    assert b is not None and b.max_calls == 0
    for _ in range(1000):
        b.inc("get")           # não levanta
    assert b.stats()["calls"] == 1000
    cfg2 = SimpleNamespace(max_external_calls=5)
    assert make_budget(cfg2).max_calls == 5


def test_budget_counts_failed_attempts_and_retries():
    """timeout/erro de rede TAMBÉM contam como chamada externa real."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        raise httpx.ConnectTimeout("timeout")

    budget = ExecutionBudget(max_calls=0)
    http = HttpClient(transport=httpx.MockTransport(handler), budget=budget, max_retries=3)
    try:
        http.get("https://x.com/a/")
    except Exception:
        pass
    stats = budget.stats()
    assert stats["calls"] == 3, "3 tentativas de rede = 3 chamadas reais"
    assert stats["retries"] == 2, "2 retentativas (não 3)"
    assert stats["by_kind"].get("get_error") == 3


def test_retry_after_is_honored(monkeypatch):
    """429 com Retry-After deve respeitar o valor (não o backoff exponencial)."""
    import hermes_seo_agent.connectors.base as base

    slept: list[float] = []
    monkeypatch.setattr(base.time, "sleep", lambda s: slept.append(s))
    responses = [httpx.Response(429, headers={"Retry-After": "30"}), httpx.Response(200, text="ok")]

    def handler(request):
        return responses.pop(0) if len(responses) > 1 else responses[0]

    http = HttpClient(transport=httpx.MockTransport(handler), max_retries=2)
    http.get("https://x.com/a/")
    assert slept and slept[0] == 30.0, f"deveria dormir 30s (Retry-After), dormiu {slept}"
