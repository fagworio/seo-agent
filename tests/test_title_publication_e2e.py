"""Fluxos E2E determinísticos da publicação supervisionada de títulos.

Estes testes atravessam a fila e o ``LaneWorker`` reais. As integrações externas
são fakes controlados para que o teste prove o contrato de produção sem exigir
credenciais, WordPress ou um site público:

    aprovação humana -> fila -> WP REST -> rebuild -> HTML público -> READY

O primeiro caso também simula a propagação atrasada do HTML. O retry precisa
reutilizar a escrita já confirmada e o rebuild solicitado, sem efeitos duplicados.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from hermes_seo_agent.config import Config
from hermes_seo_agent.lanes.handlers import handler_title_execution
from hermes_seo_agent.lanes.queue import LaneQueue
from hermes_seo_agent.lanes.title_decision import (
    enqueue_execution,
    enqueue_human_approved_execution,
    make_decision,
    persist_decision,
)
from hermes_seo_agent.lanes.worker import LaneWorker
from hermes_seo_agent.storage.db import Storage


class _FakeWP:
    def __init__(self, title: str = "Título antigo") -> None:
        self.title = title
        self.writes: list[tuple[int, dict[str, str]]] = []

    def get_post(self, post_id: int) -> dict:
        return {"id": post_id, "meta": {"rank_math_title": self.title}}

    def update_post_meta(self, post_id: int, meta: dict[str, str]) -> dict:
        self.writes.append((post_id, dict(meta)))
        self.title = meta["rank_math_title"]
        return self.get_post(post_id)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


class _FakeStatic:
    def __init__(self, title: str = "Título antigo", status_code: int = 200) -> None:
        self.title = title
        self.status_code = status_code
        self.fetches = 0

    def fetch_page(self, url: str):
        self.fetches += 1
        return SimpleNamespace(status_code=self.status_code, title=self.title)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


class _FakeWse:
    calls: list[str] = []

    def __init__(self, config: Config) -> None:
        self.config = config

    def rebuild(self, kind: str) -> dict[str, object]:
        self.calls.append(kind)
        return {"executed": True, "kind": kind}


class _CrashAfterWseRequest:
    calls = 0

    def __init__(self, config: Config) -> None:
        self.config = config

    def rebuild(self, kind: str) -> dict[str, object]:
        self.__class__.calls += 1
        raise KeyboardInterrupt("process interrupted after WSE request")


def _worker(db: str, config: Config, worker_id: str) -> dict:
    with Storage(db) as store:
        return LaneWorker(
            store,
            "title_execution",
            handler=handler_title_execution,
            worker_id=worker_id,
            max_items=1,
            retry_in=0,
            heartbeat=False,
            config=config,
        ).run().as_dict()


def test_approval_worker_retries_public_propagation_without_duplicate_effects(
    monkeypatch, tmp_path
):
    """O retry público fecha READY sem repetir WP REST ou WSE."""
    db = str(tmp_path / "title-publication-e2e.db")
    config = Config(
        wordpress_url="http://localhost",
        static_site_url="https://example.com",
        sqlite_path=db,
        dry_run=False,
        title_engine_mode="approval",
        title_rebuild_kind="smart",
        wse_workdir=str(tmp_path),
    )
    fake_wp = _FakeWP()
    fake_static = _FakeStatic()
    _FakeWse.calls = []

    import hermes_seo_agent.config as config_module
    import hermes_seo_agent.connectors.static_site as static_module
    import hermes_seo_agent.connectors.wordpress as wp_module
    import hermes_seo_agent.tools.wse_trigger as wse_module

    monkeypatch.setattr(config_module, "load_config", lambda: config)
    monkeypatch.setattr(wp_module, "WordPressClient", lambda cfg: fake_wp)
    monkeypatch.setattr(static_module, "StaticSiteClient", lambda cfg: fake_static)
    monkeypatch.setattr(wse_module, "WseTrigger", _FakeWse)

    decision = make_decision(
        url="https://example.com/post",
        post_id=7,
        before="Título antigo",
        after="Título novo",
        confidence=0.20,
        evidence={"page": {"impressions": 1200, "clicks": 15}},
        rollout={"mode": "approval", "writes_allowed": False},
    )
    with Storage(db) as store:
        persist_decision(store, decision)
        queued = enqueue_human_approved_execution(
            store,
            {**decision.as_dict(), "rebuild_kind": "smart"},
        )
    assert queued["enfileirado"] is True

    first = _worker(db, config, "title-e2e-first")
    assert first["failed"] == 1
    assert first["completed"] == 0
    assert fake_wp.writes == [(7, {"rank_math_title": "Título novo"})]
    assert _FakeWse.calls == ["smart"]

    with Storage(db) as store:
        item = LaneQueue(store).get_by_work_item(
            "title_execution", decision.decision_id
        )
        saved = store.title_decision(decision.decision_id)
    assert item["status"] == "retry"
    assert item["error_class"] == "public_pending"
    assert saved["publication_status"] == "public_pending"

    fake_static.title = "Título novo | Marca"
    second = _worker(db, config, "title-e2e-second")

    assert second["completed"] == 1
    assert second["failed"] == 0
    assert fake_static.fetches == 2
    assert fake_wp.writes == [(7, {"rank_math_title": "Título novo"})]
    assert _FakeWse.calls == ["smart"]
    with Storage(db) as store:
        item = LaneQueue(store).get_by_work_item(
            "title_execution", decision.decision_id
        )
        saved = store.title_decision(decision.decision_id)
    assert item["status"] == "done"
    assert saved["status"] == "executed"
    assert saved["publication_status"] == "public_verified"
    assert saved["outcome_id"] is not None


def test_worker_marks_external_title_change_stale_without_writing(monkeypatch, tmp_path):
    """Uma alteração humana entre decisão e worker nunca é sobrescrita."""
    db = str(tmp_path / "title-stale-e2e.db")
    config = Config(
        wordpress_url="http://localhost",
        sqlite_path=db,
        dry_run=False,
        title_engine_mode="auto",
    )
    fake_wp = _FakeWP("Título alterado por humano")

    import hermes_seo_agent.config as config_module
    import hermes_seo_agent.connectors.wordpress as wp_module

    monkeypatch.setattr(config_module, "load_config", lambda: config)
    monkeypatch.setattr(wp_module, "WordPressClient", lambda cfg: fake_wp)

    decision = make_decision(
        url="https://example.com/post",
        post_id=7,
        before="Título antigo",
        after="Título novo",
        confidence=0.90,
        rollout={"writes_allowed": True},
    )
    with Storage(db) as store:
        persist_decision(store, decision)
        assert enqueue_execution(store, decision)["enfileirado"] is True

    result = _worker(db, config, "title-stale-e2e")

    assert result["stale"] == 1
    assert result["completed"] == 0
    assert fake_wp.writes == []
    with Storage(db) as store:
        item = LaneQueue(store).get_by_work_item(
            "title_execution", decision.decision_id
        )
        saved = store.title_decision(decision.decision_id)
    assert item["status"] == "stale"
    assert saved["status"] == "stale"


def test_public_503_stays_in_unbounded_propagation_retry(monkeypatch, tmp_path):
    """503 é indisponibilidade transitória, não esgota max_attempts."""
    db = str(tmp_path / "title-publication-503.db")
    config = Config(wordpress_url="http://localhost", sqlite_path=db,
                    dry_run=False, title_engine_mode="auto")
    fake_wp = _FakeWP()
    fake_static = _FakeStatic(status_code=503)

    import hermes_seo_agent.config as config_module
    import hermes_seo_agent.connectors.static_site as static_module
    import hermes_seo_agent.connectors.wordpress as wp_module

    monkeypatch.setattr(config_module, "load_config", lambda: config)
    monkeypatch.setattr(wp_module, "WordPressClient", lambda cfg: fake_wp)
    monkeypatch.setattr(static_module, "StaticSiteClient", lambda cfg: fake_static)

    decision = make_decision(
        url="https://example.com/post", post_id=7,
        before="Título antigo", after="Título novo", confidence=0.9,
        rollout={"writes_allowed": True},
    )
    with Storage(db) as store:
        persist_decision(store, decision)
        assert enqueue_execution(store, decision)["enfileirado"] is True

    for index in range(4):
        result = _worker(db, config, f"title-503-{index}")
        assert result["failed"] == 1

    with Storage(db) as store:
        item = LaneQueue(store).get_by_work_item(
            "title_execution", decision.decision_id)
    assert item["status"] == "retry"
    assert item["error_class"] == "public_pending"
    assert item["attempt_count"] == 4
    assert fake_wp.writes == [(7, {"rank_math_title": "Título novo"})]


def test_public_404_has_bounded_propagation_retry_then_manual_review(
    monkeypatch, tmp_path
):
    """404 recebe tolerância curta, mas não pode virar retry infinito."""
    db = str(tmp_path / "title-publication-404.db")
    config = Config(wordpress_url="http://localhost", sqlite_path=db,
                    dry_run=False, title_engine_mode="auto")
    fake_wp = _FakeWP()
    fake_static = _FakeStatic(status_code=404)

    import hermes_seo_agent.config as config_module
    import hermes_seo_agent.connectors.static_site as static_module
    import hermes_seo_agent.connectors.wordpress as wp_module

    monkeypatch.setattr(config_module, "load_config", lambda: config)
    monkeypatch.setattr(wp_module, "WordPressClient", lambda cfg: fake_wp)
    monkeypatch.setattr(static_module, "StaticSiteClient", lambda cfg: fake_static)

    decision = make_decision(
        url="https://example.com/post", post_id=7,
        before="Título antigo", after="Título novo", confidence=0.9,
        rollout={"writes_allowed": True},
    )
    with Storage(db) as store:
        persist_decision(store, decision)
        assert enqueue_execution(store, decision)["enfileirado"] is True

    for index in range(3):
        result = _worker(db, config, f"title-404-{index}")
        assert result["failed"] == 1

    with Storage(db) as store:
        item = LaneQueue(store).get_by_work_item(
            "title_execution", decision.decision_id)
    assert item["status"] == "manual_review"
    assert item["error_class"] == "public_not_found"
    assert item["attempt_count"] == 3
    assert fake_wp.writes == [(7, {"rank_math_title": "Título novo"})]


def test_rebuild_intent_precedes_external_call_and_prevents_duplicate(
    monkeypatch, tmp_path
):
    """Morte após a chamada WSE não autoriza um segundo rebuild no retry."""
    db = str(tmp_path / "title-rebuild-intent.db")
    config = Config(wordpress_url="http://localhost", sqlite_path=db,
                    static_site_url="https://example.com", dry_run=False,
                    title_engine_mode="auto", title_rebuild_kind="smart",
                    wse_workdir=str(tmp_path))
    fake_wp = _FakeWP()
    fake_static = _FakeStatic()
    _CrashAfterWseRequest.calls = 0

    import hermes_seo_agent.config as config_module
    import hermes_seo_agent.connectors.static_site as static_module
    import hermes_seo_agent.connectors.wordpress as wp_module
    import hermes_seo_agent.tools.wse_trigger as wse_module

    monkeypatch.setattr(config_module, "load_config", lambda: config)
    monkeypatch.setattr(wp_module, "WordPressClient", lambda cfg: fake_wp)
    monkeypatch.setattr(static_module, "StaticSiteClient", lambda cfg: fake_static)
    monkeypatch.setattr(wse_module, "WseTrigger", _CrashAfterWseRequest)

    decision = make_decision(
        url="https://example.com/post", post_id=7,
        before="Título antigo", after="Título novo", confidence=0.9,
        rollout={"writes_allowed": True},
    )
    payload = {**decision.as_dict(), "rebuild_kind": "smart"}
    with Storage(db) as store:
        persist_decision(store, decision)

    with pytest.raises(KeyboardInterrupt):
        handler_title_execution(
            {"work_item_id": decision.decision_id, "payload": payload},
            SimpleNamespace(db_path=db),
        )

    with Storage(db) as store:
        assert store.title_decision(decision.decision_id)["publication_status"] == (
            "rebuild_requested")

    fake_static.title = "Título novo | Marca"
    result = handler_title_execution(
        {"work_item_id": decision.decision_id, "payload": payload},
        SimpleNamespace(db_path=db),
    )

    assert result["status"] == "executed"
    assert _CrashAfterWseRequest.calls == 1
    assert fake_wp.writes == [(7, {"rank_math_title": "Título novo"})]
    with Storage(db) as store:
        assert store.title_decision(decision.decision_id)["publication_status"] == (
            "public_verified")
