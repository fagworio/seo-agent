"""Tests for the watchdog schedule — weekly GA4 + corpus maintenance."""

import argparse
import dataclasses
import datetime
import json
import threading
import time

from hermes_seo_agent.cli import _cmd_schedule, _cmd_title_engine, _emit
from hermes_seo_agent.config import Config
from hermes_seo_agent.services.agent_runs import AgentRunService
from hermes_seo_agent.storage.db import Storage


def _config(db_path) -> Config:
    return Config(
        wordpress_url="http://localhost",
        static_site_url="https://www.unicorniohater.com.br",
        ga4_property_id="123",
        sqlite_path=str(db_path),
    )


def _now_patch(monkeypatch, *, weekday=1, hour=6):
    class _FakeNow(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 8, hour, 0, 0)  # 2026-09-08 = terça (weekday 1)

    monkeypatch.setattr(datetime, "datetime", _FakeNow)
    return _FakeNow


def test_schedule_includes_ga4_and_corpus_on_deep_weekday(
        monkeypatch, capsys, tmp_path):
    """Na janela semanal, o schedule roda ga4-collect + corpus-rebuild."""
    db = tmp_path / "sched.db"
    _now_patch(monkeypatch, weekday=0, hour=6)  # segunda 06:00

    captured = {}

    def _fake_audit(args, config):
        captured["audit"] = True

    def _fake_ga4(args, config):
        captured["ga4"] = args.store

    def _fake_corpus(args, config):
        captured["corpus"] = args.action

    monkeypatch.setattr("hermes_seo_agent.cli._cmd_audit", _fake_audit)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_ga4", _fake_ga4)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_corpus", _fake_corpus)
    # impede chamadas de rede dos outros steps
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_opportunities",
                        lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_inspect",
                        lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_post_audit",
                        lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_refresh_data",
                        lambda *a, **k: None)

    rc = _cmd_schedule(
        argparse.Namespace(inspect_hours="6", deep_weekday=1), _config(db))
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert "ga4-collect" in out["summary"]["steps"]
    assert "corpus-rebuild" in out["summary"]["steps"]
    assert captured["ga4"] is True
    assert captured["corpus"] == "rebuild"


def test_schedule_consumes_specific_url_manual_run(monkeypatch, capsys, tmp_path):
    db = tmp_path / "manual-specific.db"
    _now_patch(monkeypatch, hour=12)
    config = _config(db)
    with Storage(str(db)) as storage:
        run_id = AgentRunService(storage).queue_run(
            "hermes-seo-agent", intent="specific_url", mode="analyze",
            target_url="https://x.com/manual/")

    seen = []
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_audit",
                        lambda args, config: seen.append(getattr(args, "single_url", "")))
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_refresh_data", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_inspect", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_post_audit", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_opportunities", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_corpus", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_ga4", lambda *a, **k: None)

    assert _cmd_schedule(argparse.Namespace(inspect_hours="6", deep_weekday=0), config) == 0
    capsys.readouterr()
    with Storage(str(db)) as storage:
        run = AgentRunService(storage).get_run(run_id)
    assert run["status"] == "success"
    assert "https://x.com/manual/" in seen


def test_schedule_resumes_corpus_when_run_active(monkeypatch, capsys, tmp_path):
    """Guarda M2: um rebuild running é RETOMADO (drenado), nunca deixado preso.

    Removida a trava de "run ativo": um run parcial ficava 'running' para sempre
    e o build semanal nunca retomava (bug do corpus eternamente incompleto). O
    rebuild é concorrente-seguro (claim atômico + lease fencing), então o
    schedule sempre o aciona para retomar/drenar.
    """
    db = tmp_path / "sched2.db"
    _now_patch(monkeypatch, weekday=0, hour=6)
    with Storage(str(db)) as storage:
        storage.start_corpus_run(total_urls=100)  # deixa 'running'

    corpus_calls = []

    def _fake_audit(args, config):
        pass

    def _fake_ga4(args, config):
        pass

    def _fake_corpus(args, config):
        corpus_calls.append(args.action)

    monkeypatch.setattr("hermes_seo_agent.cli._cmd_audit", _fake_audit)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_ga4", _fake_ga4)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_corpus", _fake_corpus)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_opportunities",
                        lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_inspect",
                        lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_post_audit",
                        lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_refresh_data",
                        lambda *a, **k: None)

    rc = _cmd_schedule(
        argparse.Namespace(inspect_hours="6", deep_weekday=1), _config(db))
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert "corpus-rebuild" in out["summary"]["steps"]
    assert corpus_calls == ["rebuild"]  # retomou o build (drenou a fila)


def test_daily_schedule_collects_gsc_revalidates_and_records_run(monkeypatch, capsys, tmp_path):
    db = tmp_path / "daily-google.db"
    _now_patch(monkeypatch, hour=6)
    config = dataclasses.replace(_config(db), google_credentials="configured")
    calls = []
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_audit", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_inspect", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_post_audit", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_refresh_data", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_demand",
                        lambda args, config: calls.append(("demand", args.store, args.min_impressions)))
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_outcomes",
                        lambda args, config: calls.append(("outcomes", args.action)))
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_opportunities", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_ga4", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_corpus", lambda *a, **k: None)
    worker_calls = []
    monkeypatch.setattr(
        "hermes_seo_agent.cli._cmd_lanes_run",
        lambda *a, **k: worker_calls.append(True) or 0,
    )
    # F21/F22: o shadow do motor de título entra no ciclo diário (observe+persist)
    title_engine_calls = []
    config = dataclasses.replace(config, title_analysis_limit=42,
                                 title_max_writes_per_cycle=7)
    monkeypatch.setattr(
        "hermes_seo_agent.cli._cmd_title_engine",
        lambda args, config: title_engine_calls.append(
            (args.mode, args.shadow, args.persist, args.write,
             args.analysis_limit, args.limit)))

    assert _cmd_schedule(argparse.Namespace(inspect_hours="6", deep_weekday=0), config) == 0
    result = json.loads(capsys.readouterr().out)
    assert ("demand", True, 0) in calls
    assert ("outcomes", "revalidate-due") in calls
    assert "gsc-demand" in result["summary"]["steps"]
    # shadow automático: observa, compara e persiste — NUNCA publica título
    assert title_engine_calls == [("observe", True, True, False, 42, 0)]
    assert "title-engine-observe" in result["summary"]["steps"]
    assert worker_calls == []
    with Storage(str(db)) as storage:
        run = storage.conn.execute(
            "SELECT status, intent, summary_json FROM agent_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert run[0] == "success" and run[1] == "normal_cycle"


def test_schedule_does_not_advance_gsc_checkpoint_when_title_stage_fails(
        monkeypatch, capsys, tmp_path):
    """Falha do motor mantém o ciclo elegível para retry."""
    db = tmp_path / "failed-title.db"
    _now_patch(monkeypatch, hour=6)
    config = dataclasses.replace(_config(db), google_credentials="configured",
                                 title_engine_mode="auto")
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_audit", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_inspect", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_post_audit", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_refresh_data", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_demand", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_outcomes", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_ga4", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_corpus", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_opportunities", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_title_engine",
                        lambda *a, **k: 2)
    worker_calls = []
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_lanes_run",
                        lambda *a, **k: worker_calls.append(True) or 0)

    assert _cmd_schedule(argparse.Namespace(inspect_hours="6", deep_weekday=0),
                         config) == 1
    json.loads(capsys.readouterr().out)
    with Storage(str(db)) as storage:
        assert storage.get_setting("gsc:last_success", "") == ""
        assert storage.get_setting("gsc:last_error", "")
        # A title collection failure must not strand already queued decisions;
        # the independent execution lane still gets its bounded turn.
        assert worker_calls == [True]


def test_title_engine_lock_has_explicit_non_success_status(capsys, tmp_path):
    db = tmp_path / "locked-title-engine.db"
    config = _config(db)
    with Storage(str(db)) as storage:
        assert storage.acquire_named_lease("title_engine:run", "other-worker",
                                          ttl_seconds=3600) is True

    rc = _cmd_title_engine(argparse.Namespace(), config)
    result = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert result["status"] == "skipped_locked"
    assert result["summary"]["status"] == "skipped_locked"


def test_title_engine_heartbeat_renews_during_long_analysis(monkeypatch, tmp_path):
    db = tmp_path / "heartbeat-title-engine.db"
    config = _config(db)
    import hermes_seo_agent.cli as cli_module

    monkeypatch.setattr(cli_module, "_TITLE_ENGINE_LEASE_HEARTBEAT_SECONDS", 0.01)
    calls = []
    started = threading.Event()
    original_renew = Storage.renew_named_lease

    def _renew(self, key, owner, *, ttl_seconds=3600):
        calls.append(owner)
        return original_renew(self, key, owner, ttl_seconds=ttl_seconds)

    monkeypatch.setattr(Storage, "renew_named_lease", _renew)

    def _long_impl(args, config, *, lease_guard=None, lease_fence=None):
        started.set()
        deadline = time.monotonic() + 1
        while len(calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        return 0

    monkeypatch.setattr(cli_module, "_cmd_title_engine_impl", _long_impl)
    assert _cmd_title_engine(argparse.Namespace(), config) == 0
    assert started.is_set()
    assert len(calls) >= 2
    with Storage(str(db)) as storage:
        assert storage.acquire_named_lease("title_engine:run", "after-worker",
                                          ttl_seconds=60) is True


def test_schedule_defers_locked_title_without_gsc_failure_backoff(
        monkeypatch, capsys, tmp_path):
    db = tmp_path / "deferred-title-engine.db"
    _now_patch(monkeypatch, hour=6)
    config = dataclasses.replace(_config(db), google_credentials="configured",
                                 title_engine_mode="auto")
    for name in ("_cmd_audit", "_cmd_refresh_data", "_cmd_inspect",
                 "_cmd_post_audit", "_cmd_demand", "_cmd_outcomes",
                 "_cmd_ga4", "_cmd_corpus", "_cmd_opportunities"):
        monkeypatch.setattr(f"hermes_seo_agent.cli.{name}",
                            lambda *a, **k: None)

    def _locked_title(*args, **kwargs):
        _emit({
            "status": "skipped_locked",
            "summary": {"command": "title-engine", "status": "skipped_locked"},
            "findings": [], "safe_actions": [], "approval_required": [],
        }, force_json=True)
        return 0

    monkeypatch.setattr("hermes_seo_agent.cli._cmd_title_engine", _locked_title)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_lanes_run",
                        lambda *a, **k: 0)

    assert _cmd_schedule(argparse.Namespace(inspect_hours="6", deep_weekday=0),
                         config) == 0
    json.loads(capsys.readouterr().out)
    with Storage(str(db)) as storage:
        assert storage.get_setting("gsc:last_success", "") == ""
        assert storage.get_setting("gsc:next_retry", "")
        assert storage.get_setting("title-engine:next_retry", "")
        run = storage.conn.execute(
            "SELECT status FROM agent_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert run[0] == "success"


def test_schedule_drena_aprovacoes_fora_do_modo_auto(monkeypatch, capsys, tmp_path):
    """Uma decisão aprovada não pode ficar presa porque o rollout é approval."""
    db = tmp_path / "approval-worker.db"
    _now_patch(monkeypatch, hour=12)
    config = dataclasses.replace(_config(db), title_engine_mode="approval")
    for name in ("_cmd_audit", "_cmd_refresh_data", "_cmd_inspect",
                 "_cmd_post_audit", "_cmd_opportunities", "_cmd_ga4",
                 "_cmd_corpus"):
        monkeypatch.setattr(f"hermes_seo_agent.cli.{name}", lambda *a, **k: None)

    worker_calls = []
    monkeypatch.setattr(
        "hermes_seo_agent.cli._cmd_lanes_run",
        lambda args, config: worker_calls.append(args.lane) or 0,
    )

    assert _cmd_schedule(argparse.Namespace(inspect_hours="6", deep_weekday=0),
                         config) == 0
    json.loads(capsys.readouterr().out)
    assert worker_calls == ["title_execution"]


def test_schedule_treats_json_error_as_failed_stage(monkeypatch, capsys, tmp_path):
    db = tmp_path / "json-error.db"
    _now_patch(monkeypatch, hour=6)

    def failed_audit(*_args, **_kwargs):
        _emit({"status": "error", "error": "source unavailable",
               "summary": {}}, force_json=True)

    monkeypatch.setattr("hermes_seo_agent.cli._cmd_audit", failed_audit)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_refresh_data", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_inspect", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_post_audit", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_opportunities", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_ga4", lambda *a, **k: None)
    monkeypatch.setattr("hermes_seo_agent.cli._cmd_corpus", lambda *a, **k: None)

    assert _cmd_schedule(argparse.Namespace(inspect_hours="6", deep_weekday=0),
                         _config(db)) == 1
    result = json.loads(capsys.readouterr().out)
    assert any("status error" in error for error in result["summary"]["errors"])
