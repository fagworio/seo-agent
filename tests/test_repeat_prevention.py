"""Prevenção de repetição: o agente não deve re-tratar itens já em fila/medição."""
import datetime

from hermes_seo_agent.storage.db import Storage


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _days_ago(days: int) -> str:
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=days)).isoformat()


def test_title_review_skippable_pending(tmp_path):
    db = tmp_path / "d1.db"
    with Storage(str(db)) as s:
        s.save_checklist_item(url="https://x.com/a/", item="title_too_long",
                              reason="título longo", action="encurtar", gain_clicks=5.0)
        skip, reason = s.title_review_skippable("https://x.com/a/", measurement_days=28)
        assert skip is True
        assert "revisão" in reason


def test_title_review_skippable_recent_baseline(tmp_path):
    db = tmp_path / "d2.db"
    with Storage(str(db)) as s:
        s.conn.execute(
            "INSERT INTO opportunity_outcomes (keyword, opportunity_type, decision, human_decision, "
            "implemented_action, url, implemented_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("gojo", "expand_existing", "expand_existing", "approved", "expandir",
             "https://x.com/b/", _days_ago(2), _now()))
        s.conn.commit()
        skip, reason = s.title_review_skippable("https://x.com/b/", measurement_days=28)
        assert skip is True
        assert "baseline" in reason


def test_title_review_skippable_clean(tmp_path):
    db = tmp_path / "d3.db"
    with Storage(str(db)) as s:
        skip, reason = s.title_review_skippable("https://x.com/c/", measurement_days=28)
        assert skip is False and reason == ""


def test_checklist_dedup_no_duplicate_pending(tmp_path):
    """Correção 2: re-gerar o mesmo item não duplica a fila (refresca o pendente)."""
    db = tmp_path / "d4.db"
    with Storage(str(db)) as s:
        s.save_checklist_item(url="https://x.com/a/", item="title_too_long",
                              reason="título longo", action="encurtar", gain_clicks=5.0)
        s.save_checklist_item(url="https://x.com/a/", item="title_too_long",
                              reason="título longo (atualizado)", action="encurtar",
                              gain_clicks=6.0)
        rows = s.conn.execute(
            "SELECT COUNT(*) FROM improvement_checklist WHERE url = 'https://x.com/a/' "
            "AND status = 'pending'").fetchone()[0]
        assert rows == 1


def test_checklist_rejected_fingerprint_no_reopen(tmp_path):
    """Item rejeitado com a MESMA evidência não volta à fila (evita repetição)."""
    db = tmp_path / "d5.db"
    with Storage(str(db)) as s:
        s.save_checklist_item(url="https://x.com/a/", item="title_too_long",
                              reason="título longo", action="encurtar", gain_clicks=5.0)
        cid = s.conn.execute("SELECT id FROM improvement_checklist LIMIT 1").fetchone()[0]
        s.transition_checklist(cid, "rejected", reason="não fazer")
        # mesma evidência rejeitada -> não reabre
        reopened = s.save_checklist_item(url="https://x.com/a/", item="title_too_long",
                                         reason="título longo", action="encurtar",
                                         gain_clicks=5.0)
        assert reopened is False
        count = s.conn.execute(
            "SELECT COUNT(*) FROM improvement_checklist WHERE status = 'pending'"
        ).fetchone()[0]
        assert count == 0
