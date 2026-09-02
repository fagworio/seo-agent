"""Persistência de execução de agente (agents, agent_runs, steps, events).

Opera sobre a conexão do :class:`~hermes_seo_agent.storage.db.Storage` para
compartilhar a transação do SQLite. Nada de credenciais é registrado — apenas
quem iniciou, trigger, agente, comando lógico, modo, timestamps, status e
contagens (ADR-0007).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any


class AgentStore:
    def __init__(self, storage: Any) -> None:
        self.storage = storage
        self.conn: sqlite3.Connection = storage.conn

    # -- agents --------------------------------------------------------------
    def register_agent(self, name: str, description: str = "", *, now: str) -> int:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO agents (name, description, enabled, created_at) "
            "VALUES (?, ?, 1, ?)",
            (name, description, now),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT id FROM agents WHERE name = ?", (name,)).fetchone()
        return int(row[0])

    def get_agent(self, name: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, name, description, enabled, created_at FROM agents WHERE name = ?",
            (name,),
        ).fetchone()
        return self._agent_row(row)

    def list_agents(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, name, description, enabled, created_at FROM agents ORDER BY name"
        ).fetchall()
        return [self._agent_row(r) for r in rows]

    # -- runs ----------------------------------------------------------------
    def create_run(
        self,
        *,
        agent_id: int,
        status: str,
        trigger: str,
        intent: str | None,
        mode: str | None,
        started_by: str | None,
        now: str,
        target_url: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO agent_runs (agent_id, status, trigger, intent, mode, "
            "started_by, started_at, created_at, target_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (agent_id, status, trigger, intent, mode, started_by, now, now, target_url),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT r.id, r.agent_id, a.name, r.status, r.trigger, r.intent, r.mode, "
            "r.started_by, r.started_at, r.finished_at, r.duration_ms, r.summary_json, "
            "r.comparison_json, r.urls_analyzed, r.findings_count, r.opportunities_count, "
            "r.safe_fixes_count, r.executed_changes_count, r.error, r.created_at, "
            "r.target_url "
            "FROM agent_runs r JOIN agents a ON a.id = r.agent_id WHERE r.id = ?",
            (run_id,),
        ).fetchone()
        return self._run_row(row) if row else None

    def list_runs(self, *, agent: str | None = None, status: str | None = None,
                  limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        sql = ("SELECT r.id, r.agent_id, a.name, r.status, r.trigger, r.intent, r.mode, "
               "r.started_by, r.started_at, r.finished_at, r.duration_ms, r.summary_json, "
               "r.comparison_json, r.urls_analyzed, r.findings_count, r.opportunities_count, "
               "r.safe_fixes_count, r.executed_changes_count, r.error, r.created_at, "
               "r.target_url "
               "FROM agent_runs r JOIN agents a ON a.id = r.agent_id WHERE 1=1")
        params: list[Any] = []
        if agent:
            sql += " AND a.name = ?"
            params.append(agent)
        if status:
            sql += " AND r.status = ?"
            params.append(status)
        sql += " ORDER BY r.id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = self.conn.execute(sql, params).fetchall()
        return [self._run_row(r) for r in rows]

    def count_runs(self, *, agent: str | None = None, status: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM agent_runs r JOIN agents a ON a.id = r.agent_id WHERE 1=1"
        params: list[Any] = []
        if agent:
            sql += " AND a.name = ?"
            params.append(agent)
        if status:
            sql += " AND r.status = ?"
            params.append(status)
        row = self.conn.execute(sql, params).fetchone()
        return row[0] if row else 0

    def latest_completed_comparable(self, agent_id: int, intent: str | None,
                                    *, before_run_id: int | None = None) -> dict[str, Any] | None:
        sql = ("SELECT id FROM agent_runs WHERE agent_id = ? AND status IN "
               "('success','partial','failed') AND finished_at IS NOT NULL")
        params: list[Any] = [agent_id]
        if intent:
            sql += " AND intent = ?"
            params.append(intent)
        if before_run_id is not None:
            sql += " AND id < ?"
            params.append(before_run_id)
        sql += " ORDER BY id DESC LIMIT 1"
        row = self.conn.execute(sql, params).fetchone()
        return self.get_run(row[0]) if row else None

    def set_run_started(self, run_id: int) -> None:
        self.conn.execute("UPDATE agent_runs SET status = 'running' WHERE id = ? AND status = 'queued'", (run_id,))
        self.conn.commit()

    def claim_queued_run(self, *, agent: str, intent: str | None) -> dict[str, Any] | None:
        """Claim the oldest compatible manual request for the scheduler.

        SQLite's immediate transaction prevents two workers from claiming the
        same request.
        """
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            sql = ("SELECT r.id FROM agent_runs r JOIN agents a ON a.id = r.agent_id "
                   "WHERE r.status = 'queued' AND r.trigger = 'manual' AND a.name = ?")
            params: list[Any] = [agent]
            if intent:
                sql += " AND r.intent = ?"
                params.append(intent)
            sql += " ORDER BY r.id LIMIT 1"
            row = self.conn.execute(sql, params).fetchone()
            if not row:
                self.conn.commit()
                return None
            self.conn.execute("UPDATE agent_runs SET status = 'running' WHERE id = ?", (row[0],))
            self.conn.commit()
            return self.get_run(int(row[0]))
        except Exception:
            self.conn.rollback()
            raise

    def update_run_status(self, run_id: int, *, status: str, finished_at: str | None = None,
                          duration_ms: int | None = None, summary: dict | None = None,
                          comparison: dict | None = None, urls: int | None = None,
                          findings: int | None = None, opportunities: int | None = None,
                          safe_fixes: int | None = None, executed: int | None = None,
                          error: str | None = None) -> None:
        fields = ["status = ?"]
        params: list[Any] = [status]
        for col, val in (
            ("finished_at", finished_at), ("duration_ms", duration_ms),
            ("urls_analyzed", urls), ("findings_count", findings),
            ("opportunities_count", opportunities), ("safe_fixes_count", safe_fixes),
            ("executed_changes_count", executed), ("error", error),
        ):
            if val is not None:
                fields.append(f"{col} = ?")
                params.append(val)
        if summary is not None:
            fields.append("summary_json = ?")
            params.append(json.dumps(summary, ensure_ascii=False))
        if comparison is not None:
            fields.append("comparison_json = ?")
            params.append(json.dumps(comparison, ensure_ascii=False))
        params.append(run_id)
        self.conn.execute(f"UPDATE agent_runs SET {', '.join(fields)} WHERE id = ?", params)
        self.conn.commit()

    # -- steps ---------------------------------------------------------------
    def upsert_step(self, run_id: int, stage: str, *, status: str, now: str,
                    detail: dict | None = None) -> None:
        row = self.conn.execute(
            "SELECT id, started_at FROM agent_run_steps WHERE run_id = ? AND stage = ?",
            (run_id, stage),
        ).fetchone()
        if row:
            duration = 0
            if row[1] and status == "success":
                try:
                    from datetime import datetime
                    duration = int(round(
                        (datetime.fromisoformat(now) - datetime.fromisoformat(row[1])).total_seconds() * 1000
                    ))
                except Exception:
                    duration = 0
            self.conn.execute(
                "UPDATE agent_run_steps SET status = ?, finished_at = ?, duration_ms = ? "
                "WHERE run_id = ? AND stage = ?",
                (status, now, duration, run_id, stage),
            )
        else:
            self.conn.execute(
                "INSERT INTO agent_run_steps (run_id, stage, status, started_at) "
                "VALUES (?, ?, ?, ?)",
                (run_id, stage, status, now),
            )
        if detail is not None:
            self.conn.execute(
                "UPDATE agent_run_steps SET detail_json = ? WHERE run_id = ? AND stage = ?",
                (json.dumps(detail, ensure_ascii=False), run_id, stage),
            )
        self.conn.commit()

    def list_steps(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, run_id, stage, status, started_at, finished_at, duration_ms, detail_json "
            "FROM agent_run_steps WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        return [self._step_row(r) for r in rows]

    # -- events --------------------------------------------------------------
    def add_event(self, run_id: int, *, now: str, event: str, level: str = "info",
                  message: str | None = None, detail: dict | None = None) -> None:
        self.conn.execute(
            "INSERT INTO agent_run_events (run_id, ts, event, level, message, detail_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, now, event, level, message,
             json.dumps(detail, ensure_ascii=False) if detail else None),
        )
        self.conn.commit()

    def list_events(self, run_id: int, *, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, ts, event, level, message, detail_json FROM agent_run_events "
            "WHERE run_id = ? ORDER BY id LIMIT ?",
            (run_id, limit),
        ).fetchall()
        out = []
        for r in rows:
            detail = None
            if r[5]:
                try:
                    detail = json.loads(r[5])
                except Exception:
                    detail = None
            out.append({"id": r[0], "ts": r[1], "event": r[2], "level": r[3],
                        "message": r[4], "detail": detail})
        return out

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _agent_row(row: tuple | None) -> dict[str, Any] | None:
        if not row:
            return None
        return {"id": row[0], "name": row[1], "description": row[2],
                "enabled": bool(row[3]), "created_at": row[4]}

    @staticmethod
    def _run_row(row: tuple | None) -> dict[str, Any] | None:
        if not row:
            return None
        return {
            "id": row[0], "agent_id": row[1], "agent": row[2], "status": row[3],
            "trigger": row[4], "intent": row[5], "mode": row[6], "started_by": row[7],
            "started_at": row[8], "finished_at": row[9], "duration_ms": row[10],
            "summary": json.loads(row[11]) if row[11] else None,
            "comparison": json.loads(row[12]) if row[12] else None,
            "urls_analyzed": row[13], "findings_count": row[14],
            "opportunities_count": row[15], "safe_fixes_count": row[16],
            "executed_changes_count": row[17], "error": row[18], "created_at": row[19],
            "target_url": row[20] if len(row) > 20 else None,
        }

    @staticmethod
    def _step_row(row: tuple | None) -> dict[str, Any] | None:
        if not row:
            return None
        detail = None
        if row[7]:
            try:
                detail = json.loads(row[7])
            except Exception:
                detail = None
        return {"id": row[0], "run_id": row[1], "stage": row[2], "status": row[3],
                "started_at": row[4], "finished_at": row[5], "duration_ms": row[6],
                "detail": detail}
