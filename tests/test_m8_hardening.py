"""Tests for M8 hardening — baseline automático, janelas 28/56/90d e ligação
decisão→outcome com evidência/scores."""

import argparse
import json

import pytest

from hermes_seo_agent.cli import _cmd_outcomes
from hermes_seo_agent.config import Config
from hermes_seo_agent.storage.db import Storage


def test_register_with_baseline_and_scores(tmp_path):
    db = tmp_path / "o.db"
    with Storage(str(db)) as storage:
        oid = storage.save_opportunity_outcome(
            keyword="gojo idade", opportunity_type="expand_existing",
            decision="expand_existing",
            evidence={"demand_score": 0.8}, candidate_score=0.4, action_score=0.6,
            human_decision="approved", implemented_action="expand",
            url="https://x.com/a/", baseline={"gsc": {"clicks": 5}, "ga4": None},
            implemented_at="2026-01-01T00:00:00+00:00",
        )
        item = storage.list_opportunity_outcomes()[0]
        assert item["baseline"]["gsc"]["clicks"] == 5
        assert item["candidate_score"] == 0.4
        assert item["action_score"] == 0.6
        assert item["measured"] == {"7d": False, "28d": False, "56d": False, "90d": False}


def test_set_outcome_verdict_marks_window_and_blocks_remeasure(tmp_path):
    db = tmp_path / "o2.db"
    with Storage(str(db)) as storage:
        oid = storage.save_opportunity_outcome(
            keyword="k", opportunity_type="refresh", decision="refresh",
            human_decision="approved", url="https://x.com/a/",
            implemented_at="2026-01-01T00:00:00+00:00",
        )
        storage.set_outcome_verdict(oid, verdict="improved", days=28,
                                    result={"gsc_deltas": {"clicks_delta": 5}})
        item = storage.list_opportunity_outcomes()[0]
        assert item["measured"]["28d"] is True
        assert item["measured"]["56d"] is False
        assert item["verdict"] == "improved"
        assert item["results"]["28d"]["gsc_deltas"]["clicks_delta"] == 5
        # re-medir a mesma janela bloqueia
        with pytest.raises(ValueError):
            storage.set_outcome_verdict(oid, verdict="worsened", days=28)
        # dias inválidos bloqueiam
        with pytest.raises(ValueError):
            storage.set_outcome_verdict(oid, verdict="neutral", days=30)


def test_register_cli_wires_decision_scores(monkeypatch, capsys, tmp_path):
    """Ligação automática decisão→outcome: register grava evidência + scores."""
    db = tmp_path / "ocli.db"

    class _FakeGSC:
        def __init__(self, config):
            pass

        def page_metrics(self, url, **kw):
            return {"impressions": 100, "clicks": 1, "ctr": 0.01, "position": 5.0}

    monkeypatch.setattr("hermes_seo_agent.cli.SearchConsoleClient", _FakeGSC)
    config = Config(wordpress_url="http://localhost", google_credentials="fake",
                    sqlite_path=str(db))
    args = argparse.Namespace(action="register", keyword="gojo idade",
                              type="", decision="", human_decision="approved",
                              rejection_reason="", implemented_action="expand",
                              url="https://x.com/a/", trend="")
    rc = _cmd_outcomes(args, config)
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["summary"]["outcome_id"] >= 1
    # scores computados pela decisão M6 (weak_signal p/ demanda 0, mas presente)
    assert out["summary"]["candidate_score"] is not None
    assert out["summary"]["action_score"] is not None
    with Storage(str(db)) as storage:
        item = storage.list_opportunity_outcomes()[0]
        assert item["evidence"]["demand_score"] == 0.0
        assert item["baseline"]["gsc"]["clicks"] == 1  # baseline automático


def test_measure_enforces_window(tmp_path, monkeypatch, capsys):
    """measure antes da janela completa é bloqueado; com janela ok, mede."""
    db = tmp_path / "om.db"
    with Storage(str(db)) as storage:
        storage.save_opportunity_outcome(
            keyword="k", opportunity_type="expand_existing", decision="expand_existing",
            human_decision="approved", url="https://x.com/a/",
            baseline={"gsc": {"impressions": 100, "clicks": 5, "ctr": 0.05,
                              "position": 4.0}, "ga4": None},
            implemented_at="2026-08-01T00:00:00+00:00",  # passado distante
        )

    class _FakeGSC:
        def __init__(self, config):
            pass

        def page_metrics(self, url, **kw):
            return {"impressions": 300, "clicks": 15, "ctr": 0.05, "position": 3.0}

    monkeypatch.setattr("hermes_seo_agent.cli.SearchConsoleClient", _FakeGSC)
    config = Config(wordpress_url="http://localhost", google_credentials="fake",
                    sqlite_path=str(db))

    # janela 90d vs implemented_at recente demais? usamos 2026-08-01 e hoje
    # (2026-09-01) -> apenas 31d: 56d/90d bloqueiam, 28d passa.
    args28 = argparse.Namespace(action="measure", item_id=1, measure_days=28,
                                verdict="")
    rc = _cmd_outcomes(args28, config)
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["summary"]["verdict"] == "improved"  # cliques/impressões subiram
    assert out["summary"]["elapsed_days"] >= 28

    args90 = argparse.Namespace(action="measure", item_id=1, measure_days=90,
                                verdict="")
    rc = _cmd_outcomes(args90, config)
    out90 = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert "janela 90d" in out90["error"] or "não completou" in out90["error"]


def test_measure_blocks_after_already_measured(tmp_path, monkeypatch, capsys):
    db = tmp_path / "om2.db"
    with Storage(str(db)) as storage:
        storage.save_opportunity_outcome(
            keyword="k", opportunity_type="refresh", decision="refresh",
            human_decision="approved", url="https://x.com/a/",
            implemented_at="2026-01-01T00:00:00+00:00",
        )
        storage.set_outcome_verdict(1, verdict="improved", days=28)
    config = Config(wordpress_url="http://localhost", sqlite_path=str(db))
    args = argparse.Namespace(action="measure", item_id=1, measure_days=28,
                              verdict="")
    rc = _cmd_outcomes(args, config)
    out = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert "já medido" in out["error"]


def test_revalidate_due_measures_7d_only_with_google_and_baseline(tmp_path, monkeypatch, capsys):
    db = tmp_path / "due.db"
    with Storage(str(db)) as storage:
        storage.save_opportunity_outcome(
            keyword="gojo", opportunity_type="title_meta", decision="refresh",
            human_decision="approved", url="https://x.com/gojo/",
            baseline={"gsc": {"impressions": 100, "clicks": 5, "ctr": .05,
                              "position": 5.0}, "ga4": None},
            implemented_at="2020-01-01T00:00:00+00:00",
        )

    class _FakeGSC:
        def __init__(self, config):
            pass

        def page_metrics(self, url, **kwargs):
            return {"impressions": 140, "clicks": 9, "ctr": .064, "position": 4.2}

    monkeypatch.setattr("hermes_seo_agent.cli.SearchConsoleClient", _FakeGSC)
    config = Config(wordpress_url="http://localhost", google_credentials="fake",
                    sqlite_path=str(db))
    assert _cmd_outcomes(argparse.Namespace(action="revalidate-due", limit=20), config) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["summary"]["measured"] == 1
    with Storage(str(db)) as storage:
        outcome = storage.list_opportunity_outcomes()[0]
        assert outcome["measured"]["7d"] is True
        assert outcome["results"]["7d"]["observation"] == "preliminary_7d"
