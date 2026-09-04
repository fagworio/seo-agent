"""R3 — RefreshDataRun: orquestrador de coleta por fonte como estágios de AgentRun."""
from hermes_seo_agent.services.agent_runs import AgentRunService
from hermes_seo_agent.services.data_refresh import StageResult, run_refresh
from hermes_seo_agent.storage.db import Storage


def _make(db):
    storage = Storage(str(db))
    svc = AgentRunService(storage)
    return storage, svc


def test_run_refresh_success_and_steps(tmp_path):
    storage, svc = _make(tmp_path / "a.db")
    run_id = svc.start_run("hermes-seo-agent", intent="refresh_data", mode="analyze",
                           sources=["wordpress", "gsc"])
    collectors = {
        "wordpress": lambda: StageResult("wordpress", records_read=100, data_window="2026-09-03"),
        "gsc": lambda: StageResult("gsc", records_read=50, data_window="08/07→09/03"),
    }
    run = run_refresh(storage, run_id, sources=["wordpress", "gsc"], collectors=collectors)
    assert run["status"] == "success"
    steps = {s["stage"]: s for s in run["steps"]}
    assert steps["wordpress"]["status"] == "success"
    assert steps["gsc"]["status"] == "success"
    assert run["summary"]["results"]["wordpress"]["records_read"] == 100
    assert run["summary"]["results"]["gsc"]["data_window"] == "08/07→09/03"
    storage.close()


def test_run_refresh_partial_failure(tmp_path):
    storage, svc = _make(tmp_path / "b.db")
    run_id = svc.start_run("hermes-seo-agent", intent="refresh_data", mode="analyze",
                           sources=["wordpress", "gsc", "ga4"])
    collectors = {
        "wordpress": lambda: StageResult("wordpress", records_read=10),
        "gsc": lambda: StageResult("gsc", records_read=5),
        "ga4": lambda: StageResult("ga4", status="failed", error="GA4 indisponível"),
    }
    run = run_refresh(storage, run_id, sources=["wordpress", "gsc", "ga4"], collectors=collectors)
    assert run["status"] == "partial"
    steps = {s["stage"]: s for s in run["steps"]}
    assert steps["ga4"]["status"] == "failed"
    assert steps["wordpress"]["status"] == "success"
    assert steps["gsc"]["status"] == "success"
    storage.close()


def test_run_refresh_all_failed(tmp_path):
    storage, svc = _make(tmp_path / "c.db")
    run_id = svc.start_run("hermes-seo-agent", intent="refresh_data", mode="analyze",
                           sources=["gsc"])
    collectors = {"gsc": lambda: StageResult("gsc", status="failed", error="sem credencial")}
    run = run_refresh(storage, run_id, sources=["gsc"], collectors=collectors)
    assert run["status"] == "failed"
    storage.close()


def test_run_refresh_skipped_source_not_failure(tmp_path):
    """Uma fonte não configurada (skipped) não degrada o run para partial."""
    storage, svc = _make(tmp_path / "d.db")
    run_id = svc.start_run("hermes-seo-agent", intent="refresh_data", mode="analyze",
                           sources=["wordpress", "gsc"])
    collectors = {
        "wordpress": lambda: StageResult("wordpress", records_read=10),
        "gsc": lambda: StageResult("gsc", status="skipped", error="GOOGLE_APPLICATION_CREDENTIALS vazio"),
    }
    run = run_refresh(storage, run_id, sources=["wordpress", "gsc"], collectors=collectors)
    assert run["status"] == "success"
    steps = {s["stage"]: s for s in run["steps"]}
    assert steps["gsc"]["status"] == "skipped"
    storage.close()


def test_run_refresh_with_reconcile_stage(tmp_path):
    storage, svc = _make(tmp_path / "e.db")
    run_id = svc.start_run("hermes-seo-agent", intent="refresh_data", mode="analyze",
                           sources=["wordpress"])
    collectors = {"wordpress": lambda: StageResult("wordpress", records_read=10)}
    reconcile = lambda: StageResult("reconcile", records_read=10,
                                    extra={"missing_from_sitemap": 2, "orphan_in_sitemap": 1})
    run = run_refresh(storage, run_id, sources=["wordpress"],
                      collectors=collectors, reconcile=reconcile)
    assert run["status"] == "success"
    steps = {s["stage"]: s for s in run["steps"]}
    assert "reconcile" in steps
    assert steps["reconcile"]["detail"]["missing_from_sitemap"] == 2
    assert steps["reconcile"]["detail"]["orphan_in_sitemap"] == 1
    storage.close()
