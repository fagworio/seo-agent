"""Tests for the deterministic HTTP/redirect check (fake client, no network)."""

from hermes_seo_agent.checks.http import check_http


class _FakeResponse:
    def __init__(self, status_code, location=""):
        self.status_code = status_code
        self.headers = {"location": location} if location else {}


class _FakeClient:
    """Maps URL -> (status, location) responses, recording the call order."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        status, location = self.routes[url]
        return _FakeResponse(status, location)


def test_ok_page():
    client = _FakeClient({"https://x.com/a/": (200, "")})
    state = check_http(client, "https://x.com/a/")
    assert state["status_code"] == 200
    assert state["redirect_hops"] == 0


def test_single_redirect():
    client = _FakeClient({
        "https://x.com/a/": (301, "https://x.com/b/"),
        "https://x.com/b/": (200, ""),
    })
    state = check_http(client, "https://x.com/a/")
    assert state["status_code"] == 200
    assert state["redirect_hops"] == 1
    assert state["final_url"] == "https://x.com/b/"


def test_redirect_chain():
    client = _FakeClient({
        "https://x.com/a/": (301, "https://x.com/b/"),
        "https://x.com/b/": (302, "https://x.com/c/"),
        "https://x.com/c/": (200, ""),
    })
    state = check_http(client, "https://x.com/a/", max_hops=5)
    assert state["status_code"] == 200
    assert state["redirect_hops"] == 2


def test_redirect_loop_detected():
    client = _FakeClient({
        "https://x.com/a/": (301, "https://x.com/b/"),
        "https://x.com/b/": (301, "https://x.com/a/"),
    })
    state = check_http(client, "https://x.com/a/")
    assert state["redirect_loop"] is True


def test_hop_cap():
    client = _FakeClient({
        "https://x.com/a/": (301, "https://x.com/b/"),
        "https://x.com/b/": (301, "https://x.com/c/"),
        "https://x.com/c/": (301, "https://x.com/d/"),
        "https://x.com/d/": (301, "https://x.com/e/"),
        "https://x.com/e/": (301, "https://x.com/f/"),
        "https://x.com/f/": (200, ""),
    })
    state = check_http(client, "https://x.com/a/", max_hops=3)
    assert "too many redirects" in state["error"]


def test_404_reported():
    client = _FakeClient({"https://x.com/a/": (404, "")})
    state = check_http(client, "https://x.com/a/")
    assert state["status_code"] == 404
