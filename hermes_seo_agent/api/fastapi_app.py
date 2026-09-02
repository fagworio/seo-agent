"""FastAPI/ASGI adapter for the control-plane Router.

The Router remains the one place that enforces sessions, CSRF and RBAC. This
adapter only translates ASGI HTTP requests into its tested request contract.
"""
from typing import Any


def create_app(storage_path: str, config: Any):
    """Create the production FastAPI application lazily."""
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("FastAPI não está instalado; instale as dependências do projeto.") from exc
    from ..storage.db import Storage
    from .http import HttpRequest
    from .router import Router

    app = FastAPI(title="SEO Agent Control Plane", version="0.1.0", openapi_url="/api/v1/openapi.json", docs_url="/api/docs")

    @app.api_route("/api/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def control_plane(request: Request, path: str):
        storage = Storage(storage_path)
        try:
            response = Router(storage, config).handle(HttpRequest(
                method=request.method, path=f"/api/v1/{path}",
                query=dict(request.query_params),
                headers={key.lower(): value for key, value in request.headers.items()},
                body=await request.body(), client_ip=request.client.host if request.client else "",
            ))
        finally:
            storage.close()
        result = JSONResponse(status_code=response.status, content=response.body)
        if response.set_cookie and "header" in response.set_cookie:
            result.headers.append("set-cookie", response.set_cookie["header"])
        return result
    return app
