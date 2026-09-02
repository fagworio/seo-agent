"""AgentRunService: ciclo de vida, estados, steps/events, comparação."""
import datetime

import pytest

from hermes_seo_agent.services.agent_runs import AgentRunError, AgentRunService
from hermes_seo_agent.storage.db import Storage


class FakeClock:
    def __init__(self, ts: int = 1_700_000_000):
        self.ts = ts

    def __call__(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(self.ts, tz=datetime.timezone.utc)

    def advance(self, seconds: int) -> None:
        self.ts += seconds


def _make(db):
    clock = FakeClock()
    storage = Storage(str(db))
    return storage, AgentRunService(storage, clock=clock), clock


def test_start_run_registers_agent_and_creates_running(tmp_path):
    storage, svc, _ = _make(tmp_path / "a.db")
    rid = svc.start_run("hermes-seo-agent", trigger="manual", intent="technical",
                        mode="analyze", started_by="admin@x.com")
    run = svc.get_run(rid)
    assert run["status"] == "running"
    assert run["agent"] == "hermes-seo-agent"
    assert run["trigger"] == "manual"
    assert run["intent"] == "technical"
    assert run["started_by"] == "admin@x.com"
    assert any(e["event"] == "RUN_STARTED" for e in run["events"])
    # registrar de novo é idempotente (mesmo agente)
    assert svc.register_agent("hermes-seo-agent") == run["agent_id"]
    storage.close()


def test_mark_step_records_step_and_event(tmp_path):
    storage, svc, _ = _make(tmp_path / "b.db")
    rid = svc.start_run("gsc-collector", trigger="system", intent="opportunities")
    svc.mark_step(rid, "fetch", "running")
    svc.mark_step(rid, "fetch", "success", detail={"items": 120})
    run = svc.get_run(rid)
    assert [s["stage"] for s in run["steps"]] == ["fetch"]
    assert run["steps"][0]["status"] == "success"
    assert any(e["event"] == "STEP:fetch" for e in run["events"])
    storage.close()


def test_complete_sets_counts_and_duration(tmp_path):
    storage, svc, clock = _make(tmp_path / "c.db")
    clock.ts = 1_700_000_000
    rid = svc.start_run("hermes-seo-agent", trigger="schedule", intent="technical")
    clock.advance(1)   # 1 segundo
    run = svc.complete(rid, status="success", urls=100, findings=7,
                       opportunities=3, safe_fixes=2, executed=1,
                       summary={"ok": True})
    assert run["status"] == "success"
    assert run["urls_analyzed"] == 100
    assert run["findings_count"] == 7
    assert run["duration_ms"] == 1000
    assert run["comparison"] is None      # primeira execução: sem comparável
    storage.close()


def test_comparison_between_comparable_runs(tmp_path):
    storage, svc, clock = _make(tmp_path / "d.db")
    r1 = svc.start_run("hermes-seo-agent", trigger="schedule", intent="technical")
    svc.complete(r1, status="success", urls=80, findings=5, opportunities=2,
                 safe_fixes=1, executed=1)
    clock.advance(1000)
    r2 = svc.start_run("hermes-seo-agent", trigger="schedule", intent="technical")
    svc.complete(r2, status="success", urls=100, findings=8, opportunities=4,
                 safe_fixes=3, executed=2)
    run2 = svc.get_run(r2)
    cmp = run2["comparison"]
    assert cmp["prior_run_id"] == r1
    assert cmp["urls_analyzed_delta"] == 20
    assert cmp["findings_delta"] == 3
    assert cmp["opportunities_delta"] == 2
    storage.close()


def test_fail_and_cancel(tmp_path):
    storage, svc, _ = _make(tmp_path / "e.db")
    rid = svc.start_run("hermes-seo-agent", trigger="manual", intent="technical")
    run = svc.fail(rid, "timeout no fetch")
    assert run["status"] == "failed"
    assert run["error"] == "timeout no fetch"

    rid2 = svc.start_run("hermes-seo-agent", trigger="manual", intent="technical")
    run2 = svc.cancel(rid2)
    assert run2["status"] == "cancelled"
    storage.close()


def test_run_list_and_running(tmp_path):
    storage, svc, _ = _make(tmp_path / "f.db")
    svc.start_run("a", trigger="manual", intent="technical")
    svc.start_run("b", trigger="system", intent="content")
    runs = svc.list_runs()
    assert len(runs) == 2
    statuses = {r["agent"] for r in svc.list_runs(status="running")}
    assert statuses == {"a", "b"}
    storage.close()


def test_queued_manual_run_is_claimed_by_compatible_worker(tmp_path):
    storage, svc, _ = _make(tmp_path / "queued.db")
    run_id = svc.queue_run("hermes-seo-agent", intent="technical", mode="analyze",
                           started_by="operator@x.com")
    assert svc.get_run(run_id)["status"] == "queued"
    assert svc.claim_queued_run("hermes-seo-agent", intent="technical") == run_id
    run = svc.get_run(run_id)
    assert run["status"] == "running"
    assert any(event["event"] == "RUN_STARTED" for event in run["events"])
    storage.close()


def test_invalid_inputs_rejected(tmp_path):
    storage, svc, _ = _make(tmp_path / "g.db")
    with pytest.raises(AgentRunError):
        svc.start_run("x", trigger="bad")
    with pytest.raises(AgentRunError):
        svc.start_run("x", trigger="manual", mode="bad")
    rid = svc.start_run("x", trigger="manual")
    with pytest.raises(AgentRunError):
        svc.complete(rid, status="unknown")
    storage.close()


def test_record_agent_run_from_cli(tmp_path):
    """O CLI registra a execução real com as contagens (agentes/Hoje)."""
    from types import SimpleNamespace

    from hermes_seo_agent.cli import _record_agent_run

    db = tmp_path / "run.db"
    config = SimpleNamespace(sqlite_path=str(db), app_user="cli-user")
    result = {
        "summary": {"audited_urls": 3},
        "findings": [{"rule_id": "a"}, {"rule_id": "b"}],
        "safe_actions": [{"rule_id": "c"}],
        "approval_required": [],
    }
    _record_agent_run(config, result, cycle_id="cycle-1", started="2026-01-01T00:00:00+00:00")
    with Storage(str(db)) as storage:
        runs = AgentRunService(storage).list_runs()
        assert len(runs) == 1
        run = runs[0]
        assert run["agent"] == "hermes-seo-agent"
        assert run["status"] == "success"
        assert run["urls_analyzed"] == 3
        assert run["findings_count"] == 2
        assert run["safe_fixes_count"] == 1
        assert run["intent"] == "technical"
