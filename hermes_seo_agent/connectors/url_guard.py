"""Guard de URLs externas (SSRF).

Sitemap `<loc>`, redirects e fetches de página nunca devem induzir o servidor a
requisitar recursos internos (127.0.0.1, 169.254.169.254, 10/8, ...). A defesa:

  1. esquema http/https apenas;
  2. host na ALLOWLIST dos hosts do próprio site (static_site_url/sitemap_url);
  3. rejeição de IP literal privado/loopback/link-local/reservado/multicast;
  4. resolução DNS OPCIONAL (default off) que rejeita hosts que resolvem para
     IPs proibidos — habilitável por config quando o ambiente resolver DNS.
"""
from __future__ import annotations

import ipaddress
import socket
from functools import lru_cache
from typing import Any, Iterable
from urllib.parse import urlparse

from .base import ConnectorError


class UnsafeUrlError(ConnectorError):
    """URL externa rejeitada pelo guard (SSRF)."""


def _forbidden_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])  # descarta zone-id IPv6
    except ValueError:
        return True  # não é IP válido -> trata como proibido (fail closed)
    if (addr.is_private or addr.is_loopback or addr.is_link_local
            or addr.is_multicast or addr.is_reserved or addr.is_unspecified):
        return True
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        return _forbidden_ip(str(mapped))
    return False


@lru_cache(maxsize=1024)
def _host_resolves_to_forbidden(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True  # não resolvido -> fail closed
    return any(_forbidden_ip(info[4][0]) for info in infos)


def allowed_hosts_from_config(config: Any) -> set[str]:
    """Hosts permitidos: os do próprio site (static_site_url + sitemap_url)."""
    hosts: set[str] = set()
    for attr in ("static_site_url", "sitemap_url"):
        host = urlparse(getattr(config, attr, "") or "").hostname
        if host:
            hosts.add(host.lower())
    return hosts


def validate_external_url(url: str, *, allowed_hosts: Iterable[str] | None = None,
                          resolve: bool = False) -> None:
    """Levanta :class:`UnsafeUrlError` se a URL não for segura para fetch."""
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError(f"esquema não permitido: {parsed.scheme or '(vazio)'}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise UnsafeUrlError("URL sem host")

    # IP literal: rejeita direto (cobre http://127.0.0.1, 169.254.169.254, ...).
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        if _forbidden_ip(host):
            raise UnsafeUrlError(f"IP interno/privado bloqueado: {host}")
        literal_ip = True
    except ValueError:
        literal_ip = False

    if allowed_hosts is not None:
        allow = {h.lower() for h in allowed_hosts}
        if allow and host not in allow:
            raise UnsafeUrlError(f"host fora da allowlist: {host}")

    if resolve and not literal_ip and _host_resolves_to_forbidden(host):
        raise UnsafeUrlError(f"host resolve para IP interno/privado: {host}")
