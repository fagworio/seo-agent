"""Tests for explainable scoring + closed workflow (points 4, 6, 7)."""

from hermes_seo_agent.report.scoring import confidence_for, effort, score_factors
from hermes_seo_agent.storage.db import Storage


# -- point 4: explainable score ---------------------------------------------

def test_score_factors_breakdown():
    factors = score_factors(item="title_meta", gain_clicks=100.0, evidence_quality=0.7)
    assert factors["score_breakdown"]["impacto"] == 0.5
    assert factors["score_breakdown"]["confianca"] == 0.7
    assert factors["score_breakdown"]["facilidade"] == 1.0  # title = effort 3
    assert factors["score"] == round(0.5 * 0.7 * 1.0, 3)


def test_score_factors_stability_affects_confidence():
    stable = score_factors(item="question_gap", gain_clicks=50.0,
                           evidence_quality=0.5, stable=True)
    declining = score_factors(item="question_gap", gain_clicks=50.0,
                              evidence_quality=0.5, stable=False)
    assert stable["score_breakdown"]["confianca"] > declining["score_breakdown"]["confianca"]


def test_confidence_for_evidence():
    assert confidence_for(has_queries=True, impressions=800, word_count=500) == 0.9
    low = confidence_for(has_queries=False, impressions=10, word_count=None)
    assert low < 0.5


def test_effort_mapping():
    assert effort("title_meta") == 3
    assert effort("supporting_post") == 1
    assert effort("unknown-item") == 2


# -- point 6: closed workflow ------------------------------------------------

def _pauta():
    return {"pauta_type": "supporting_post", "title": "Post: Gojo idade",
            "intent": "informational", "evidence": "500 impressões",
            "related_urls": [], "scope": "resposta própria",
            "duplication_risk": "baixo", "score": 2.0}


def test_workflow_snooze_supersede_and_expire(tmp_path):
    with Storage(tmp_path / "wf.db") as storage:
        storage.save_pauta(_pauta())
        pid = storage.list_backlog()[0]["id"]
        assert storage.transition_backlog(pid, "snoozed", deadline="2026-01-01T00:00:00+00:00")
        assert storage.transition_backlog(pid, "superseded")
        assert storage.expire_overdue() == 0  # já superseded, não vira expired


def test_expire_overdue_marks_proposed(tmp_path):
    with Storage(tmp_path / "exp.db") as storage:
        storage.save_pauta(_pauta())
        pid = storage.list_backlog()[0]["id"]
        # deadline vencido persiste na transição: approved + prazo passado -> expira.
        assert storage.transition_backlog(pid, "snoozed", deadline="2020-01-01T00:00:00+00:00")
        assert storage.expire_overdue() == 0  # snoozed não expira via expire_overdue
        storage.transition_backlog(pid, "approved")
        assert storage.expire_overdue() == 1  # approved com prazo vencido -> expired


def test_rejected_pauta_does_not_return(tmp_path):
    with Storage(tmp_path / "rej.db") as storage:
        assert storage.save_pauta(_pauta())
        pid = storage.list_backlog()[0]["id"]
        assert storage.transition_backlog(pid, "rejected", reason="fora de escopo")
        # nova geração da MESMA pauta é suprimida (sem evidência nova).
        assert not storage.save_pauta(_pauta())


def test_rejected_checklist_item_does_not_return(tmp_path):
    with Storage(tmp_path / "rej2.db") as storage:
        assert storage.save_checklist_item(url="https://x.com/a/", item="title_meta",
                                           reason="ctr baixo", action="reescrever", gain_clicks=5.0)
        cid = storage.list_checklist()[0]["id"]
        assert storage.transition_checklist(cid, "rejected", reason="título já ok")
        assert not storage.save_checklist_item(url="https://x.com/a/", item="title_meta",
                                               reason="ctr baixo", action="reescrever",
                                               gain_clicks=5.0)


# -- point 7: checklist measurement data ------------------------------------

def test_checklist_measure_fields(tmp_path):
    with Storage(tmp_path / "meas.db") as storage:
        assert storage.save_checklist_item(url="https://x.com/a/", item="title_meta",
                                           reason="r", action="a", gain_clicks=None)
        cid = storage.list_checklist()[0]["id"]
        assert storage.transition_checklist(cid, "done", intervention_type="title_meta",
                                            baseline={"impressions": 100, "clicks": 0})
        item = storage.get_checklist_item(cid)
        assert item["intervention_type"] == "title_meta"
        assert item["baseline"] == {"impressions": 100, "clicks": 0}


def test_score_unknown_gain_has_base_impacto():
    """Sugestão sem ganho estimado não deve ficar com score 0."""
    factors = score_factors(item="question_gap", gain_clicks=None, evidence_quality=0.6)
    assert factors["score_breakdown"]["impacto"] == 0.3
    assert factors["score"] > 0.0


def test_rejected_checklist_reopens_only_with_new_evidence(tmp_path):
    with Storage(tmp_path / "reopen.db") as storage:
        assert storage.save_checklist_item(url="https://x.com/a/", item="title_meta",
                                           reason="ctr 0% p/ 500 impr", action="a", gain_clicks=None)
        cid = storage.list_checklist()[0]["id"]
        assert storage.transition_checklist(cid, "rejected", reason="fora de escopo")
        # mesma EVIDÊNCIA MATERIAL (mudança só de métrica) -> bloqueada
        assert not storage.save_checklist_item(url="https://x.com/a/", item="title_meta",
                                               reason="ctr 0% p/ 2500 impr", action="a",
                                               gain_clicks=None)
        # evidência QUALITATIVAMENTE nova (outra lacuna) -> reabre
        assert storage.save_checklist_item(url="https://x.com/a/", item="title_meta",
                                           reason="pergunta sem seção que responda", action="a",
                                           gain_clicks=None)


def test_pauta_reopens_only_with_new_evidence(tmp_path):
    with Storage(tmp_path / "reopen2.db") as storage:
        p = {"pauta_type": "supporting_post", "title": "Gojo", "intent": "q",
             "evidence": "500 impr", "related_urls": [], "scope": "resposta",
             "duplication_risk": "baixo", "score": 2.0}
        assert storage.save_pauta(p)
        pid = storage.list_backlog()[0]["id"]
        assert storage.transition_backlog(pid, "rejected", reason="duplicado")
        # mudança só de métrica -> bloqueada (mesma evidência material)
        assert not storage.save_pauta(dict(p, evidence="5000 impr"))
        # mudança qualitativa (outro ângulo/escopo) -> reabre
        assert storage.save_pauta(dict(p, evidence="5000 impr",
                                       scope="foco em feiticeiros secundários"))


def test_checklist_done_sets_implemented_at_and_baseline(tmp_path):
    with Storage(tmp_path / "impl.db") as storage:
        assert storage.save_checklist_item(url="https://x.com/a/", item="title_meta",
                                           reason="r", action="a", gain_clicks=None)
        cid = storage.list_checklist()[0]["id"]
        assert storage.transition_checklist(cid, "done", intervention_type="title_meta",
                                            baseline={"impressions": 100, "clicks": 0})
        item = storage.get_checklist_item(cid)
        assert item["implemented_at"] is not None
        assert item["baseline"] == {"impressions": 100, "clicks": 0}


def test_material_fingerprint_preserves_intent_numbers(tmp_path):
    """Métrica muda -> bloqueia; número de intenção (ano/versão) muda -> reabre."""
    with Storage(tmp_path / "fp2.db") as storage:
        assert storage.save_checklist_item(url="https://x.com/a/", item="title_meta",
                                           reason="ctr 0% p/ 500 impr", action="a", gain_clicks=None)
        cid = storage.list_checklist()[0]["id"]
        assert storage.transition_checklist(cid, "rejected", reason="x")
        # só métrica mudou -> mesmo fingerprint material -> bloqueado
        assert not storage.save_checklist_item(url="https://x.com/a/", item="title_meta",
                                               reason="ctr 0% p/ 2500 impr", action="a",
                                               gain_clicks=None)
        # número de INTENÇÃO mudou (guia 2025 -> 2026) -> reabre
        assert storage.save_checklist_item(url="https://x.com/a/", item="title_meta",
                                           reason="guia 2025 desatualizado", action="a",
                                           gain_clicks=None)


def test_checklist_persists_score_and_orders_by_priority(tmp_path):
    with Storage(tmp_path / "score.db") as storage:
        storage.save_checklist_item(url="https://x.com/low/", item="title_meta",
                                    reason="r1", action="a", gain_clicks=None,
                                    explainable_score=0.2,
                                    score_breakdown={"impacto": 0.2, "confianca": 0.5})
        storage.save_checklist_item(url="https://x.com/high/", item="title_meta",
                                    reason="r2", action="a", gain_clicks=None,
                                    explainable_score=0.9,
                                    score_breakdown={"impacto": 0.9, "confianca": 0.8})
        items = storage.list_checklist(status="pending")
        assert items[0]["url"] == "https://x.com/high/"  # prioridade DESC
        assert items[0]["explainable_score"] == 0.9
        assert items[0]["score_breakdown"]["impacto"] == 0.9


def test_pending_duplicate_refreshes_score(tmp_path):
    with Storage(tmp_path / "refresh.db") as storage:
        assert storage.save_checklist_item(url="https://x.com/a/", item="title_meta",
                                           reason="r1", action="a", gain_clicks=None,
                                           explainable_score=0.3)
        # mesmo hypothesis_key pendente -> atualiza score/evidência, sem duplicar
        assert storage.save_checklist_item(url="https://x.com/a/", item="title_meta",
                                           reason="r1 com evidência nova", action="a",
                                           gain_clicks=None, explainable_score=0.7)
        items = storage.list_checklist(status="pending")
        assert len(items) == 1
        assert items[0]["explainable_score"] == 0.7
        assert "evidência nova" in items[0]["reason"]


# -- backfill precision: per-URL aggregated demand (latest window) -----------

def test_url_demand_aggregates_latest_window(tmp_path):
    """url_demand soma TODAS as queries da URL na janela mais recente (mesma
    base de content-brief/post-audit), com posição ponderada por impressões."""
    url = "https://x.com/a/"
    with Storage(tmp_path / "dem.db") as storage:
        storage.save_query_pages(
            [
                {"query": "q1", "url": url, "clicks": 2, "impressions": 200,
                 "ctr": 0.01, "position": 5, "intent": "informational"},
                {"query": "q2", "url": url, "clicks": 3, "impressions": 300,
                 "ctr": 0.01, "position": 7, "intent": "informational"},
            ],
            window_start="2025-06-01", window_end="2025-06-28",
        )
        # janela ANTIGA: mesma URL com mais impressões — deve ser ignorada
        storage.save_query_pages(
            [
                {"query": "q0", "url": url, "clicks": 9, "impressions": 900,
                 "ctr": 0.01, "position": 3, "intent": "informational"},
                {"query": "q0", "url": "https://x.com/old-only/", "clicks": 1,
                 "impressions": 50, "ctr": 0.02, "position": 4, "intent": "informational"},
            ],
            window_start="2025-05-01", window_end="2025-05-28",
        )
        demand = storage.url_demand(url)
        assert demand["has_queries"] is True
        assert demand["impressions"] == 500.0        # 200 + 300 (janela mais recente)
        assert demand["clicks"] == 5.0               # 2 + 3
        assert demand["position"] == 6.2             # (200*5 + 300*7) / 500
        # URL que só existe na janela antiga -> sem demanda na janela vigente
        assert storage.url_demand("https://x.com/old-only/")["has_queries"] is False
        assert storage.url_demand("https://x.com/old-only/")["impressions"] == 0.0
        # janela histórica DECLARADA explicitamente -> respeita o filtro
        assert storage.url_demand(url, window_start="2025-05-01")["impressions"] == 900.0


def test_checklist_rescore_aggregates_url_demand(tmp_path, capsys):
    """checklist rescore usa a demanda AGREGADA da URL (não queries_for_url
    limit=1): 200@5 + 300@7 -> confiança 0.8 -> score 0.3*0.8*1.0 = 0.24."""
    import argparse
    import json

    from hermes_seo_agent.cli import _cmd_checklist
    from hermes_seo_agent.config import Config

    url = "https://x.com/a/"
    db_path = tmp_path / "rescore.db"
    with Storage(db_path) as storage:
        storage.save_query_pages(
            [
                {"query": "q1", "url": url, "clicks": 2, "impressions": 200,
                 "ctr": 0.01, "position": 5, "intent": "informational"},
                {"query": "q2", "url": url, "clicks": 3, "impressions": 300,
                 "ctr": 0.01, "position": 7, "intent": "informational"},
            ],
            window_start="2025-06-01", window_end="2025-06-28",
        )
        assert storage.save_checklist_item(url=url, item="title_meta",
                                           reason="ctr baixo", action="reescrever",
                                           gain_clicks=None)
        cid = storage.list_checklist()[0]["id"]

    config = Config(wordpress_url="http://localhost", sqlite_path=str(db_path))
    args = argparse.Namespace(action="rescore", limit=0, all=False,
                              item_id=None, json=True)
    assert _cmd_checklist(args, config) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["summary"]["re_scored"] == 1
    assert out["summary"]["without_demand"] == 0

    with Storage(db_path) as storage:
        item = storage.get_checklist_item(cid)
        assert item["explainable_score"] == 0.24
        assert item["score_breakdown"]["confianca"] == 0.8
        assert item["score_breakdown"]["impacto"] == 0.3  # ganho desconhecido


def test_content_brief_score_uses_aggregated_url_demand(tmp_path, monkeypatch, capsys):
    """content-brief usa url_demand() (TODAS as queries da janela) no score,
    não as top-10 do diagnóstico: 12 queries × 45 impr = 540 (>= 500 -> conf. 0.9);
    se fossem as top-10 (450 < 500) a confiança seria 0.8."""
    import argparse
    import json

    from hermes_seo_agent.cli import _cmd_content_brief
    from hermes_seo_agent.config import Config
    from hermes_seo_agent.connectors.static_site import PageSnapshot, StaticSiteClient

    url = "https://x.com/a/"
    db_path = tmp_path / "brief.db"
    rows = [
        {"query": f"q{i:02d}", "url": url, "clicks": 1, "impressions": 45,
         "ctr": 0.02, "position": 6, "intent": "informational"}
        for i in range(12)
    ]
    with Storage(db_path) as storage:
        storage.save_query_pages(rows, window_start="2025-06-01",
                                 window_end="2025-06-28")

    page = PageSnapshot(url, 200)
    page.title = "Guia"
    page.h1 = ["Guia"]
    page.h2s = ["Resumo"]
    page.body_text = "palavra " * 300  # word_count > 0 -> +0.1 de confiança
    page.links = []

    def _fake_fetch(self, u):
        return page

    monkeypatch.setattr(StaticSiteClient, "fetch_page", _fake_fetch)
    config = Config(wordpress_url="http://localhost", sqlite_path=str(db_path))
    args = argparse.Namespace(single_url=url, limit=0, store=False, json=True)
    assert _cmd_content_brief(args, config) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "ok"
    assert out["briefs"][0]["url"] == url
    checklist = out["briefs"][0]["checklist"]
    assert checklist, "content-brief deveria gerar itens para a URL"
    # Confiança 0.9 só é alcançada com o AGREGADO (540 impr): 0.3 base + 0.3
    # queries + 0.2 (>=500) + 0.1 (word_count). Top-10 (450) daria 0.8.
    assert all(i["score_breakdown"]["confianca"] == 0.9 for i in checklist)
    assert any(i["score_breakdown"]["confianca"] == 0.9 for i in checklist)
