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

    def handler(request):
        return httpx.Response(200, text="ok")

    http = HttpClient(transport=httpx.MockTransport(handler), budget=budget)
    http.get("https://x.com/a/")  # 1 chamada (dentro do limite)
    try:
        http.get("https://x.com/b/")  # 2ª → estoura
        raised = False
    except BudgetExceeded:
        raised = True
    assert raised, "a 2ª chamada deve estourar o orçamento (max_calls=1)"


def test_make_budget_off_when_zero():
    from types import SimpleNamespace
    cfg = SimpleNamespace(max_external_calls=0)
    assert make_budget(cfg) is None
    cfg2 = SimpleNamespace(max_external_calls=5)
    b = make_budget(cfg2)
    assert b is not None and b.max_calls == 5
