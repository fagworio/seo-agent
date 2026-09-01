"""Tests for the Phase 4 executor — safety invariants are tested as code."""

import pytest

from hermes_seo_agent.config import Config
from hermes_seo_agent.executor.executor import Executor, _fingerprint
from hermes_seo_agent.storage.db import Storage


class _FakeWP:
    """Records writes; returns fixed before/after shapes."""

    def __init__(self):
        self.writes = []

    def get_media(self, media_id):
        return {"id": media_id, "alt_text": ""}

    def update_media_alt(self, media_id, alt_text):
        self.writes.append(("media_alt", media_id, alt_text))
        return {"id": media_id, "alt_text": alt_text}

    def get_post(self, post_id):
        return {"id": post_id, "meta": {"rank_math_title": "Old"}}

    def update_post_meta(self, post_id, meta):
        self.writes.append(("post_meta", post_id, meta))
        return {"id": post_id, "meta": meta}


def _config(dry_run: bool) -> Config:
    return Config(
        wordpress_url="http://localhost",
        app_user="u", app_password="p",
        dry_run=dry_run,
        sqlite_path="/tmp/seo-executor.db",
    )


def _actions() -> list[dict]:
    return [
        {
            "rule_id": "image_no_alt",
            "url": "https://x.com/img/1",
            "detail": "no alt",
            "fix": {"type": "wp_media_alt", "media_id": 1, "alt_text": "Jogo X"},
        },
        {
            "rule_id": "title_too_long",
            "url": "https://x.com/post/1",
            "detail": "title 90 chars",
            "fix": {"type": "wp_post_meta", "post_id": 1,
                    "meta": {"rank_math_title": "Título novo"}},
        },
    ]


def test_dry_run_previews_without_writes(tmp_path):
    db = tmp_path / "exec.db"
    wp = _FakeWP()
    with Storage(str(db)) as storage:
        outcome = Executor(_config(dry_run=True), wp, storage).apply_safe_actions(
            _actions(), cycle_id="c1"
        )
    assert len(outcome["previewed"]) == 2
    assert outcome["executed"] == []
    assert wp.writes == []  # nothing touched
    assert outcome["dry_run"] is True


def test_execute_writes_and_records_audit(tmp_path):
    db = tmp_path / "exec.db"
    wp = _FakeWP()
    with Storage(str(db)) as storage:
        outcome = Executor(_config(dry_run=False), wp, storage).apply_safe_actions(
            _actions(), cycle_id="c1"
        )
        assert len(outcome["executed"]) == 2
        assert len(wp.writes) == 2
        # audit trail: actions row carries before/after/rollback + fingerprint
        row = storage.conn.execute(
            "SELECT rule_id, before_json, after_json, rollback_json FROM actions"
        ).fetchone()
        assert row[0] == "image_no_alt"
        # audit_log entry exists with the action type
        log = storage.conn.execute(
            "SELECT action_type FROM audit_log WHERE entity = ?", ("https://x.com/img/1",)
        ).fetchone()
        assert "wp_media_alt" in log[0]


def test_idempotent_second_run_skips(tmp_path):
    db = tmp_path / "exec.db"
    wp = _FakeWP()
    with Storage(str(db)) as storage:
        executor = Executor(_config(dry_run=False), wp, storage)
        first = executor.apply_safe_actions(_actions(), cycle_id="c1")
        second = executor.apply_safe_actions(_actions(), cycle_id="c2")
        assert len(first["executed"]) == 2
        assert second["executed"] == []
        assert len(second["skipped"]) == 2
        assert all("idempotent" in s["reason"] for s in second["skipped"])
        assert len(wp.writes) == 2  # no duplicate writes


def test_blast_radius_caps_actions(tmp_path):
    db = tmp_path / "exec.db"
    wp = _FakeWP()
    actions = [
        {"rule_id": "image_no_alt", "url": f"https://x.com/{i}", "detail": "d",
         "fix": {"type": "wp_media_alt", "media_id": i, "alt_text": "alt"}}
        for i in range(1, 30)
    ]
    with Storage(str(db)) as storage:
        outcome = Executor(_config(dry_run=False), wp, storage).apply_safe_actions(
            actions, cycle_id="c1", max_actions=5
        )
        assert len(outcome["executed"]) == 5


def test_unsupported_fix_skipped(tmp_path):
    db = tmp_path / "exec.db"
    wp = _FakeWP()
    actions = [{"rule_id": "x", "url": "https://x.com/", "detail": "d",
                "fix": {"type": "wp_delete_post", "post_id": 1}}]
    with Storage(str(db)) as storage:
        outcome = Executor(_config(dry_run=False), wp, storage).apply_safe_actions(
            actions, cycle_id="c1"
        )
        assert outcome["executed"] == []
        assert len(outcome["skipped"]) == 1
        assert "no supported fix spec" in outcome["skipped"][0]["reason"]


def test_fingerprint_stable():
    assert _fingerprint("image_no_alt", "https://x.com/a", "no alt") == \
        _fingerprint("image_no_alt", "https://x.com/a", "no alt")
    assert _fingerprint("image_no_alt", "https://x.com/a", "no alt") != \
        _fingerprint("image_no_alt", "https://x.com/a", "different")


def test_fingerprint_includes_fix_value_not_just_length():
    """Títulos DIFERENTES com o MESMO comprimento não podem colidir: o fix
    (post_id + meta_key + novo_valor) entra no fingerprint, não só o detail."""
    detail = "ajustar título manual (6 chars)"
    fix_a = {"type": "wp_post_meta", "post_id": 7,
             "meta": {"rank_math_title": "AAAAAA"}}
    fix_b = {"type": "wp_post_meta", "post_id": 7,
             "meta": {"rank_math_title": "BBBBBB"}}
    assert _fingerprint("title_manual", "https://x.com/a", detail, fix_a) != \
        _fingerprint("title_manual", "https://x.com/a", detail, fix_b)
    # Mesmo fix (mesmo post, mesma meta, mesmo valor) -> estável (idempotente).
    assert _fingerprint("title_manual", "https://x.com/a", detail, fix_a) == \
        _fingerprint("title_manual", "https://x.com/a", detail, fix_a)
    # fix ausente mantém compatibilidade com a forma antiga (detail only).
    assert _fingerprint("r", "u", "d") == _fingerprint("r", "u", "d")


def test_same_detail_different_fix_both_execute(tmp_path):
    """Duas ações com o MESMO detail (títulos de mesmo comprimento) mas VALORES
    diferentes não são consideradas 'already executed' uma pela outra."""
    db = tmp_path / "exec2.db"
    wp = _FakeWP()
    actions = [
        {"rule_id": "title_manual", "url": "https://x.com/a", "detail": "6 chars",
         "fix": {"type": "wp_post_meta", "post_id": 1,
                 "meta": {"rank_math_title": "AAAAAA"}}},
        {"rule_id": "title_manual", "url": "https://x.com/a", "detail": "6 chars",
         "fix": {"type": "wp_post_meta", "post_id": 1,
                 "meta": {"rank_math_title": "BBBBBB"}}},
    ]
    with Storage(str(db)) as storage:
        outcome = Executor(_config(dry_run=False), wp, storage).apply_safe_actions(
            actions, cycle_id="c1"
        )
    assert len(outcome["executed"]) == 2
    assert len(wp.writes) == 2
    assert wp.writes[0][2]["rank_math_title"] == "AAAAAA"
    assert wp.writes[1][2]["rank_math_title"] == "BBBBBB"


def test_verify_ok_counts_as_executed(tmp_path):
    db = tmp_path / "vok.db"
    wp = _FakeWP()

    def _verify(fix, after):
        return True

    with Storage(str(db)) as storage:
        outcome = Executor(_config(dry_run=False), wp, storage).apply_safe_actions(
            _actions(), cycle_id="c1", verify=_verify
        )
    assert len(outcome["executed"]) == 2
    assert outcome["unverified"] == []
    assert len(wp.writes) == 2


def test_verify_failure_is_unverified_and_retry_allowed(tmp_path):
    """Confirmação REST divergente => status unverified (NÃO executed), e um
    retry com o mesmo título NÃO é bloqueado por idempotência."""
    db = tmp_path / "vbad.db"
    wp = _FakeWP()
    actions = [{
        "rule_id": "title_manual", "url": "https://x.com/a", "detail": "d",
        "fix": {"type": "wp_post_meta", "post_id": 1,
                "meta": {"rank_math_title": "NOVO"}},
    }]

    def _verify(fix, after):
        return False  # REST re-read diverges (mu-plugin ausente)

    with Storage(str(db)) as storage:
        executor = Executor(_config(dry_run=False), wp, storage)
        first = executor.apply_safe_actions(actions, cycle_id="c1", verify=_verify)
        second = executor.apply_safe_actions(actions, cycle_id="c2", verify=_verify)
    assert first["executed"] == []
    assert len(first["unverified"]) == 1
    assert "unverified" in first["unverified"][0]["reason"]
    # retry NÃO bloqueado: segunda tentativa também executa (não "already executed")
    assert len(second["unverified"]) == 1
    # no DB: registro existe mas com status unverified (action_executed = False)
    with Storage(str(db)) as storage:
        status = storage.conn.execute(
            "SELECT status FROM actions WHERE fingerprint = ?",
            (first["unverified"][0]["fingerprint"],),
        ).fetchone()
        assert status[0] == "unverified"
        assert storage.action_executed(first["unverified"][0]["fingerprint"]) is False
