"""B0 — ImprovementCampaignService: criação, homogeneidade, fix forward, ciclo de vida."""
import json

from hermes_seo_agent.services.improvement_campaigns import (
    ImprovementCampaignService,
    forward_fix,
)
from hermes_seo_agent.storage.db import Storage


def _seed_actions(storage: Storage) -> None:
    storage.conn.execute(
        "INSERT INTO actions (cycle_id, rule_id, url, level, status, fingerprint, before_json, "
        "after_json, rollback_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("c1", "title_manual", "https://x.com/a/", "safe_fix", "pending", "fp-title-1",
         json.dumps({"rank_math_title": "velho"}),
         json.dumps({"rank_math_title": "novo"}),
         json.dumps({"type": "wp_post_meta", "post_id": 7, "meta": {"rank_math_title": "velho"}})))
    storage.conn.execute(
        "INSERT INTO actions (cycle_id, rule_id, url, level, status, fingerprint, before_json, "
        "after_json, rollback_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("c1", "title_manual", "https://x.com/b/", "safe_fix", "pending", "fp-title-2",
         json.dumps({"rank_math_title": "B velho"}),
         json.dumps({"rank_math_title": "B novo"}),
         json.dumps({"type": "wp_post_meta", "post_id": 8, "meta": {"rank_math_title": "B velho"}})))
    storage.conn.commit()


def test_forward_fix_reconstructs_wp_post_meta():
    assert forward_fix({"rank_math_title": "novo"},
                       {"type": "wp_post_meta", "post_id": 7,
                        "meta": {"rank_math_title": "velho"}}) == \
        {"type": "wp_post_meta", "post_id": 7, "meta": {"rank_math_title": "novo"}}


def test_create_campaign_and_items(tmp_path):
    storage = Storage(str(tmp_path / "c.db"))
    _seed_actions(storage)
    svc = ImprovementCampaignService(storage)
    camp = svc.create("Títulos", "title_manual", ["fp-title-1", "fp-title-2"],
                      created_by="admin@x.com", max_actions_per_run=10)
    assert camp is not None and camp["status"] == "draft"
    assert camp["total_items"] == 2 and camp["pending_items"] == 2
    assert len(camp["items"]) == 2
    assert camp["items"][0]["fix"] == {"type": "wp_post_meta", "post_id": 7,
                                       "meta": {"rank_math_title": "novo"}}
    storage.close()


def test_create_rejects_non_homogeneous(tmp_path):
    storage = Storage(str(tmp_path / "c2.db"))
    _seed_actions(storage)
    storage.conn.execute(
        "INSERT INTO actions (cycle_id, rule_id, url, level, status, fingerprint, before_json, "
        "after_json, rollback_json) VALUES ('c1','image_no_alt','https://x.com/c/','safe_fix',"
        "'pending','fp-alt',?,?,?)",
        (json.dumps({"alt_text": ""}), json.dumps({"alt_text": "x"}),
         json.dumps({"type": "wp_media_alt", "media_id": 1, "alt_text": ""})))
    storage.conn.commit()
    svc = ImprovementCampaignService(storage)
    assert svc.create("Mistura", "title_manual", ["fp-title-1", "fp-alt"]) is None
    storage.close()


def test_approve_pause_resume_cancel(tmp_path):
    storage = Storage(str(tmp_path / "c3.db"))
    _seed_actions(storage)
    svc = ImprovementCampaignService(storage)
    camp = svc.create("Títulos", "title_manual", ["fp-title-1"], created_by="admin@x.com")
    cid = camp["id"]
    assert svc.approve(cid, approved_by="admin@x.com")
    assert svc.get(cid)["status"] == "approved"
    svc.pause(cid)
    assert svc.get(cid)["status"] == "paused"
    svc.resume(cid)
    assert svc.get(cid)["status"] == "approved"
    svc.cancel(cid)
    assert svc.get(cid)["status"] == "cancelled"
    storage.close()


def test_preview_eligible_and_missing(tmp_path):
    storage = Storage(str(tmp_path / "p.db"))
    _seed_actions(storage)
    svc = ImprovementCampaignService(storage)
    res = svc.preview(["fp-title-1", "fp-title-2", "nao-existe"], max_actions_per_run=10)
    assert res["homogeneous"] is True
    assert res["action_type"] == "title_manual"
    assert len(res["eligible"]) == 2
    assert res["missing"] == ["nao-existe"]
    assert res["per_cycle"] == 2
    storage.close()


def test_preview_non_homogeneous_gives_per_cycle_zero(tmp_path):
    storage = Storage(str(tmp_path / "p2.db"))
    _seed_actions(storage)
    storage.conn.execute(
        "INSERT INTO actions (cycle_id, rule_id, url, level, status, fingerprint, before_json, "
        "after_json, rollback_json) VALUES ('c1','image_no_alt','https://x.com/c/','safe_fix',"
        "'pending','fp-alt',?,?,?)",
        (json.dumps({"alt_text": ""}), json.dumps({"alt_text": "x"}),
         json.dumps({"type": "wp_media_alt", "media_id": 1, "alt_text": ""})))
    storage.conn.commit()
    svc = ImprovementCampaignService(storage)
    res = svc.preview(["fp-title-1", "fp-alt"], max_actions_per_run=10)
    assert res["homogeneous"] is False
    assert res["action_type"] is None
    assert res["per_cycle"] == 0
    storage.close()


def test_run_campaign_batches(tmp_path):
    storage = Storage(str(tmp_path / "r.db"))
    _seed_actions(storage)
    svc = ImprovementCampaignService(storage)
    camp = svc.create("Títulos", "title_manual", ["fp-title-1", "fp-title-2"],
                      created_by="admin@x.com", max_actions_per_run=1)
    cid = camp["id"]
    svc.approve(cid, approved_by="admin@x.com")

    def fake_apply(actions):
        return {"executed": actions, "skipped": [], "previewed": [], "unverified": []}

    # 1º lote: executa 1 (max_actions_per_run=1), sobra 1
    run = svc.run(cid, actor="admin@x.com", apply=fake_apply)
    assert run is not None and run["status"] == "queued"
    assert run["executed_items"] == 1 and run["pending_items"] == 1

    # 2º lote: executa o restante -> completed
    run2 = svc.run(cid, actor="admin@x.com", apply=fake_apply)
    assert run2["status"] == "completed"
    assert run2["executed_items"] == 2 and run2["pending_items"] == 0
    storage.close()


def test_run_campaign_marks_failure_partial(tmp_path):
    storage = Storage(str(tmp_path / "r2.db"))
    _seed_actions(storage)
    svc = ImprovementCampaignService(storage)
    camp = svc.create("Títulos", "title_manual", ["fp-title-1", "fp-title-2"],
                      created_by="admin@x.com", max_actions_per_run=10)
    cid = camp["id"]
    svc.approve(cid, approved_by="admin@x.com")

    def fake_apply(actions):
        # primeiro executado, segundo unverified (falha)
        executed = [a for a in actions if a["_campaign_fp"] == "fp-title-1"]
        unverified = [a for a in actions if a["_campaign_fp"] == "fp-title-2"]
        return {"executed": executed, "skipped": [], "previewed": [], "unverified": unverified}

    run = svc.run(cid, actor="admin@x.com", apply=fake_apply)
    assert run["status"] == "partial"
    assert run["executed_items"] == 1 and run["failed_items"] == 1
    storage.close()


def test_persist_title_candidates_creates_action_and_checklist(tmp_path):
    from hermes_seo_agent.storage.db import Storage
    storage = Storage(str(tmp_path / "t.db"))
    n = storage.persist_title_candidates([
        {"url": "https://x.com/a/", "current_title": "velho", "suggested_title": "novo",
         "top_query": "q", "post_id": 5, "clicks": 3},
    ], cycle_id="c1")
    assert n == 1
    row = storage.conn.execute(
        "SELECT fingerprint, status, rule_id FROM actions WHERE url='https://x.com/a/'").fetchone()
    assert row is not None and row[2] == "title_opportunity" and row[1] == "pending"
    chk = storage.conn.execute(
        "SELECT item FROM improvement_checklist WHERE url='https://x.com/a/'").fetchone()
    assert chk is not None and chk[0] == "title"
    storage.close()


def test_run_campaign_links_outcome_for_revalidation(tmp_path):
    storage = Storage(str(tmp_path / "r3.db"))
    _seed_actions(storage)
    svc = ImprovementCampaignService(storage)
    camp = svc.create("Títulos", "title_manual", ["fp-title-1"], created_by="admin@x.com",
                      max_actions_per_run=10)
    cid = camp["id"]
    svc.approve(cid, approved_by="admin@x.com")
    def fake_apply(actions): return {"executed": actions, "skipped": [], "previewed": [], "unverified": []}
    svc.run(cid, actor="admin@x.com", apply=fake_apply)
    row = storage.conn.execute(
        "SELECT human_decision, url FROM opportunity_outcomes WHERE url='https://x.com/a/'").fetchone()
    assert row is not None and row[0] == "approved"
    storage.close()


def test_internal_link_campaign_mock(tmp_path):
    """B10 — mock do fluxo de campanha de links internos (WP fake)."""
    from hermes_seo_agent.config import Config
    from hermes_seo_agent.executor.executor import Executor, _fingerprint
    from hermes_seo_agent.report.interlinks import build_interlink_fix

    body = "<p>O novo trailer divide opiniões. Veja o elenco completo.</p>"
    fix = build_interlink_fix(source_url="https://x.com/a/", target_url="https://x.com/b/",
                              source_context={"body_text": body, "title": "Filme X"},
                              anchor="elenco completo", excerpt="Veja o elenco completo.",
                              post_id=7)
    assert fix is not None and fix["type"] == "wp_post_content_patch"

    storage = Storage(str(tmp_path / "il.db"))
    fp = _fingerprint("internal_link", "https://x.com/a/", "link interno", fix)
    storage.record_action(cycle_id="c1", rule_id="internal_link", url="https://x.com/a/",
                          level="safe_fix", fingerprint=fp,
                          before={"content": body}, after={"content": body}, rollback=fix,
                          status="pending", fix=fix)

    svc = ImprovementCampaignService(storage)
    camp = svc.create("Links internos", "internal_link", [fp], created_by="admin@x.com",
                      max_actions_per_run=5)
    assert camp is not None and camp["items"][0]["fix"]["type"] == "wp_post_content_patch"
    cid = camp["id"]
    svc.approve(cid, approved_by="admin@x.com")

    class FakeWP:
        def __init__(self): self.content = body; self.writes = []
        def get_post(self, pid): return {"id": pid, "content": {"raw": self.content}}
        def update_post_content(self, pid, content): self.writes.append(content); self.content = content

    wp = FakeWP()
    config = Config(wordpress_url="http://localhost", app_user="u", app_password="p",
                    dry_run=False, sqlite_path=str(tmp_path / "il.db"))

    def fake_apply(actions):
        return Executor(config, wp, storage).apply_safe_actions(actions, cycle_id="c1", max_actions=5)

    run = svc.run(cid, actor="admin@x.com", apply=fake_apply)
    assert run["status"] == "completed"
    assert run["executed_items"] == 1
    assert "https://x.com/b/" in wp.content       # link inserido
    assert len(wp.writes) == 1
    out = storage.conn.execute(
        "SELECT human_decision FROM opportunity_outcomes WHERE url='https://x.com/a/'").fetchone()
    assert out is not None and out[0] == "approved"
    storage.close()
