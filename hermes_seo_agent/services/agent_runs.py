"""AgentRunService: ciclo de vida da execução de agente (ADR-0007).

Estados: queued | running | success | partial | failed | cancelled.
Cada run registra trigger (schedule|manual|system), comando lógico (não flags
CLI), modo (analyze|safe_fix), quem iniciou, duração, contagens e o delta vs a
execução comparável anterior. Nenhuma credencial é registrada.
"""

from __future__ import annotations

import datetime
from typing import Any

from ..storage.agent_store import AgentStore

TERMINAL_STATES = {"success", "partial", "failed", "cancelled"}
ACTIVE_STATES = {"queued", "running"}


class AgentRunError(Exception):
    pass


class AgentRunService:
    def __init__(self, storage: Any, *, clock: Any | None = None) -> None:
        self.store = AgentStore(storage)
        self._clock = clock

    def _now(self) -> str:
        if self._clock:
            return self._clock().isoformat()
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    # -- lifecycle -----------------------------------------------------------
    def register_agent(self, name: str, description: str = "") -> int:
        return self.store.register_agent(name, description, now=self._now())

    def start_run(
        self,
        agent: str,
        *,
        trigger: str = "manual",
        intent: str | None = None,
        mode: str | None = None,
        started_by: str | None = None,
        description: str = "",
    ) -> int:
        if trigger not in {"schedule", "manual", "system"}:
            raise AgentRunError(f"trigger inválida: {trigger}")
        if mode not in {None, "analyze", "safe_fix"}:
            raise AgentRunError(f"mode inválido: {mode}")
        agent_id = self.register_agent(agent, description)
        run_id = self.store.create_run(
            agent_id=agent_id, status="running", trigger=trigger,
            intent=intent, mode=mode, started_by=started_by, now=self._now(),
        )
        self.store.add_event(run_id, now=self._now(), event="RUN_STARTED",
                             level="info", message=f"execução iniciada ({trigger})")
        return run_id

    def queue_run(
        self,
        agent: str,
        *,
        intent: str | None = None,
        mode: str | None = None,
        started_by: str | None = None,
        description: str = "",
    ) -> int:
        """Persist a human request for a worker to execute.

        The control plane must not pretend that creating a row has executed
        Hermes.  A worker claims this queued run and transitions it to running.
        """
        if mode not in {None, "analyze", "safe_fix"}:
            raise AgentRunError(f"mode inválido: {mode}")
        agent_id = self.register_agent(agent, description)
        run_id = self.store.create_run(
            agent_id=agent_id, status="queued", trigger="manual",
            intent=intent, mode=mode, started_by=started_by, now=self._now(),
        )
        self.store.add_event(run_id, now=self._now(), event="RUN_QUEUED",
                             level="info", message="execução solicitada; aguardando worker")
        return run_id

    def claim_queued_run(self, agent: str, *, intent: str | None = None) -> int | None:
        run = self.store.claim_queued_run(agent=agent, intent=intent)
        if run is None:
            return None
        self.store.add_event(run["id"], now=self._now(), event="RUN_STARTED",
                             level="info", message="execução iniciada pelo worker")
        return int(run["id"])

    def log(self, run_id: int, event: str, *, level: str = "info",
            message: str | None = None, detail: dict | None = None) -> None:
        self.store.add_event(run_id, now=self._now(), event=event, level=level,
                             message=message, detail=detail)

    def mark_step(self, run_id: int, stage: str, status: str, *, detail: dict | None = None) -> None:
        self.store.upsert_step(run_id, stage, status=status, now=self._now(), detail=detail)
        self.store.add_event(run_id, now=self._now(), event=f"STEP:{stage}",
                             level="info", message=f"etapa {stage}: {status}")

    def complete(
        self,
        run_id: int,
        *,
        status: str = "success",
        summary: dict | None = None,
        urls: int | None = None,
        findings: int | None = None,
        opportunities: int | None = None,
        safe_fixes: int | None = None,
        executed: int | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        if status not in TERMINAL_STATES:
            raise AgentRunError(f"status inválido: {status}")
        run = self.store.get_run(run_id)
        if run is None:
            raise AgentRunError(f"run inexistente: {run_id}")
        started = run["started_at"]
        duration_ms = self._duration_ms(started, self._now()) if started else None
        comparison = self._compare_prior(
            run_id, run, urls=urls, findings=findings, opportunities=opportunities,
            safe_fixes=safe_fixes, executed=executed,
        )
        self.store.update_run_status(
            run_id, status=status, finished_at=self._now(), duration_ms=duration_ms,
            summary=summary, comparison=comparison, urls=urls, findings=findings,
            opportunities=opportunities, safe_fixes=safe_fixes, executed=executed,
            error=error,
        )
        self.store.add_event(run_id, now=self._now(), event="RUN_COMPLETED",
                             level="info" if status == "success" else "warning",
                             message=f"execução {status}")
        return self.store.get_run(run_id)

    def fail(self, run_id: int, error: str, *, summary: dict | None = None) -> dict[str, Any]:
        return self.complete(run_id, status="failed", error=error, summary=summary)

    def cancel(self, run_id: int) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            raise AgentRunError(f"run inexistente: {run_id}")
        if run["status"] in TERMINAL_STATES:
            return run
        return self.complete(run_id, status="cancelled")

    # -- queries -------------------------------------------------------------
    def get_run(self, run_id: int) -> dict[str, Any] | None:
        run = self.store.get_run(run_id)
        if run is None:
            return None
        run["steps"] = self.store.list_steps(run_id)
        run["events"] = self.store.list_events(run_id)
        return run

    def list_runs(self, *, agent: str | None = None, status: str | None = None,
                  limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self.store.list_runs(agent=agent, status=status, limit=limit, offset=offset)

    def running_runs(self) -> list[dict[str, Any]]:
        return self.store.list_runs(limit=50)

    def list_agents(self) -> list[dict[str, Any]]:
        return self.store.list_agents()

    def _compare_prior(self, run_id: int, run: dict[str, Any], *, urls: int | None,
                       findings: int | None, opportunities: int | None,
                       safe_fixes: int | None, executed: int | None) -> dict[str, Any] | None:
        prior = self.store.latest_completed_comparable(
            run["agent_id"], run["intent"], before_run_id=run_id
        )
        if prior is None:
            return None
        return {
            "prior_run_id": prior["id"],
            "urls_analyzed_delta": self._delta(urls or 0, prior.get("urls_analyzed", 0)),
            "findings_delta": self._delta(findings or 0, prior.get("findings_count", 0)),
            "opportunities_delta": self._delta(
                opportunities or 0, prior.get("opportunities_count", 0)),
            "safe_fixes_delta": self._delta(
                safe_fixes or 0, prior.get("safe_fixes_count", 0)),
            "executed_delta": self._delta(
                executed or 0, prior.get("executed_changes_count", 0)),
        }

    @staticmethod
    def _delta(current: int, prior: int) -> int:
        return (current or 0) - (prior or 0)

    @staticmethod
    def _duration_ms(started: str | None, finished: str) -> int | None:
        if not started:
            return None
        try:
            return int(round(
                (datetime.datetime.fromisoformat(finished)
                 - datetime.datetime.fromisoformat(started)).total_seconds() * 1000
            ))
        except (ValueError, TypeError):
            return None
