"""Rate limiting por janela deslizante (determinístico, clock injetável).

Usado em endpoints sensíveis (login, mfa/verify, forgot/reset-password), por
chaves como IP e conta. Backoff progressivo é responsabilidade do chamador (o
AuthService já endurece o login por conta+IP via `login_attempts`).
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Callable


def _default_clock() -> float:
    return time.time()


class SlidingWindowLimiter:
    """Limita `max_events` a cada `window_seconds` por chave.

    Implanta janela deslizante com deque (O(1) amortizado). O estado é
    por-processo (adequado p/ MVP single-worker); produção multi-instância
    deve trocar por contador em storage compartilhado.
    """

    def __init__(
        self,
        *,
        max_events: int,
        window_seconds: int,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if max_events < 1:
            raise ValueError("max_events must be >= 1")
        if window_seconds < 1:
            raise ValueError("window_seconds must be >= 1")
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._clock = clock or _default_clock
        self._events: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        """Registra um evento e devolve False se o limite foi excedido."""
        now = self._clock()
        q = self._events.setdefault(key, deque())
        while q and q[0] <= now - self.window_seconds:
            q.popleft()
        if len(q) >= self.max_events:
            return False
        q.append(now)
        return True

    def remaining(self, key: str) -> int:
        now = self._clock()
        q = self._events.get(key)
        if not q:
            return self.max_events
        while q and q[0] <= now - self.window_seconds:
            q.popleft()
        return max(0, self.max_events - len(q))

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._events.clear()
        else:
            self._events.pop(key, None)
