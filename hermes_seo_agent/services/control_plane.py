"""Control plane read models (framework-agnóstico, pronto p/ FastAPI).

Compose os services existentes (OpportunityFeedService, IntegrationStatusService,
AgentRunService) em DTOs de PRODUTO — não comandos CLI — para as telas
Hoje, Caixa de Trabalho, Fontes de dados e Atividade. A UI nunca lê SQLite
nem Markdown diretamente; consome estes contratos.

Sem escrita: apenas projeções determinísticas sobre o Storage.
"""

from __future__ import annotations

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
