from types import SimpleNamespace

import pytest

from hermes_seo_agent.config import Config
from hermes_seo_agent.lanes.handlers import handler_title_execution
from hermes_seo_agent.lanes.title_decision import make_decision, persist_decision
from hermes_seo_agent.storage.db import Storage


class _FakeWP:
    def __init__(self):
        self.title = "Título antigo"
        self.writes = []

    def get_post(self, post_id):
        return {"id": post_id, "meta": {"rank_math_title": self.title}}

    def update_post_meta(self, post_id, meta):
        self.writes.append((post_id, meta))
        self.title = meta["rank_math_title"]
        return self.get_post(post_id)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


class _FakeStatic:
    def __init__(self):
        self.title = "Título antigo"
        self.fetches = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def fetch_page(self, url):
        self.fetches += 1
        return SimpleNamespace(status_code=200, title=self.title)


def test_title_execution_writes_and_confirms(monkeypatch, tmp_path):
    db = tmp_path / "title-worker.db"
    config = Config(wordpress_url="http://localhost", sqlite_path=str(db),
                    dry_run=False, title_engine_mode="auto")
    fake_wp = _FakeWP()

    import hermes_seo_agent.config as config_module
    import hermes_seo_agent.connectors.wordpress as wp_module

    monkeypatch.setattr(config_module, "load_config", lambda: config)
    monkeypatch.setattr(wp_module, "WordPressClient", lambda cfg: fake_wp)

    decision = make_decision(
        url="https://example.com/post", post_id=7,
        before="Título antigo", after="Título novo",
        confidence=0.9, rollout={"writes_allowed": True},
    )
    with Storage(str(db)) as store:
        persist_decision(store, decision)

    result = handler_title_execution({
        "work_item_id": decision.decision_id,
        "payload": {
            "decision_id": decision.decision_id,
            "url": decision.url,
            "post_id": decision.post_id,
            "field": "rank_math_title",
            "before": decision.before,
            "after": decision.after,
            "public_verification": False,
        },
    }, SimpleNamespace(db_path=str(db)))

    assert result["status"] == "executed"
    assert fake_wp.writes == [(7, {"rank_math_title": "Título novo"})]
    with Storage(str(db)) as store:
        assert store.title_decision(decision.decision_id)["status"] == "executed"


def test_title_execution_marks_stale_without_writing(monkeypatch, tmp_path):
    db = tmp_path / "title-worker-stale.db"
    config = Config(wordpress_url="http://localhost", sqlite_path=str(db),
                    dry_run=False, title_engine_mode="auto")
    fake_wp = _FakeWP()
    fake_wp.title = "Título alterado por humano"

    import hermes_seo_agent.config as config_module
    import hermes_seo_agent.connectors.wordpress as wp_module

    monkeypatch.setattr(config_module, "load_config", lambda: config)
    monkeypatch.setattr(wp_module, "WordPressClient", lambda cfg: fake_wp)

    decision = make_decision(
        url="https://example.com/post", post_id=7,
        before="Título antigo", after="Título novo",
        confidence=0.9, rollout={"writes_allowed": True},
    )
    with Storage(str(db)) as store:
        persist_decision(store, decision)

    result = handler_title_execution({
        "work_item_id": decision.decision_id,
        "payload": {
            "decision_id": decision.decision_id,
            "url": decision.url,
            "post_id": decision.post_id,
            "field": "rank_math_title",
            "before": decision.before,
            "after": decision.after,
            "public_verification": False,
        },
    }, SimpleNamespace(db_path=str(db)))

    assert result["status"] == "stale"
    assert fake_wp.writes == []
    with Storage(str(db)) as store:
        assert store.title_decision(decision.decision_id)["status"] == "stale"


def test_title_execution_observe_never_writes(monkeypatch, tmp_path):
    db = tmp_path / "title-worker-observe.db"
    config = Config(wordpress_url="http://localhost", sqlite_path=str(db),
                    dry_run=False, title_engine_mode="observe")
    fake_wp = _FakeWP()
    import hermes_seo_agent.config as config_module
    import hermes_seo_agent.connectors.wordpress as wp_module

    monkeypatch.setattr(config_module, "load_config", lambda: config)
    monkeypatch.setattr(wp_module, "WordPressClient", lambda cfg: fake_wp)

    with pytest.raises(RuntimeError, match="TITLE_ENGINE_MODE=observe"):
        handler_title_execution({
            "work_item_id": "decision-observe",
            "payload": {"decision_id": "decision-observe",
                        "url": "https://example.com/post", "post_id": 7,
                        "field": "rank_math_title", "before": "old",
                        "after": "new"},
        }, SimpleNamespace(db_path=str(db)))
    assert fake_wp.writes == []


def test_title_execution_revalidates_persisted_rollout(monkeypatch, tmp_path):
    db = tmp_path / "title-worker-authorization.db"
    config = Config(wordpress_url="http://localhost", sqlite_path=str(db),
                    dry_run=False, title_engine_mode="auto")
    fake_wp = _FakeWP()
    import hermes_seo_agent.config as config_module
    import hermes_seo_agent.connectors.wordpress as wp_module

    monkeypatch.setattr(config_module, "load_config", lambda: config)
    monkeypatch.setattr(wp_module, "WordPressClient", lambda cfg: fake_wp)
    decision = make_decision(
        url="https://example.com/post", post_id=7,
        before="Título antigo", after="Título novo", confidence=0.9,
        rollout={"mode": "approval", "writes_allowed": False},
    )
    with Storage(str(db)) as store:
        persist_decision(store, decision)

    with pytest.raises(RuntimeError, match="sem autorização persistida"):
        handler_title_execution({
            "work_item_id": decision.decision_id,
            "payload": {"decision_id": decision.decision_id,
                        "url": decision.url, "post_id": decision.post_id,
                        "field": "rank_math_title", "before": decision.before,
                        "after": decision.after, "public_verification": False},
        }, SimpleNamespace(db_path=str(db)))
    assert fake_wp.writes == []


def test_title_execution_waits_for_public_html_and_recovers_without_rewrite(
        monkeypatch, tmp_path):
    """REST confirmado não fecha o ciclo enquanto o rebuild não propagou."""
    db = tmp_path / "title-worker-public.db"
    config = Config(wordpress_url="http://localhost", sqlite_path=str(db),
                    static_site_url="https://example.com", dry_run=False,
                    title_engine_mode="auto")
    fake_wp = _FakeWP()
    fake_static = _FakeStatic()

    import hermes_seo_agent.config as config_module
    import hermes_seo_agent.connectors.wordpress as wp_module
    import hermes_seo_agent.connectors.static_site as static_module

    monkeypatch.setattr(config_module, "load_config", lambda: config)
    monkeypatch.setattr(wp_module, "WordPressClient", lambda cfg: fake_wp)
    monkeypatch.setattr(static_module, "StaticSiteClient", lambda cfg: fake_static)

    decision = make_decision(
        url="https://example.com/post", post_id=7,
        before="Título antigo", after="Título novo",
        confidence=0.9, rollout={"writes_allowed": True},
    )
    with Storage(str(db)) as store:
        persist_decision(store, decision)

    payload = {
        "decision_id": decision.decision_id,
        "url": decision.url,
        "post_id": decision.post_id,
        "field": "rank_math_title",
        "before": decision.before,
        "after": decision.after,
        "public_verification": True,
    }
    with pytest.raises(RuntimeError, match="HTML público pendente"):
        handler_title_execution({"work_item_id": decision.decision_id,
                                 "payload": payload},
                                SimpleNamespace(db_path=str(db)))

    with Storage(str(db)) as store:
        pending = store.title_decision(decision.decision_id)
        assert pending["status"] == "decided"
        assert pending["publication_status"] == "public_pending"
        assert store.conn.execute(
            "SELECT COUNT(*) FROM actions WHERE work_item_id = ?",
            (decision.decision_id,),
        ).fetchone()[0] == 1

    fake_static.title = "Título novo | Marca"
    result = handler_title_execution({"work_item_id": decision.decision_id,
                                       "payload": payload},
                                      SimpleNamespace(db_path=str(db)))

    assert result["status"] == "executed"
    assert fake_wp.writes == [(7, {"rank_math_title": "Título novo"})]
    assert fake_static.fetches == 2
    with Storage(str(db)) as store:
        saved = store.title_decision(decision.decision_id)
        assert saved["status"] == "executed"
        assert saved["publication_status"] == "public_verified"
