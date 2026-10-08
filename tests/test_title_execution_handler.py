from types import SimpleNamespace

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


def test_title_execution_writes_and_confirms(monkeypatch, tmp_path):
    db = tmp_path / "title-worker.db"
    config = Config(wordpress_url="http://localhost", sqlite_path=str(db),
                    dry_run=False)
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
        },
    }, SimpleNamespace(db_path=str(db)))

    assert result["status"] == "executed"
    assert fake_wp.writes == [(7, {"rank_math_title": "Título novo"})]
    with Storage(str(db)) as store:
        assert store.title_decision(decision.decision_id)["status"] == "executed"


def test_title_execution_marks_stale_without_writing(monkeypatch, tmp_path):
    db = tmp_path / "title-worker-stale.db"
    config = Config(wordpress_url="http://localhost", sqlite_path=str(db),
                    dry_run=False)
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
        },
    }, SimpleNamespace(db_path=str(db)))

    assert result["status"] == "stale"
    assert fake_wp.writes == []
    with Storage(str(db)) as store:
        assert store.title_decision(decision.decision_id)["status"] == "stale"
