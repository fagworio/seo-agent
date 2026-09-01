"""HTTP status + redirect chain checks (deterministic)."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import Config
from ..connectors.base import HttpClient


def check_http(
    client: HttpClient,
    url: str,
    *,
    max_hops: int = 5,
) -> dict[str, Any]:
    """Follow redirects deterministically; return status, final URL, chain.

    httpx history is unreliable with follow_redirects=False, so redirects are
    followed manually hop-by-hop with a hard cap (loop/chain protection).
    """
    chain: list[dict[str, Any]] = []
    current = url
    seen: set[str] = set()
    for _ in range(max_hops + 1):
        if current in seen:
            return {
                "url": url,
                "status_code": 0,
                "final_url": current,
                "redirect_chain": chain,
                "redirect_loop": True,
                "error": "redirect loop detected",
            }
        seen.add(current)
        try:
            response = client.get(current)
        except Exception as exc:  # ConnectorError / httpx
            return {
                "url": url,
                "status_code": 0,
                "final_url": current,
                "redirect_chain": chain,
                "redirect_loop": False,
                "error": str(exc),
            }
        chain.append(
            {
                "url": current,
                "status_code": response.status_code,
                "location": response.headers.get("location", ""),
            }
        )
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if not location:
                return _result(url, chain, current, status=response.status_code, error="redirect without Location")
            current = _join(current, location)
            continue
        return _result(url, chain, current, status=response.status_code)
    return _result(url, chain, current, status=0, error=f"too many redirects (> {max_hops})")


def _join(base: str, location: str) -> str:
    if location.startswith(("http://", "https://")):
        return location
    from urllib.parse import urljoin

    return urljoin(base, location)


def _result(
    url: str,
    chain: list[dict[str, Any]],
    final_url: str,
    *,
    status: int,
    error: str = "",
) -> dict[str, Any]:
    return {
        "url": url,
        "status_code": status,
        "final_url": final_url,
        "redirect_chain": chain,
        "redirect_hops": max(0, len(chain) - 1),
        "redirect_loop": False,
        "error": error,
    }
