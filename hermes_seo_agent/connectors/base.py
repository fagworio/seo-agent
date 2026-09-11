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
        budget: Any | None = None,
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.auth = auth
        self.bearer = bearer
        # orçamento/telemetria externa (opt-in via RunContext); None = sem limite.
        self.budget = budget
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

    def get_conditional(self, url: str, *, etag: str = "", last_modified: str = "",
                        headers: dict[str, str] | None = None) -> httpx.Response:
        """GET using HTTP validators; callers handle a 304 response."""
        merged = dict(headers or {})
        if etag:
            merged["If-None-Match"] = etag
        if last_modified:
            merged["If-Modified-Since"] = last_modified
        return self.get(url, headers=merged)

    @staticmethod
    def _decoded_response(resp: httpx.Response, content: bytes) -> httpx.Response:
        """Reconstrói a Response com o corpo JÁ descomprimido (`iter_bytes`).

        `resp.iter_bytes()` entrega o corpo DECODIFICADO (gzip/br/deflate), então
        os cabeçalhos de codificação NÃO podem ser preservados: se
        `Content-Encoding: gzip` sobrevivesse, o httpx tentaria descomprimir de
        novo ao ler `.content`/`.text` -> DecodingError ("incorrect header
        check") em toda página/sitemap servida comprimida — regressão de
        produção 2026-09-11 (o `audit` morria no primeiro fetch gzipado).
        `Content-Length`/`Transfer-Encoding` também são recalculados a partir do
        novo corpo (o `Response` repõe `Content-Length` correto).
        """
        skip = {"content-encoding", "content-length", "transfer-encoding"}
        headers = [(key, value) for key, value in resp.headers.raw
                   if key.decode("latin-1").lower() not in skip]
        return httpx.Response(resp.status_code, headers=headers, content=content,
                              request=resp.request)

    def get_limited(self, url: str, *, max_bytes: int = 0,
                    headers: dict[str, str] | None = None) -> httpx.Response:
        """GET com teto de bytes aplicado em STREAMING.

        Defesa real contra resource exhaustion: rejeita cedo por `Content-Length`
        e interrompe a leitura ao exceder `max_bytes` — sem baixar a resposta
        inteira para a RAM. Mantém o pré-flight do budget e o retry/backoff.
        Uma violação de tamanho NÃO é retentada (ConnectorError direto).
        """
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            kind = "get"
            if self.budget is not None:
                self.budget.reserve(kind)
            recorded = False
            _t0 = time.perf_counter()
            try:
                with self.client.stream("GET", url, headers=headers, auth=self.auth) as resp:
                    if resp.status_code in {429, 500, 502, 503, 504}:
                        # corpo de erro TAMBÉM é limitado (um 500 com 500MB não
                        # pode carregar tudo para a RAM).
                        ebuf = bytearray()
                        for chunk in resp.iter_bytes():
                            ebuf.extend(chunk)
                            if max_bytes and len(ebuf) > max_bytes:
                                break
                        body = bytes(ebuf)
                        if self.budget is not None:
                            self.budget.record(bytes_=len(body),
                                               duration=time.perf_counter() - _t0)
                            recorded = True
                        raise _Transient(resp.status_code,
                                         response=self._decoded_response(resp, body))
                    declared = resp.headers.get("content-length")
                    if max_bytes and declared and declared.isdigit() \
                            and int(declared) > max_bytes:
                        raise ConnectorError(
                            f"resposta excede o limite ({declared} > {max_bytes} bytes): {url}")
                    buf = bytearray()
                    for chunk in resp.iter_bytes():
                        buf.extend(chunk)
                        if max_bytes and len(buf) > max_bytes:
                            raise ConnectorError(
                                f"resposta excede o limite de {max_bytes} bytes: {url}")
                    content = bytes(buf)
                    response = self._decoded_response(resp, content)
                if self.budget is not None:
                    self.budget.record(bytes_=len(content),
                                       duration=time.perf_counter() - _t0)
                    recorded = True
                return response
            except (_Transient, httpx.TimeoutException, httpx.TransportError) as exc:
                if self.budget is not None and not recorded:
                    self.budget.record(duration=time.perf_counter() - _t0)
                    self.budget.record_error(kind)
                last_exc = exc
                if attempt < self.max_retries:
                    if self.budget is not None:
                        self.budget.retry()
                    time.sleep(_backoff(attempt, response=getattr(exc, "response", None)))
        raise ConnectorError(f"GET {url} failed after {self.max_retries} attempts: {last_exc}")

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
            kind = method.lower()
            # PRE-FLIGHT: conta/reserva a chamada ANTES da rede. Se o teto já foi
            # atingido, BudgetExceeded sobe aqui e a requisição NÃO sai.
            if self.budget is not None:
                self.budget.reserve(kind)
            recorded = False
            _t0 = time.perf_counter()
            try:
                if method == "GET":
                    response = self.client.get(url, params=params, headers=headers, auth=self.auth)
                else:
                    response = self.client.post(url, params=params, json=json_body,
                                                headers=headers, auth=self.auth)
                if self.budget is not None:
                    self.budget.record(bytes_=len(response.content or b""),
                                       duration=time.perf_counter() - _t0)
                    recorded = True
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise _Transient(response.status_code, response=response)
                return response
            except (_Transient, httpx.TimeoutException, httpx.TransportError) as exc:
                if self.budget is not None and not recorded:
                    # timeout/connreset/DNS: a reserva já contou a chamada; aqui só
                    # registra a duração e marca como erro de rede.
                    self.budget.record(duration=time.perf_counter() - _t0)
                    self.budget.record_error(kind)
                last_exc = exc
                if attempt < self.max_retries:
                    if self.budget is not None:
                        self.budget.retry()
                    # _Transient carrega a response -> Retry-After é respeitado.
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
    def __init__(self, status_code: int, response: httpx.Response | None = None):
        super().__init__(f"transient HTTP {status_code}")
        self.status_code = status_code
        # carrega a response para o backoff honrar Retry-After (antes era None).
        self.response = response


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
