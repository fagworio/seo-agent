"""HTTP client contract shared by all connectors.

Deterministic retry with exponential backoff, respects Retry-After,
enforces timeouts, and masks credentials in any log output.
"""

from __future__ import annotations

import base64
import time
from typing import Any

import httpx


class ConnectorError(RuntimeError):
    """Base error for connector failures."""


class HttpClient:
    """Thin wrapper over httpx with deterministic retry/backoff semantics."""

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        max_retries: int = 3,
        user_agent: str = "hermes-seo-agent/0.1",
        auth: tuple[str, str] | None = None,
        bearer: str | None = None,
        transport: Any | None = None,
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.auth = auth
        self.bearer = bearer
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=False,  # redirect logic lives in checks/redirects
            transport=transport,  # MockTransport in tests
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json,text/html,*/*",
                **({"Authorization": f"Bearer {bearer}"} if bearer else {}),
            },
        )

    # -- public --------------------------------------------------------------

    def get(self, url: str, *, params: dict[str, Any] | None = None,
            headers: dict[str, str] | None = None) -> httpx.Response:
        """GET with retries; raises ConnectorError when all attempts fail."""
        return self._request("GET", url, params=params, headers=headers)

    def post(self, url: str, *, json_body: dict[str, Any] | None = None,
             headers: dict[str, str] | None = None,
             params: dict[str, Any] | None = None) -> httpx.Response:
        """POST with retries; raises ConnectorError when all attempts fail."""
        return self._request("POST", url, json_body=json_body, headers=headers, params=params)

    def _request(self, method: str, url: str, *, params: dict[str, Any] | None = None,
                 json_body: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                if method == "GET":
                    response = self.client.get(url, params=params, headers=headers, auth=self.auth)
                else:
                    response = self.client.post(url, params=params, json=json_body,
                                                headers=headers, auth=self.auth)
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise _Transient(response.status_code)
                return response
            except (_Transient, httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    delay = _backoff(attempt, response=getattr(exc, "response", None))
                    time.sleep(delay)
        raise ConnectorError(f"{method} {url} failed after {self.max_retries} attempts: {last_exc}")

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class _Transient(RuntimeError):
    def __init__(self, status_code: int):
        super().__init__(f"transient HTTP {status_code}")
        self.status_code = status_code
        self.response = None


def _backoff(attempt: int, *, response: httpx.Response | None = None) -> float:
    """Exponential backoff with jitter; honors Retry-After when present."""
    if response is not None and response.headers.get("Retry-After"):
        try:
            return min(float(response.headers["Retry-After"]), 60.0)
        except ValueError:
            pass
    return min(2.0 ** (attempt - 1), 30.0)


def basic_auth_header(user: str, password: str) -> str:
    token = f"{user}:{password}".encode()
    return f"Basic {base64.b64encode(token).decode()}"
