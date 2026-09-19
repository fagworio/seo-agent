"""SEO-INC-015/016: backoff respeitado, sync em lote e autoridade do título.

Os três achados da revisão de 19/09/2026 (commit 7d05669 -> HEAD):

1. `get_urls_for_audit` ignorava `next_audit_at` do trilho dirty: uma URL que
   falhou voltava a cada ciclo (2h) e martelava o servidor.
2. `sync_audit_inventory` fazia 1 SELECT + 1 UPSERT + 1 COMMIT por post
   (medido: 1.900 commits / 2,3s para 1.900 posts; ~19 mil por ciclo).
3. `current_title` tratava `corpus_documents` como autoridade absoluta — um
   corpus atrasado (rebuild limitado a 1.000/ciclo) fazia o diagnóstico acusar
   gap num título já corrigido.
"""

from __future__ import annotations

import datetime as dt
import tempfile

from hermes_seo_agent.services.audit_inventory import sync_audit_inventory
from hermes_seo_agent.storage.db import Storage


def _storage(tmp_path):
    return Storage(str(tmp_path / "s.db"))


def test_backoff_e_respeitado_na_fila(tmp_path):
    """SEO-INC-015: falha com next_audit_at no futuro NÃO entra na fila."""
    with _storage(tmp_path) as s:
        s.upsert_url_audit_state(url="https://www.unicorniohater.com.br/a/",
                                 dirty=True, dirty_reason="previous_failure")
        # agenda o backoff para amanhã
        futuro = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=6)).isoformat()
        s.conn.execute("UPDATE url_audit_state SET next_audit_at = ?", (futuro,))
        s.conn.commit()
        assert s.get_urls_for_audit(limit=10) == [], "backoff ignorado: martela a URL"

        # quando o backoff vence, a URL volta
        passado = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)).isoformat()
        s.conn.execute("UPDATE url_audit_state SET next_audit_at = ?", (passado,))
        s.conn.commit()
        assert [c["url"] for c in s.get_urls_for_audit(limit=10)], "vencido deve voltar"


def test_falha_nova_sem_next_audit_at_entra(tmp_path):
    """Sem next_audit_at gravado (1ª falha) a URL continua elegível."""
    with _storage(tmp_path) as s:
        s.upsert_url_audit_state(url="https://www.unicorniohater.com.br/b/",
                                 dirty=True, dirty_reason="previous_failure")
        assert [c["url"] for c in s.get_urls_for_audit(limit=10)]


def test_prioridade_p0_antes_de_falha(tmp_path):
    """Mudança real (P0) precede falha (P2) dentro do mesmo lote."""
    with _storage(tmp_path) as s:
        s.upsert_url_audit_state(url="https://www.unicorniohater.com.br/velho/",
                                 dirty=True, dirty_reason="previous_failure")
        s.upsert_url_audit_state(url="https://www.unicorniohater.com.br/novo/",
                                 dirty=True, dirty_reason="wordpress_modified")
        fila = s.get_urls_for_audit(limit=10)
        assert fila[0]["url"].endswith("/novo/"), fila


def test_sync_em_lote_grava_so_o_que_mudou(tmp_path):
    """SEO-INC-015: 1 SELECT + 1 COMMIT por sync, não 1 por post."""
    with _storage(tmp_path) as s:
        posts = [{"id": i, "link": f"https://prod.unicorniohater.com.br/p{i}/",
                  "modified": "2026-09-19T10:00:00"} for i in range(300)]
        ents = [(f"https://www.unicorniohater.com.br/p{i}/", "2026-09-19T10:00:00")
                for i in range(300)]

        commits = {"n": 0}
        s.conn.set_trace_callback(
            lambda sql: commits.__setitem__("n", commits["n"] + 1)
            if sql.strip().upper().startswith("COMMIT") else None)

        delta = sync_audit_inventory(s, posts, ents, static_host="www.unicorniohater.com.br")
        assert delta["new_url"] == 300 and delta["written"] == 300
        assert commits["n"] == 1, f"esperado 1 commit, veio {commits['n']}"

        # segunda passada: nada mudou -> zero escrita nova
        antes = commits["n"]
        delta2 = sync_audit_inventory(s, posts, ents, static_host="www.unicorniohater.com.br")
        assert delta2["unchanged"] == 300 and delta2["written"] == 0
        s.conn.set_trace_callback(None)
        assert commits["n"] == antes, "sync sem mudanças não deve commitar"


def test_current_title_prefere_fonte_mais_recente(tmp_path):
    """SEO-INC-016: corpus atrasado não ganha de uma captura mais nova."""
    from hermes_seo_agent.report.align import current_title

    with _storage(tmp_path) as s:
        s.conn.execute(
            "INSERT INTO corpus_documents (url, title, seo_title, built_at, content_hash) "
            "VALUES (?, ?, ?, ?, ?)",
            ("https://prod.unicorniohater.com.br/x/", "Titulo antigo do corpus",
             "Titulo antigo do corpus", "2026-09-01T00:00:00", "h1"))
        s.conn.execute(
            "INSERT INTO page_snapshots (url, title, captured_at) VALUES (?, ?, ?)",
            ("https://www.unicorniohater.com.br/x/", "Titulo NOVO no ar",
             "2026-09-19T12:00:00"))
        s.conn.commit()
        assert current_title(s, "https://www.unicorniohater.com.br/x/") == "Titulo NOVO no ar"

        # corpus mais novo vence a captura antiga
        s.conn.execute("UPDATE corpus_documents SET built_at = ?", ("2026-09-20T00:00:00",))
        s.conn.commit()
        assert current_title(s, "https://www.unicorniohater.com.br/x/") == "Titulo antigo do corpus"
