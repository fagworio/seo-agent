"""Control plane API (framework-agnóstico; transporte stdlib enquanto o ambiente
não tem FastAPI — ver ADR-0009)."""

from __future__ import annotations

from typing import Any

from .http import HttpRequest, HttpResponse
from .router import Router
from .app import create_app


def create_router(storage: Any, config: Any) -> Router:
    return Router(storage, config)


def make_router_factory(storage_path: str, config: Any):
    """Fábrica para o servidor threaded: uma Storage/Router por request."""
    from ..storage.db import Storage

    def factory() -> Router:
        return Router(Storage(storage_path), config)

    return factory


def handle(request: HttpRequest, storage: Any, config: Any) -> HttpResponse:
    return Router(storage, config).handle(request)


__all__ = ["Router", "HttpRequest", "HttpResponse", "create_router",
           "make_router_factory", "handle", "create_app"]
