"""Control plane read models (framework-agnóstico, pronto p/ FastAPI).

Compose os services existentes (OpportunityFeedService, IntegrationStatusService,
AgentRunService) em DTOs de PRODUTO — não comandos CLI — para as telas
Hoje, Caixa de Trabalho, Fontes de dados e Atividade. A UI nunca lê SQLite
nem Markdown diretamente; consome estes contratos.

Sem escrita: apenas projeções determinísticas sobre o Storage.
"""

from __future__ import annotations

import json
from typing import Any

from ..config import Config
from .agent_runs import AgentRunService
from .integration_status import IntegrationStatusService
from .opportunity import OpportunityFeedService

_REVIEW_STATUS = {"pending", "proposed", "review", "snoozed"}


class ControlPlaneService:
    def __init__(self, storage: Any, config: Config) -> None:
        self.storage = storage
        self.config = config
        self.opportunities = OpportunityFeedService(storage)
        self.runs = AgentRunService(storage)

    # -- SEO Técnico (F9) ----------------------------------------------------
    def technical(self, *, rule: str | None = None, limit: int = 200) -> dict[str, Any]:
        """Separa DIAGNÓSTICO (problemas) de CORREÇÕES (ações safe_fix com preview).

        Os problemas vêm dos findings determinísticos; as correções vêm das ações
        safe_fix registradas (com before/after/rollback para preview e reversão).
        """
        problems_sql = ("SELECT rule_id, url, severity, detail_json, created_at, cycle_id "
                        "FROM findings WHERE 1=1")
        params: list[Any] = []
        if rule:
            problems_sql += " AND rule_id = ?"
            params.append(rule)
        problems_sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        problems = []
        try:
            for r in self.storage.conn.execute(problems_sql, params).fetchall():
                problems.append({"rule_id": r[0], "url": r[1], "severity": r[2],
                                 "detail": self._json(r[3]) or {}, "created_at": r[4]})
        except Exception:
            pass

        corrections = []
        try:
            for r in self.storage.conn.execute(
                "SELECT fingerprint, rule_id, url, level, status, before_json, after_json, "
                "rollback_json, executed_at FROM actions WHERE level = 'safe_fix' "
                "ORDER BY id DESC LIMIT ?", (limit,)).fetchall():
                corrections.append({
                    "fingerprint": r[0], "rule_id": r[1], "url": r[2], "level": r[3],
                    "status": r[4], "before": self._json(r[5]), "after": self._json(r[6]),
                    "rollback": self._json(r[7]), "executed_at": r[8],
                })
        except Exception:
            pass
        return {"problems": problems, "corrections": corrections}

    def action_preview(self, fingerprint: str) -> dict[str, Any] | None:
        """Preview de uma correção (before/after/rollback) — somente leitura."""
        try:
            r = self.storage.conn.execute(
                "SELECT fingerprint, rule_id, url, status, before_json, after_json, "
                "rollback_json, executed_at FROM actions WHERE fingerprint = ?",
                (fingerprint,)).fetchone()
        except Exception:
            return None
        if not r:
            return None
        return {"fingerprint": r[0], "rule_id": r[1], "url": r[2], "status": r[3],
                "before": self._json(r[4]), "after": self._json(r[5]),
                "rollback": self._json(r[6]), "executed_at": r[7]}

    def technical_findings(self, *, rule: str | None = None, limit: int = 200,
                           sort: str = "potential") -> list[dict[str, Any]]:
        """Read model ENRIQUECIDO para a tela SEO Técnico (fila de decisão).

        Cada finding vira um objeto com identidade de página (public_url/wordpress_url),
        evidência do Search Console (query_pages + seo_expectations), potencial
        estimado (cenários conservador/realista/otimista) e apresentação da regra.
        missing ≠ zero: sem coleta Google, os números ficam ausentes (não 0).
        """
        from ..inventory.reconcile import normalize_url
        from .rule_catalog import rule_presentation

        # Janela GSC mais recente (cache único — evita re-consulta por linha).
        window = self._latest_gsc_window()

        rows = self.storage.conn.execute(
            "SELECT rule_id, url, severity, detail_json, created_at FROM findings "
            "WHERE 1=1"
            + (" AND rule_id = ?" if rule else "")
            + " ORDER BY id DESC LIMIT ?", (*([] if not rule else [rule]), limit),
        ).fetchall()
        out = []
        for r in rows:
            rule_id, url, severity = r[0], r[1], r[2]
            identity = self._resolve_page_identity(url)
            pres = rule_presentation(rule_id)
            gsc = self._google_evidence(identity["public_url"], window)
            expectation = self._traffic_expectation(identity["public_url"])
            out.append({
                "rule_id": rule_id,
                "rule": pres,
                "severity": severity or pres["severity"],
                "page": identity,
                "title": self._page_title(identity["public_url"]),
                "google": gsc,
                "potential": expectation,
                "created_at": r[4],
            })
        if sort == "potential":
            out.sort(key=lambda f: (f["potential"]["realistic"] is None,
                                    -(f["potential"]["realistic"] or 0), f["rule"]["label"]))
        elif sort == "impressions":
            out.sort(key=lambda f: -(f["google"]["impressions"] or 0))
        elif sort == "severity":
            order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
            out.sort(key=lambda f: order.get(f["severity"], 9))
        elif sort == "recent":
            out.sort(key=lambda f: f["created_at"], reverse=True)
        return out

    def _latest_gsc_window(self) -> tuple[str, str]:
        try:
            row = self.storage.conn.execute(
                "SELECT window_start, window_end FROM query_pages "
                "ORDER BY window_start DESC LIMIT 1").fetchone()
            return (row[0], row[1]) if row else ("", "")
        except Exception:
            return ("", "")

    def _resolve_page_identity(self, url: str) -> dict[str, Any]:
        """Resolve a identidade por PATH (host-independente), nunca por hostname.

        public_url = site público/headless (Google crawla); wordpress_url = origem
        editorial. Antes de usar localhost/dvl.to como URL analisada, normaliza.
        """
        from ..inventory.reconcile import normalize_url
        path = normalize_url(url or "")
        static = getattr(self.config, "static_site_url", "https://www.unicorniohater.com.br")
        wp_public = getattr(self.config, "wordpress_public_url", "https://prod.unicorniohater.com.br")
        public_url = f"{static.rstrip('/')}{path}"
        return {
            "path": path,
            "finding_url": url,
            "public_url": public_url,
            "wordpress_url": f"{wp_public.rstrip('/')}{path}",
            "wordpress_edit_url": "",          # sem wp_post_id persistido -> não inventa
            "headless": True,
        }

    def _page_title(self, public_url: str) -> str:
        try:
            row = self.storage.conn.execute(
                "SELECT title FROM page_snapshots WHERE url = ? AND title <> '' "
                "ORDER BY captured_at DESC LIMIT 1", (public_url,)).fetchone()
            return row[0] if row and row[0] else ""
        except Exception:
            return ""

    def _google_evidence(self, public_url: str, window: tuple[str, str]) -> dict[str, Any]:
        w_start, w_end = window
        try:
            row = self.storage.conn.execute(
                "SELECT SUM(clicks), SUM(impressions), AVG(position), COUNT(*) "
                "FROM query_pages WHERE url = ? AND window_start = ?",
                (public_url, w_start)).fetchone()
        except Exception:
            row = None
        impressions = row[1] if row else 0
        clicks = row[0] if row else 0
        count = row[3] if row else 0
        data_status = "available" if count and impressions else "missing"
        top_queries = []
        if count:
            try:
                for q in self.storage.conn.execute(
                    "SELECT query, clicks, impressions, ctr, position FROM query_pages "
                    "WHERE url = ? AND window_start = ? ORDER BY impressions DESC LIMIT 5",
                    (public_url, w_start)).fetchall():
                    top_queries.append({"query": q[0], "clicks": q[1] or 0,
                                        "impressions": q[2] or 0, "ctr": q[3], "position": q[4]})
            except Exception:
                top_queries = []
        # Expected/gap a partir do seo_expectations (nunca 0 falso: só se existir).
        exp = self._traffic_expectation(public_url)
        return {
            "data_status": data_status,
            "window_start": w_start, "window_end": w_end,
            "clicks": clicks if data_status == "available" else None,
            "impressions": impressions if data_status == "available" else None,
            "ctr": (clicks / impressions) if data_status == "available" and impressions else None,
            "position": round(row[2], 1) if row and row[2] is not None else None,
            "expected_ctr": exp["ctr_expected"],
            "expected_clicks": exp["expected_clicks"],
            "gap_clicks": exp["gap_clicks"],
            "top_queries": top_queries,
        }

    def _traffic_expectation(self, public_url: str) -> dict[str, Any]:
        """Potencial estimado: cenários de seo_expectations (não inventa se não existe)."""
        try:
            row = self.storage.conn.execute(
                "SELECT position, impressions, clicks, ctr, expected_ctr, expected_clicks, "
                "gap_clicks, conservative_clicks, realistic_clicks, optimistic_clicks "
                "FROM seo_expectations WHERE url = ? ORDER BY computed_at DESC LIMIT 1",
                (public_url,)).fetchone()
        except Exception:
            row = None
        if not row:
            return {"data_status": "missing", "conservative": None, "realistic": None,
                    "optimistic": None, "ctr_expected": None, "expected_clicks": None,
                    "gap_clicks": None}
        return {
            "data_status": "available" if row[8] is not None else "missing",
            "position": row[0], "impressions": row[1], "clicks": row[2], "ctr": row[3],
            "ctr_expected": row[4],
            "expected_clicks": row[5], "gap_clicks": row[6],
            "conservative": row[7], "realistic": row[8], "optimistic": row[9],
        }

    # -- Páginas (F8) --------------------------------------------------------
    def pages(self, *, query: str = "", limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Explorer de páginas: snapshot mais recente por URL + métricas."""
        sql = ("SELECT id, url, title, status_code, captured_at, meta_robots, CANONICAL, "
               "word_count FROM page_snapshots WHERE id IN "
               "(SELECT MAX(id) FROM page_snapshots GROUP BY url)")
        params: list[Any] = []
        if query:
            sql += " AND url LIKE ?"
            params.append(f"%{query}%")
        sql += " ORDER BY captured_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        try:
            rows = self.storage.conn.execute(sql, params).fetchall()
        except Exception:
            return []
        out = []
        for r in rows:
            url = r[1]
            out.append({
                "url": url,
                "title": r[2] or "",
                "health": self._page_health(r[3], r[5]),
                "index_state": self._index_state(url, r[5]),
                "metrics": self._page_metrics(url),
                "primary_opportunity": self._primary_opportunity(url),
                "captured_at": r[4],
                "word_count": r[7] or 0,
            })
        return out

    def page_history(self, url: str) -> list[dict[str, Any]]:
        """Timeline narrativa por URL: detecção -> aprovação -> implementação ->
        recrawl -> medição (snapshots + ação vinculada)."""
        try:
            rows = self.storage.conn.execute(
                "SELECT captured_at, source, linked_action, status_code, title, "
                "meta_robots, canonical, cwv_json, gsc_json, content_hash "
                "FROM page_snapshots WHERE url = ? ORDER BY captured_at",
                (url,),
            ).fetchall()
        except Exception:
            return []
        out = []
        for r in rows:
            out.append({
                "ts": r[0], "source": r[1], "linked_action": r[2] or "",
                "status_code": r[3], "title": r[4] or "",
                "meta_robots": r[5] or "", "canonical": r[6] or "",
                "cwv": self._json(r[7]), "gsc": self._json(r[8]),
                "content_hash": r[9],
            })
        return out

    def editorial_items(self, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        """Editorial backlog as a product board, preserving the native workflow."""
        sql = ("SELECT id, pauta_type, title, intent, evidence, related_urls_json, scope, "
               "duplication_risk, score, status, created_at, published_url, baseline_json, "
               "responsible, deadline FROM editorial_backlog WHERE 1=1")
        params: list[Any] = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY score DESC, id DESC LIMIT ?"
        params.append(limit)
        rows = self.storage.conn.execute(sql, params).fetchall()
        return [{"id": f"backlog:{r[0]}", "type": r[1], "title": r[2] or "",
                 "intent": r[3] or "", "evidence": r[4] or "",
                 "related_urls": self._json(r[5]) or [], "recommendation": r[6] or "",
                 "duplication_risk": r[7] or "", "score": r[8], "status": r[9],
                 "created_at": r[10] or "", "published_url": r[11] or "",
                 "baseline": self._json(r[12]) or {}, "responsible": r[13] or "",
                 "deadline": r[14] or ""} for r in rows]

    def transition_editorial(self, item_id: str, status: str, *, actor: str,
                             published_url: str = "", reason: str = "") -> dict[str, Any] | None:
        source, _, key = item_id.partition(":")
        if source != "backlog" or not key.isdigit():
            return None
        if not self.storage.transition_backlog(int(key), status, published_url=published_url, reason=reason):
            return None
        self.storage.log_audit(actor, f"EDITORIAL_{status.upper()}", item_id,
                               {"published_url": published_url}, {"status": status})
        return {"id": item_id, "status": status}

    def _page_health(self, status_code: int | None, meta_robots: str | None) -> str:
        if status_code is not None and status_code >= 400:
            return "error"
        if "noindex" in (meta_robots or "").lower():
            return "noindex"
        if status_code in (301, 302):
            return "redirect"
        return "ok"

    def _index_state(self, url: str, meta_robots: str | None) -> str:
        if "noindex" in (meta_robots or "").lower():
            return "noindex"
        try:
            row = self.storage.conn.execute(
                "SELECT in_sitemap FROM urls WHERE url = ?", (url,)).fetchone()
            if row is not None and row[0] == 0:
                return "not_in_sitemap"
        except Exception:
            pass
        return "indexed"

    def _page_metrics(self, url: str) -> dict[str, Any]:
        try:
            row = self.storage.conn.execute(
                "SELECT position, impressions, clicks, ctr FROM seo_expectations "
                "WHERE url = ? ORDER BY computed_at DESC LIMIT 1", (url,)).fetchone()
            if not row:
                return {"position": None, "impressions": 0, "clicks": 0, "ctr": None}
            return {"position": row[0], "impressions": row[1] or 0, "clicks": row[2] or 0,
                    "ctr": row[3]}
        except Exception:
            return {"position": None, "impressions": 0, "clicks": 0, "ctr": None}

    def _primary_opportunity(self, url: str) -> str:
        try:
            for it in self.opportunities.feed(limit=50):
                if it.get("url") == url:
                    return it.get("title") or it.get("source", "")
        except Exception:
            pass
        return ""

    @staticmethod
    def _json(value: str | None) -> Any:
        if not value:
            return None
        try:
            return json.loads(value)
        except Exception:
            return None

    # -- Experimentos (F11) --------------------------------------------------
    def experiments(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Intervenções implementadas com baseline, janela de medição e delta.

        Distingue movimento observado de certeza causal: expõe baseline, verdict
        e o estado de medição (waiting_data | measuring | measured). Nunca
        sobrestima causalidade sem evidência.
        """
        try:
            rows = self.storage.conn.execute(
                "SELECT keyword, opportunity_type, url, implemented_action, "
                "implemented_at, baseline_json, verdict, measured_28d, measured_56d, "
                "measured_90d FROM opportunity_outcomes "
                "WHERE human_decision = 'approved' ORDER BY implemented_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        except Exception:
            return []
        out = []
        for r in rows:
            baseline = self._json(r[5]) or {}
            recorded = bool(r[7] or r[8] or r[9])
            out.append({
                "keyword": r[0], "opportunity_type": r[1], "url": r[2],
                "implemented_action": r[3] or "", "implemented_at": r[4],
                "baseline": baseline,
                "verdict": r[6],
                "windows": {"28d": bool(r[7]), "56d": bool(r[8]), "90d": bool(r[9])},
                "measurement_state": self._measurement_state(r[6], recorded),
            })
        return out

    @staticmethod
    def _measurement_state(verdict: str | None, recorded: bool) -> str:
        if verdict:
            return "measured"
        if recorded:
            return "measuring"
        return "waiting_data"

    # -- Caixa de Trabalho ---------------------------------------------------
    def work_items(self, *, source: str | None = None, status: str | None = None,
                   limit: int = 200) -> list[dict[str, Any]]:
        return self.opportunities.feed(source=source, status=status, limit=limit)

    ACTION_EVENTS = {"approved": "OPPORTUNITY_APPROVED", "rejected": "OPPORTUNITY_REJECTED",
                     "snoozed": "OPPORTUNITY_SNOOZED"}

    def update_work_item_status(self, item_id: str, status: str, *, actor: str = "",
                                reason: str = "") -> dict[str, Any] | None:
        """Aplica uma decisão humana (approved/rejected/snoozed) a um work item.

        Mapeia o id `source:key` para a tabela de origem e usa as transições
        existentes (backlog usa transition_backlog com eventos; checklist usa
        mark_checklist_done). Sempre registra o evento de auditoria.
        """
        event = self.ACTION_EVENTS.get(status)
        if event is None:
            raise ValueError(f"status inválido para work item: {status!r}")
        source, _, key = item_id.partition(":")
        if not key or not key.isdigit():
            return None
        key_id = int(key)
        done = False
        if source == "checklist":
            if status == "approved":
                done = self.storage.mark_checklist_done(key_id)
            else:
                done = self._update_simple("improvement_checklist", key_id, status, reason)
        elif source == "content_brief":
            done = self._update_simple("content_briefs", key_id, status, reason)
        elif source == "interlink":
            done = self._update_simple("interlink_suggestions", key_id, status, reason)
        elif source == "backlog":
            allowed = {"approved", "rejected", "snoozed"}
            if status in allowed:
                done = self.storage.transition_backlog(key_id, status, reason=reason)
        if not done:
            return None
        self.storage.log_audit(actor or "system", event, item_id,
                               {"status": status}, {"status": status, "reason": reason})
        return {"id": item_id, "source": source, "status": status}

    def _update_simple(self, table: str, row_id: int, status: str, reason: str) -> bool:
        cur = self.storage.conn.execute(
            f"UPDATE {table} SET status = ? WHERE id = ?", (status, row_id)
        )
        self.storage.conn.commit()
        return cur.rowcount > 0

    # -- Hoje ----------------------------------------------------------------
    def today(self, *, limit: int = 10) -> dict[str, Any]:
        items = self.opportunities.feed(limit=200)
        needs_attention = [i for i in items if i["status"] in _REVIEW_STATUS]
        top = sorted([i for i in items if i["score"] is not None],
                     key=lambda o: -o["score"])[:limit]
        if not top:
            top = items[:limit]

        try:
            integrations = [s.to_dict() for s in
                            IntegrationStatusService(self.config, self.storage).check()]
        except Exception:
            integrations = []
        warnings = [s for s in integrations if s["data_status"] != "available"]

        return {
            "needs_attention": len(needs_attention),
            "critical_findings": self._count_findings(),
            "safe_fixes": self._count_pending_actions(),
            "organic_summary": self._organic_summary(),
            "recent_runs": self.runs.list_runs(limit=5),
            "top_opportunities": top,
            "integration_warnings": warnings,
        }

    # -- Fontes de dados ------------------------------------------------------
    def integrations(self, *, live: bool = False) -> list[dict[str, Any]]:
        return [s.to_dict() for s in
                IntegrationStatusService(self.config, self.storage).check(live=live)]

    # -- Atividade / auditoria ----------------------------------------------
    def activity(self, *, limit: int = 50) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for r in self.runs.list_runs(limit=limit):
            entries.append({
                "ts": r.get("finished_at") or r.get("started_at") or "",
                "actor": r.get("started_by") or "system",
                "type": "agent_run",
                "event": f"AGENT_RUN_{r['status'].upper()}",
                "summary": f"{r.get('agent', '')} {r['status']} ({r.get('intent') or '-'})",
                "ref": r["id"],
            })
        try:
            from ..auth.service import AuthService
            auth = AuthService(self.storage, config=self.config)
            for e in auth.store.list_events(limit=limit):
                entries.append({
                    "ts": e["ts"], "actor": e["actor"] or "system",
                    "type": "auth", "event": e["event"],
                    "summary": e["event"], "ref": e["id"],
                })
        except Exception:
            pass
        try:
            for r in self.storage.conn.execute(
                "SELECT ts, actor, action_type, entity FROM audit_log ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall():
                entries.append({
                    "ts": r[0], "actor": r[1] or "system", "type": "audit",
                    "event": r[2], "summary": f"{r[2]} {r[3] or ''}", "ref": r[3] or "",
                })
        except Exception:
            pass
        entries.sort(key=lambda e: e["ts"], reverse=True)
        return entries[:limit]

    # -- helpers -------------------------------------------------------------
    def _count_findings(self) -> int:
        try:
            row = self.storage.conn.execute(
                "SELECT COUNT(*) FROM findings WHERE severity IN ('high','critical')"
            ).fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    def _count_pending_actions(self) -> int:
        try:
            row = self.storage.conn.execute(
                "SELECT COUNT(*) FROM actions WHERE level = 'safe_fix' AND status = 'pending'"
            ).fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    def _organic_summary(self) -> dict[str, Any] | None:
        try:
            row = self.storage.conn.execute(
                "SELECT SUM(clicks), SUM(impressions), AVG(position), COUNT(*) "
                "FROM query_pages WHERE window_start = "
                "(SELECT MAX(window_start) FROM query_pages)"
            ).fetchone()
            if not row or not row[3]:
                return None
            ws = self.storage.conn.execute(
                "SELECT MAX(window_start) FROM query_pages"
            ).fetchone()
            return {
                "window_start": ws[0] if ws else "",
                "clicks": row[0] or 0,
                "impressions": row[1] or 0,
                "avg_position": round(row[2], 1) if row[2] is not None else None,
                "pages": row[3],
            }
        except Exception:
            return None
