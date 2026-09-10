"""Regressão P0 (SSRF): URLs internas/host fora da allowlist são bloqueadas."""
import httpx
import pytest

from hermes_seo_agent.config import Config
from hermes_seo_agent.connectors.base import HttpClient
from hermes_seo_agent.connectors.static_site import StaticSiteClient
from hermes_seo_agent.connectors.url_guard import UnsafeUrlError, validate_external_url


@pytest.mark.parametrize("bad", [
    "http://127.0.0.1:3000/admin",
    "http://localhost/",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/",
    "http://192.168.1.1/",
    "http://172.16.0.1/",
    "file:///etc/passwd",
    "ftp://x.com/a",
])
def test_blocks_internal_and_bad_scheme(bad):
    with pytest.raises(UnsafeUrlError):
        validate_external_url(bad, allowed_hosts={"x.com"})


def test_blocks_host_outside_allowlist():
    with pytest.raises(UnsafeUrlError):
        validate_external_url("https://evil.com/p/", allowed_hosts={"x.com"})


def test_allows_allowlisted_host():
    validate_external_url("https://x.com/p/", allowed_hosts={"x.com"})  # não levanta


def test_static_client_blocks_ssrf_loc(tmp_path):
    cfg = Config(wordpress_url="http://x", sitemap_url="https://x.com/sitemap_index.xml",
                 static_site_url="https://x.com", sqlite_path=str(tmp_path / "g.db"),
                 http_cache_dir=str(tmp_path / "c"), google_credentials="", ga4_property_id="")
    http = HttpClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="x")))
    static = StaticSiteClient(cfg, http=http)
    with pytest.raises(UnsafeUrlError):
        static.fetch_page("http://127.0.0.1:3000/admin")           # IP interno
    with pytest.raises(UnsafeUrlError):
        static.fetch_page("http://169.254.169.254/latest/meta-data/")  # link-local
    with pytest.raises(UnsafeUrlError):
        static.fetch_page("https://evil.com/x/")                  # fora da allowlist
    static.close()


def test_redirect_hop_to_internal_ip_is_blocked(tmp_path):
    from hermes_seo_agent.checks.http import check_http

    cfg = Config(wordpress_url="http://x", sitemap_url="https://x.com/sitemap_index.xml",
                 static_site_url="https://x.com", sqlite_path=str(tmp_path / "g2.db"),
                 http_cache_dir=str(tmp_path / "c2"), google_credentials="", ga4_property_id="")

    def handler(request):
        # x.com responde 302 apontando para a metadata interna (SSRF via redirect)
        return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

    http = HttpClient(transport=httpx.MockTransport(handler))
    static = StaticSiteClient(cfg, http=http)
    info = check_http(static.http, "https://x.com/p/", validate_url=static.validate_url)
    assert info["status_code"] == 0
    assert "blocked redirect" in info["error"]
    static.close()
