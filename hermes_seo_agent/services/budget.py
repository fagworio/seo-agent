"""Execution budget/telemetry for external calls (#8).

Counts external API/HTTP calls (and retries/bytes/duration) so that a future
loop that starts calling an API per item cannot silently blow the limit. The
budget is OPT-IN: only the `RunContext` (scheduler) installs one (from
config.max_external_calls); standalone connectors/tests run unbounded.
"""
from __future__ import annotations

import threading
import time
from typing import Any


class BudgetExceeded(RuntimeError):
    """Raised when the configured call limit is reached."""


class ExecutionBudget:
    """Thread-safe counter shared by connectors within a cycle.

    `max_calls` 0/None = unbounded. Callers call :meth:`inc` around each external
    request; when the total exceeds `max_calls`, a :class:`BudgetExceeded` is
    raised (so the cycle aborts instead of silently spending more).
    """

    def __init__(self, max_calls: int = 0):
        self.max_calls = max_calls
        self._lock = threading.Lock()
        self._calls = 0
        self._bytes = 0
        self._retries = 0
        self._duration = 0.0
        self._kinds: dict[str, int] = {}

    def inc(self, kind: str = "http", *, bytes_: int = 0,
            duration: float = 0.0) -> None:
        with self._lock:
            self._calls += 1
            self._bytes += max(bytes_, 0)
            self._duration += max(duration, 0.0)
            self._kinds[kind] = self._kinds.get(kind, 0) + 1
            if self.max_calls and self._calls > self.max_calls:
                raise BudgetExceeded(
                    f"execution budget exceeded: {self._calls} calls > {self.max_calls}")

    def retry(self) -> None:
        """Conta UMA retentativa (uma tentativa adicional além da primeira)."""
        with self._lock:
            self._retries += 1

    def hit(self, kind: str = "cache") -> None:
        """Registra uma chamada EVITADA (cache hit) — não conta no limite."""
        with self._lock:
            self._kinds[kind] = self._kinds.get(kind, 0) + 1

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "calls": self._calls,
                "cache_hits": sum(v for k, v in self._kinds.items() if k.startswith("cache")
                                  or k.endswith("_hit") or k.endswith("_304")),
                "bytes": self._bytes,
                "retries": self._retries,
                "duration_s": round(self._duration, 3),
                "max_calls": self.max_calls,
                "by_kind": dict(self._kinds),
            }


def make_budget(config: Any) -> ExecutionBudget:
    """Sempre devolve um budget: max_calls=0 MEDE sem nunca bloquear.

    Antes, max_calls=0 devolvia None -> sem limite E SEM TELEMETRIA, o oposto do
    que se precisa para medir o consumo real e só depois calibrar o teto.
    """
    max_calls = int(getattr(config, "max_external_calls", 0) or 0)
    return ExecutionBudget(max_calls=max_calls)


_TIME = time.perf_counter
