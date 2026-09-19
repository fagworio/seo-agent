"""SEO-INC: auditoria incremental por URL (fila, backoff, cobertura, lifecycle).

Cobre as mudancas SEO-INC-002/003/005/007: o audit deixa de andar um cursor
cego sobre o sitemap e passa a consumir uma fila por URL, alimentada por um
inventario que compara o estado barato (WP modified + sitemap lastmod).
"""
from hermes_seo_agent.services.audit_inventory import sync_audit_inventory
from hermes_seo_agent.storage.db import Storage


def _storage(tmp_path, name="inc.db"):
    return Storage(str(tmp_path / name))


def test_fila_incremental_por_url(tmp_path):
    """Auditado sai da fila; nunca auditado entra; falha volta com backoff."""
    with _storage(tmp_path) as s:
        s.upsert_url_audit_state(url="https://x.com/nova/", dirty=True,
                                 dirty_reason="new_url")
        fila = s.get_urls_for_audit(limit=10)
        assert [f["url"] for f in fila] == ["https://x.com/nova/"]

        s.mark_url_audited(url="https://x.com/nova/", status_code=200,
                           content_hash="h")
        assert s.get_urls_for_audit(limit=10) == []
        cov = s.audit_coverage()
        assert cov["known"] == 1 and cov["never_audited"] == 0 and cov["stale"] == 0

        s.mark_url_audit_failed(url="https://x.com/quebrada/", status_code=404)
        s.mark_url_audit_failed(url="https://x.com/quebrada/", status_code=404)
        fila = s.get_urls_for_audit(limit=10)
        assert fila[0]["dirty_reason"] == "previous_failure"
        assert fila[0]["failure_count"] == 2
        assert s.audit_coverage()["failed"] == 1


def test_inventory_detecta_apenas_o_que_mudou(tmp_path):
    """WP modified / sitemap lastmod: so o delta vira dirty (nao o acervo)."""
    posts = [
        {"id": 1, "link": "https://prod.x.com/a/", "modified": "2026-09-01T10:00"},
        {"id": 2, "link": "https://prod.x.com/b/", "modified": "2026-09-01T10:00"},
    ]
    sm = [("https://www.x.com/a/", "2026-09-01"), ("https://www.x.com/b/", "2026-09-01")]
    with _storage(tmp_path, "inv.db") as s:
        d1 = sync_audit_inventory(s, posts, sm, static_host="www.x.com")
        assert d1["new_url"] == 2, "primeira varredura: tudo novo"

        # nada mudou -> nada dirty (sem reprocessar o acervo)
        d2 = sync_audit_inventory(s, posts, sm, static_host="www.x.com")
        assert d2["unchanged"] == 2 and d2["new_url"] == 0

        # 1 post modificado + 1 fora do sitemap
        posts2 = [
            {"id": 1, "link": "https://prod.x.com/a/", "modified": "2026-09-18T09:00"},
            {"id": 2, "link": "https://prod.x.com/b/", "modified": "2026-09-01T10:00"},
        ]
        d3 = sync_audit_inventory(s, posts2, [sm[0]], static_host="www.x.com")
        assert d3["wordpress_modified"] == 1
        assert d3["missing_from_sitemap"] == 1
        fila = {f["url"] for f in s.get_urls_for_audit(limit=10)}
        assert "https://www.x.com/a/" in fila and "https://www.x.com/b/" in fila


def test_resolve_no_action_encerra_o_item(tmp_path):
    """SEO-INC-007: item triado sem acao vira estado terminal (nao fica pending)."""
    with _storage(tmp_path, "life.db") as s:
        s.save_checklist_item(url="https://x.com/a/", item="title_regression",
                              reason="medicao 7d: worsened", action="retriar",
                              gain_clicks=0)
        cid = s.conn.execute("SELECT id FROM improvement_checklist").fetchone()[0]
        assert s.resolve_checklist_no_action(
            cid, reason="query_already_present",
            evidence={"impressions": 162, "position": 4.85}, next_review_days=28)
        row = s.conn.execute(
            "SELECT status, rejection_reason, resolution_json, deadline "
            "FROM improvement_checklist WHERE id = ?", (cid,)).fetchone()
        assert row[0] == "resolved_no_action"
        assert row[1] == "query_already_present"
        assert "162" in (row[2] or "")
        assert row[3], "next_review agendado"
        # resolver de novo nao reabre (idempotente por status)
        assert s.resolve_checklist_no_action(cid, reason="x") is False


def test_posts_cache_pula_varredura_quando_sinal_igual(tmp_path):
    """SEO-INC-009: sinal igual -> nao baixa os 19k posts de novo (187x)."""
    from types import SimpleNamespace

    from hermes_seo_agent.services.run_context import RunContext

    chamadas = {"lista": 0}

    class WP:
        def posts_signal(self, status="publish"):
            return {"total": "3", "last_modified": "2026-09-19T10:00:00"}

        def list_posts(self, status="publish"):
            chamadas["lista"] += 1
            return [{"id": 1, "link": "https://prod/x/", "modified": "m1",
                     "slug": "x", "status": "publish"}]

    ctx = SimpleNamespace(config=SimpleNamespace(sqlite_path=str(tmp_path / "s.db")))
    ctx.wordpress = lambda: WP()
    ctx._posts = None
    assert len(RunContext.posts(ctx)) == 1
    assert chamadas["lista"] == 1
    ctx._posts = None  # nova "instancia"
    assert len(RunContext.posts(ctx)) == 1
    assert chamadas["lista"] == 1, "nao deveria refazer a varredura completa"


def test_posts_cache_rebusca_quando_sinal_muda(tmp_path):
    """Post novo/editado (sinal diferente) -> full refresh."""
    from types import SimpleNamespace

    from hermes_seo_agent.services.run_context import RunContext

    chamadas = {"lista": 0}
    estado = {"total": "3"}

    class WP:
        def posts_signal(self, status="publish"):
            return {"total": estado["total"], "last_modified": "2026-09-19T10:00:00"}

        def list_posts(self, status="publish"):
            chamadas["lista"] += 1
            return [{"id": 1, "link": "https://prod/x/", "modified": "m1",
                     "slug": "x", "status": "publish"}]

    ctx = SimpleNamespace(config=SimpleNamespace(sqlite_path=str(tmp_path / "s.db")))
    ctx.wordpress = lambda: WP()
    ctx._posts = None
    RunContext.posts(ctx)
    estado["total"] = "4"
    ctx._posts = None
    RunContext.posts(ctx)
    assert chamadas["lista"] == 2, "sinal mudou -> deve rebuscar"


def test_sweep_respeita_o_teto_por_ciclo(tmp_path):
    """SEO-INC-011: o rodizio de paginas saas nao atropela o incremental."""
    import datetime as dt

    with _storage(tmp_path) as s:
        atras = (dt.datetime.now(dt.timezone.utc)
                 - dt.timedelta(days=10)).isoformat()
        for i in range(3):  # paginas saas vencidas (P3/P4)
            url = f"https://www.u.com/saudavel-{i}/"
            s.upsert_url_audit_state(url=url, dirty=False)
            s.conn.execute(
                "UPDATE url_audit_state SET last_audited_at = ?, next_audit_at = ? "
                "WHERE url = ?", (atras, atras, url))
        s.upsert_url_audit_state(url="https://www.u.com/nova/", dirty=True,
                                 dirty_reason="new_url")  # expresso (P0)
        s.conn.commit()
        fila = s.get_urls_for_audit(limit=10, sweep_limit=1)
        duros = [c for c in fila if c["dirty_reason"] or not c["last_audited_at"]]
        saas = [c for c in fila if not c["dirty_reason"] and c["last_audited_at"]]
        assert len(duros) == 1, "o expresso sempre entra"
        assert len(saas) == 1, "o rodizio respeita o teto do ciclo"
        # sweep_limit=0 -> nenhum rodizio, so o expresso
        assert len(s.get_urls_for_audit(limit=10, sweep_limit=0)) == 1
