"""Tests for set-title write path: before/after snapshots + REST confirmation.

Covers the two production blockers:
  1. idempotence fingerprint includes the fix VALUE (see test_executor);
  2. set-title captures snapshot BEFORE, confirms rank_math_title via re-read
     REST, and captures snapshot AFTER (linked to the action) so `impact`
     detects the change — even when the rebuild is not yet visible.
"""

import argparse

from hermes_seo_agent.cli import _cmd_set_title
from hermes_seo_agent.config import Config
from hermes_seo_agent.connectors.static_site import PageSnapshot
from hermes_seo_agent.storage.db import Storage


class _FakeWP:
    """In-memory WP: get_post reflects updates (so the REST re-read confirms)."""

    def __init__(self, post):
        self.post = post

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_post_by_slug(self, slug):
        return self.post if self.post["slug"] == slug else None

    def get_post(self, post_id, **kwargs):
        return self.post

    def update_post_meta(self, post_id, meta):
        self.post["meta"].update(meta)
        return self.post


class _FakeStatic:
    """Static site whose visible title comes from a provider callable."""

    def __init__(self, title_for):
        self._title_for = title_for
        self.fetches = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetch_page(self, url):
        self.fetches.append(url)
        page = PageSnapshot(url, 200)
        page.title = self._title_for(url)
        page.meta_description = "md"
        page.canonical = url
        page.meta_robots = ""
        page.h1 = [page.title]
        page.body_text = "conteúdo " * 50
        page.html = "<html><body>conteúdo</body></html>"
        page.links = []
        return page


def _config(db_path) -> Config:
    return Config(
        wordpress_url="http://localhost",
        static_site_url="https://www.example.com",
        app_user="u", app_password="p",
        dry_run=False,
        google_credentials="fake-service-account.json",
        sqlite_path=str(db_path),
    )


def _run(monkeypatch, db_path, *, rebuild_visible: bool):
    post = {"id": 42, "slug": "meu-post",
            "meta": {"rank_math_title": "Título Antigo"}}
    wp = _FakeWP(post)

    if rebuild_visible:
        # O site reflete o WP: antes do update -> título antigo; depois -> novo.
        def _title_for(url):
            return post["meta"].get("rank_math_title") or "Título Antigo"
    else:
        def _title_for(url):
            return "Título Antigo"  # rebuild pendente: site nunca muda

    static = _FakeStatic(_title_for)
    monkeypatch.setattr("hermes_seo_agent.cli.WordPressClient", lambda cfg: wp)
    monkeypatch.setattr("hermes_seo_agent.cli.StaticSiteClient", lambda cfg: static)

    class _FakeGSC:
        def __init__(self, config):
            pass

        def page_metrics(self, url, **kwargs):
            return {"impressions": 100.0, "clicks": 1.0, "ctr": 0.01, "position": 5.0}

    monkeypatch.setattr("hermes_seo_agent.cli.SearchConsoleClient", _FakeGSC)

    args = argparse.Namespace(target="meu-post", title="Título Novo SEO")
    rc = _cmd_set_title(args, _config(db_path))
    return rc, wp, static


def _snapshots(db_path):
    with Storage(str(db_path)) as storage:
        return storage.page_snapshots("https://www.example.com/meu-post/")


def test_set_title_snapshot_before_and_after_when_rebuild_visible(tmp_path, monkeypatch):
    db = tmp_path / "st.db"
    rc, wp, static = _run(monkeypatch, db, rebuild_visible=True)

    snaps = _snapshots(db)
    assert len(snaps) == 2  # antes (sem link) + depois (com linked_action)
    assert snaps[0]["source"] == "set-title"
    assert snaps[0]["linked_action"] == ""
    assert snaps[0]["title"] == "Título Antigo"
    assert snaps[1]["linked_action"] != ""  # vinculada à ação (fingerprint do fix)
    assert snaps[1]["title"] == "Título Novo SEO"
    assert wp.post["meta"]["rank_math_title"] == "Título Novo SEO"


def test_set_title_waits_for_rebuild_with_warning(tmp_path, monkeypatch, capsys):
    db = tmp_path / "st2.db"
    rc, wp, static = _run(monkeypatch, db, rebuild_visible=False)

    snaps = _snapshots(db)
    # Só o snapshot ANTES existe; o DEPOIS virá do próximo audit/cycle pós-rebuild.
    assert len(snaps) == 1
    assert snaps[0]["source"] == "set-title"
    assert snaps[0]["linked_action"] == ""
    assert snaps[0]["title"] == "Título Antigo"

    out = capsys.readouterr().out
    assert "rebuild pendente" in out


def test_set_title_confirms_via_rest_and_records_expectation(tmp_path, monkeypatch, capsys):
    db = tmp_path / "st3.db"
    rc, wp, static = _run(monkeypatch, db, rebuild_visible=True)

    out = capsys.readouterr().out
    import json
    summary = json.loads(out)["summary"]
    assert summary["executed"] == 1
    assert summary["confirmed_via_rest"] is True
    assert summary["snapshot_before"] is True
    with Storage(str(db)) as storage:
        exps = storage.conn.execute(
            "SELECT source FROM seo_expectations WHERE url = ?",
            ("https://www.example.com/meu-post/",),
        ).fetchall()
    assert ("set-title",) in exps


class _WPThatDoesNotPersist(_FakeWP):
    """Simula mu-plugin ausente: update_post_meta 'aceita' mas a re-leitura
    REST continua devolvendo o valor antigo."""

    def update_post_meta(self, post_id, meta):
        self.post["meta"].update(meta)
        self.post["_persisted"] = False  # escrita 'aceita', persistência falha
        return self.post

    def get_post(self, post_id, **kwargs):
        if not self.post.get("_persisted", True):
            # devolve o estado ANTERIOR à escrita (meta nunca persistiu)
            return {"id": post_id, "meta": {"rank_math_title": "Título Antigo"}}
        return self.post


def test_set_title_rest_divergence_is_unverified_and_retry_allowed(
        tmp_path, monkeypatch, capsys):
    """Confirmação REST divergente => unverified (não executed), sem
    expectation, e um retry com o MESMO título volta a executar."""
    import json

    db = tmp_path / "st4.db"
    post = {"id": 42, "slug": "meu-post", "meta": {"rank_math_title": "Título Antigo"}}
    wp = _WPThatDoesNotPersist(post)
    static = _FakeStatic(lambda url: "Título Antigo")
    monkeypatch.setattr("hermes_seo_agent.cli.WordPressClient", lambda cfg: wp)
    monkeypatch.setattr("hermes_seo_agent.cli.StaticSiteClient", lambda cfg: static)

    class _FakeGSC:
        def __init__(self, config):
            pass

        def page_metrics(self, url, **kwargs):
            return {"impressions": 100.0, "clicks": 1.0, "ctr": 0.01, "position": 5.0}

    monkeypatch.setattr("hermes_seo_agent.cli.SearchConsoleClient", _FakeGSC)

    args = argparse.Namespace(target="meu-post", title="Título Novo SEO")
    rc = _cmd_set_title(args, _config(db))
    first = json.loads(capsys.readouterr().out)
    assert first["summary"]["executed"] == 0
    assert first["summary"]["unverified"] == 1
    assert first["summary"]["confirmed_via_rest"] is False
    assert any("unverified" in w for w in first["warnings"])
    # sem expectation (ação não confirmada não deve gerar projeção)
    with Storage(str(db)) as storage:
        assert storage.conn.execute(
            "SELECT COUNT(*) FROM seo_expectations WHERE url = ?",
            ("https://www.example.com/meu-post/",),
        ).fetchone()[0] == 0

    # RETRY com o mesmo título NÃO é bloqueado pela idempotência (unverified):
    # a segunda tentativa volta a executar e sobrescreve o registro unverified.
    rc = _cmd_set_title(args, _config(db))
    second = json.loads(capsys.readouterr().out)
    assert second["summary"]["unverified"] == 1
    with Storage(str(db)) as storage:
        rows = storage.conn.execute(
            "SELECT status FROM actions WHERE rule_id = 'title_manual'"
        ).fetchall()
        count = storage.conn.execute(
            "SELECT COUNT(*) FROM actions WHERE rule_id = 'title_manual'"
        ).fetchone()[0]
    assert [r[0] for r in rows] == ["unverified"]  # UPSERT: sobrescreveu, não duplicou
    assert count == 1


def test_title_matches_visible_tolerates_brand_suffix(tmp_path, monkeypatch, capsys):
    """Rebuild detectado mesmo com sufixo de marca/template no <title>."""
    import json

    from hermes_seo_agent.cli import _title_matches_visible

    assert _title_matches_visible("Título Novo SEO", "Título Novo SEO | Unicórnio Hater")
    assert _title_matches_visible("Título Novo SEO", "titulo novo seo - marca")
    assert not _title_matches_visible("Título Novo SEO", "Título Antigo | Unicórnio Hater")
