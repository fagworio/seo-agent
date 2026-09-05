"""corpus_source: escolha de fonte do corpus (M2) — WP preferido, static fallback."""
from types import SimpleNamespace

from hermes_seo_agent.config import Config
from hermes_seo_agent.report.corpus_source import corpus_source


class _FakeWP:
    def __init__(self, *, posts, post):
        self._posts = posts
        self._post = post
        self.closed = False

    def list_posts(self, **kw):
        return self._posts

    def get_post(self, post_id, **kw):
        return self._post

    def close(self):
        self.closed = True


class _FakeStatic:
    def __init__(self, urls, page):
        self._urls = urls
        self._page = page

    def all_sitemap_urls(self):
        return self._urls

    def fetch_page(self, url):
        return self._page

    def close(self):
        pass


def test_corpus_source_prefers_wordpress_api(monkeypatch):
    cfg = Config(wordpress_url="https://prod.unicorniohater.com.br",
                 sitemap_url="https://x.com/sitemap_index.xml",
                 sqlite_path=":memory:")
    wp = _FakeWP(
        posts=[{"link": "https://x.com/a/", "id": 1},
               {"link": "https://x.com/b/", "id": 2}],
        post={"title": {"rendered": "Título A"},
              "content": {"rendered": "<h2>Seção 1</h2><p>corpo do post</p>"},
              "link": "https://x.com/a/"})
    monkeypatch.setattr("hermes_seo_agent.report.corpus_source.WordPressClient",
                        lambda c, http=None: wp)

    src = corpus_source(cfg)
    assert src.name == "wordpress"
    assert src.urls == ["https://x.com/a", "https://x.com/b"]  # normalizadas (sem / final)
    snap = src.fetch("https://x.com/a/")
    assert snap.title == "Título A"
    assert snap.h1 == ["Título A"]
    assert snap.h2s == ["Seção 1"]
    assert snap.body_text == "Seção 1 corpo do post"  # HTML strippado
    src.close()
    assert wp.closed is True


def test_corpus_source_falls_back_to_static_when_wp_fails(monkeypatch):
    cfg = Config(wordpress_url="https://prod.unicorniohater.com.br",
                 sitemap_url="https://x.com/sitemap_index.xml",
                 sqlite_path=":memory:")

    def _list_posts(**kw):
        raise RuntimeError("wp down")

    class _WPOff:
        list_posts = _list_posts
        def close(self): pass

    monkeypatch.setattr("hermes_seo_agent.report.corpus_source.WordPressClient",
                        lambda c, http=None: _WPOff())
    static = _FakeStatic(["https://x.com/a/"],
                         SimpleNamespace(url="https://x.com/a/", title="T"))
    monkeypatch.setattr("hermes_seo_agent.report.corpus_source.StaticSiteClient",
                        lambda c, http=None: static)

    src = corpus_source(cfg)
    assert src.name == "static"
    assert src.urls == ["https://x.com/a/"]
    src.close()


def test_corpus_source_falls_back_to_static_when_no_wp_url(monkeypatch):
    cfg = Config(wordpress_url="", sitemap_url="https://x.com/sitemap_index.xml",
                 sqlite_path=":memory:")
    static = _FakeStatic(["https://x.com/a/"], SimpleNamespace(url="x", title="T"))
    monkeypatch.setattr("hermes_seo_agent.report.corpus_source.StaticSiteClient",
                        lambda c, http=None: static)
    src = corpus_source(cfg)
    assert src.name == "static"
    src.close()
