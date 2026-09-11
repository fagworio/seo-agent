"""Execution budget/telemetry for external calls (#8).

Counts external API/HTTP calls (and retries/bytes/duration) so that a limit can
cap a cycle and a report can calibrate it. `max_calls=0` MEASURES everything and
never blocks (so you can observe real consumption before choosing a ceiling).

Pre-flight: `reserve()` is called BEFORE the network request, so the call that
would exceed the limit never leaves the machine.
"""
from __future__ import annotations

import threading
import time
from typing import Any


class BudgetExceeded(RuntimeError):
    """Raised when the configured call limit is reached (before the call)."""


class ExecutionBudget:
    """Thread-safe counter shared by connectors within a cycle.

    `max_calls` 0/None = unbounded (still measures). Connectors call
    :meth:`reserve` before the request (which raises if over the limit) and
    :meth:`record` after it (bytes/duration). Attempts that fail on the network
    are also counted (via `record_error`).
    """

    def __init__(self, max_calls: int = 0):
        self.max_calls = max_calls
        self._lock = threading.Lock()
        self._calls = 0
        self._blocked = 0
        self._bytes = 0
        self._retries = 0
        self._duration = 0.0
        self._kinds: dict[str, int] = {}

    # -- accounting ----------------------------------------------------------

    def reserve(self, kind: str = "http") -> None:
        """Conta UMA chamada externa ANTES de enviá-la (hard pre-flight).
        Levanta :class:`BudgetExceeded` quando o teto é atingido, de modo que a
        requisição que excederia NÃO sai na rede. `stats()["calls"]` reflete
        apenas chamadas REALMENTE realizadas; a tentativa bloqueada vai para
        `blocked_calls` (útil na calibragem do teto)."""
        with self._lock:
            if self.max_calls and self._calls >= self.max_calls:
                self._blocked += 1
                raise BudgetExceeded(
                    f"execution budget exceeded: {self._calls} calls >= {self.max_calls}")
            self._calls += 1
            self._kinds[kind] = self._kinds.get(kind, 0) + 1

    def record(self, *, bytes_: int = 0, duration: float = 0.0) -> None:
        with self._lock:
            self._bytes += max(bytes_, 0)
            self._duration += max(duration, 0.0)

    def record_error(self, kind: str = "http") -> None:
        """Conta uma tentativa que falhou na rede (timeout/connreset/DNS)."""
        with self._lock:
            key = f"{kind}_error"
            self._kinds[key] = self._kinds.get(key, 0) + 1

    def retry(self) -> None:
        """Conta UMA retentativa (tentativa adicional além da primeira)."""
        with self._lock:
            self._retries += 1

    def hit(self, kind: str = "cache") -> None:
        """Registra uma chamada EVITADA (cache) — NÃO conta no limite."""
        with self._lock:
            self._kinds[kind] = self._kinds.get(kind, 0) + 1

    def inc(self, kind: str = "http", *, bytes_: int = 0, duration: float = 0.0) -> None:
        """Conveniência (reserve+record) para chamadas não-HTTP."""
        self.reserve(kind)
        self.record(bytes_=bytes_, duration=duration)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            kinds = dict(self._kinds)
            return {
                "calls": self._calls,
                # tentativas bloqueadas ANTES da rede (teto atingido)
                "blocked_calls": self._blocked,
                # chamadas externas REALMENTE evitadas (cache de dataset por janela)
                "cache_hits": kinds.get("dataset_cache_hit", 0),
                # HTTP 304 reusa o corpo, mas a requisição HTTP ACONTECEU — não é
                # "chamada evitada"; por isso é reportado separadamente.
                "http_304": kinds.get("http_304", 0),
                "bytes": self._bytes,
                "retries": self._retries,
                "duration_s": round(self._duration, 3),
                "max_calls": self.max_calls,
                "by_kind": kinds,
            }


def make_budget(config: Any) -> ExecutionBudget:
    """Sempre devolve um budget: max_calls=0 MEDE sem nunca bloquear."""
    max_calls = int(getattr(config, "max_external_calls", 0) or 0)
    return ExecutionBudget(max_calls=max_calls)


_TIME = time.perf_counter
