"""Workflow guards: decisions must follow the human editorial sequence."""

from hermes_seo_agent.storage.db import Storage


def _pauta():
    return {"pauta_type": "supporting_post", "title": "Post de apoio: Gojo idade",
            "intent": "informational", "evidence": "500 impressões", "related_urls": [],
            "scope": "resposta própria", "duplication_risk": "baixo", "score": 2.0}


def test_backlog_transitions_and_rejected_deduplication(tmp_path):
    with Storage(tmp_path / "editorial.db") as storage:
        assert storage.save_pauta(_pauta())
        item_id = storage.list_backlog()[0]["id"]
        assert not storage.transition_backlog(item_id, "published", published_url="https://x.com/nova/")
        assert storage.transition_backlog(item_id, "approved")
        assert storage.transition_backlog(item_id, "published", published_url="https://x.com/nova/")
        assert not storage.transition_backlog(item_id, "rejected")
        assert storage.transition_backlog(item_id, "measured")
        assert not storage.save_pauta(_pauta())


def test_publish_requires_confirmed_url(tmp_path):
    with Storage(tmp_path / "editorial.db") as storage:
        storage.save_pauta(_pauta())
        item_id = storage.list_backlog()[0]["id"]
        assert storage.transition_backlog(item_id, "approved")
        assert not storage.transition_backlog(item_id, "published")
