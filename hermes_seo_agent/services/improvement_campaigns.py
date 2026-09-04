"""B0 — ImprovementCampaignService: campanha de melhorias (trabalho que dura
várias execuções de AgentRun).

Uma campanha agrupa correções aprovadas e homogêneas (ex.: só títulos) e as
entrega ao Hermes em lotes de até max_actions_per_run, reaproveitando o executor
`apply_safe_actions` (fingerprint/idempotência/before/after/rollback/dry-run).
Nada aqui escreve no site — a escrita é do executor (B5), sob as mesmas guardas.
"""

from __future__ import annotations

import datetime
import json
from typing import Any

from ..storage.db import Storage

# Estados da campanha (B0).
DRAFT = "draft"
REVIEW_REQUIRED = "review_required"
APPROVED = "approved"
QUEUED = "queued"
RUNNING = "running"
PARTIAL = "partial"
COMPLETED = "completed"
MEASURING = "measuring"
MEASURED = "measured"
PAUSED = "paused"
CANCELLED = "cancelled"
FAILED = "failed"

CAMPAIGN_STATES = (
    DRAFT, REVIEW_REQUIRED, APPROVED, QUEUED, RUNNING, PARTIAL, COMPLETED,
    MEASURING, MEASURED, PAUSED, CANCELLED, FAILED,
)

# Status por item.
ITEM_PENDING = "pending"
ITEM_EXECUTED = "executed"
ITEM_FAILED = "failed"
ITEM_STALE = "stale"
ITEM_SKIPPED = "skipped"


def forward_fix(after: dict[str, Any], rollback: dict[str, Any]) -> dict[str, Any] | None:
    """Reconstrói o fix FORWARD a partir de rollback + after.

    O actions persiste before/after/rollback, mas o executor precisa do fix
    forward. Para os tipos suportados, ele é determinístico:
      wp_post_meta : meta = {chave: after[chave]}, post_id do rollback.
      wp_media_alt : alt_text = after[alt_text], media_id do rollback.
    """
    t = rollback.get("type")
    if t == "wp_post_meta":
        meta = {k: after.get(k) for k in (rollback.get("meta") or {})}
        if not meta:
            return None
        return {"type": "wp_post_meta", "post_id": rollback.get("post_id"), "meta": meta}
    if t == "wp_media_alt":
        return {"type": "wp_media_alt", "media_id": rollback.get("media_id"),
                "alt_text": after.get("alt_text", "")}
    return None


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class ImprovementCampaignService:
    def __init__(self, storage: Storage, config: Any | None = None):
        self.storage = storage
        self.conn = storage.conn
        self.config = config

    # -- criação -------------------------------------------------------------
    def create(
        self,
        name: str,
        action_type: str,
        fingerprints: list[str],
        *,
        created_by: str = "",
        max_actions_per_run: int = 10,
        execution_mode: str = "delegated",
        schedule_policy: str | None = None,
    ) -> dict[str, Any] | None:
        """Cria uma campanha a partir de ações safe_fix aprovadas (por fingerprint).

        - Homogênea: todas as ações devem ter o MESMO rule_id == action_type.
        - Itens copiam before/after e reconstroem o fix forward (para o runner).
        """
        if not fingerprints:
            return None
        items = []
        for fp in fingerprints:
            row = self.conn.execute(
                "SELECT rule_id, url, before_json, after_json, rollback_json, fix_json, status "
                "FROM actions WHERE fingerprint = ?", (fp,)
            ).fetchone()
            if row is None:
                return None  # fingerprint desconhecida
            if row[0] != action_type:
                return None  # lote não-homogêneo
            before = json.loads(row[2]) if row[2] else {}
            after = json.loads(row[3]) if row[3] else {}
            rollback = json.loads(row[4]) if row[4] else {}
            # Se a ação persistiu o fix forward completo (ex.: wp_post_content_patch),
            # usa-o; senão reconstrói a partir de rollback+after.
            fix = json.loads(row[5]) if row[5] else forward_fix(after, rollback)
            if fix is None:
                return None  # sem fix forward suportado
            items.append({
                "action_fingerprint": fp, "url": row[1], "action_type": action_type,
                "before": before, "after": after, "fix": fix,
            })
        if not items:
            return None

        now = _now()
        cur = self.conn.execute(
            "INSERT INTO improvement_campaigns (name, action_type, status, created_by, "
            "execution_mode, schedule_policy, max_actions_per_run, total_items, "
            "pending_items, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, action_type, DRAFT, created_by, execution_mode, schedule_policy,
             max_actions_per_run, len(items), len(items), now),
        )
        campaign_id = int(cur.lastrowid)
        for it in items:
            self.conn.execute(
                "INSERT INTO improvement_campaign_items (campaign_id, action_fingerprint, "
                "url, action_type, before_json, after_json, fix_json, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (campaign_id, it["action_fingerprint"], it["url"], it["action_type"],
                 json.dumps(it["before"], ensure_ascii=False, default=str),
                 json.dumps(it["after"], ensure_ascii=False, default=str),
                 json.dumps(it["fix"], ensure_ascii=False, default=str),
                 ITEM_PENDING),
            )
        self.conn.commit()
        self.storage.log_audit(created_by or "system", "CAMPAIGN_CREATED", f"campaign:{campaign_id}",
                               {}, {"name": name, "action_type": action_type, "total": len(items)})
        return self.get(campaign_id)

    # -- leitura -------------------------------------------------------------
    def preview(self, fingerprints: list[str], *, max_actions_per_run: int = 10) -> dict[str, Any]:
        """B1 — valida a seleção antes de criar a campanha.

        Retorna elegíveis (homogêneos, com fix suportado e não-executados),
        incompatíveis, ausentes, risco, reversibilidade e quantidade por ciclo.
        """
        eligible: list[dict[str, Any]] = []
        incompatible: list[dict[str, Any]] = []
        missing: list[str] = []
        for fp in fingerprints:
            row = self.conn.execute(
                "SELECT rule_id, url, before_json, after_json, rollback_json, fix_json, status "
                "FROM actions WHERE fingerprint = ?", (fp,)).fetchone()
            if row is None:
                missing.append(fp)
                continue
            rule_id, url, before_j, after_j, rollback_j = row[0], row[1], row[2], row[3], row[4]
            fix_j, status = row[5], row[6]
            before = json.loads(before_j) if before_j else {}
            after = json.loads(after_j) if after_j else {}
            rollback = json.loads(rollback_j) if rollback_j else {}
            fix = json.loads(fix_j) if fix_j else forward_fix(after, rollback)
            if fix is None:
                incompatible.append({"fingerprint": fp, "reason": "sem fix suportado"})
                continue
            if status in ("executed", "reverted"):
                incompatible.append({"fingerprint": fp, "reason": f"status {status}"})
                continue
            eligible.append({
                "fingerprint": fp, "rule_id": rule_id, "url": url,
                "before": before, "after": after,
                "risk": self._risk(rule_id), "reversible": True,
            })
        action_types = {e["rule_id"] for e in eligible}
        homogeneous = len(action_types) == 1
        return {
            "eligible": eligible,
            "incompatible": incompatible,
            "missing": missing,
            "action_type": next(iter(action_types)) if homogeneous else None,
            "homogeneous": homogeneous,
            "per_cycle": min(len(eligible), max_actions_per_run) if homogeneous else 0,
            "max_actions_per_run": max_actions_per_run,
        }

    @staticmethod
    def _risk(rule_id: str) -> str:
        if rule_id in ("title_manual", "title_opportunity", "image_no_alt"):
            return "low"
        if rule_id in ("internal_link", "interlink"):
            return "review_required"   # B10: links internos exigem revisão humana
        return "review_required"

    def list_campaigns(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT id, name, action_type, status, created_by, approved_by, execution_mode, " \
              "schedule_policy, max_actions_per_run, total_items, pending_items, executed_items, " \
              "failed_items, stale_items, created_at, approved_at, started_at, finished_at, " \
              "last_run_id, next_run_at FROM improvement_campaigns WHERE 1=1"
        params: list[Any] = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [self._campaign_row(r) for r in self.conn.execute(sql, params).fetchall()]

    def get(self, campaign_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, name, action_type, status, created_by, approved_by, execution_mode, "
            "schedule_policy, max_actions_per_run, total_items, pending_items, executed_items, "
            "failed_items, stale_items, created_at, approved_at, started_at, finished_at, "
            "last_run_id, next_run_at FROM improvement_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if row is None:
            return None
        out = self._campaign_row(row)
        out["items"] = self._list_items(campaign_id)
        return out

    def _list_items(self, campaign_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, work_item_id, action_fingerprint, url, action_type, before_json, "
            "after_json, fix_json, status, failure_reason, executed_run_id, executed_at, "
            "verified_at FROM improvement_campaign_items WHERE campaign_id = ? ORDER BY id",
            (campaign_id,),
        ).fetchall()
        out = []
        for r in rows:
            out.append({
                "id": r[0], "work_item_id": r[1], "action_fingerprint": r[2], "url": r[3],
                "action_type": r[4],
                "before": json.loads(r[5]) if r[5] else {},
                "after": json.loads(r[6]) if r[6] else {},
                "fix": json.loads(r[7]) if r[7] else {},
                "status": r[8], "failure_reason": r[9], "executed_run_id": r[10],
                "executed_at": r[11], "verified_at": r[12],
            })
        return out

    # -- ciclo de vida -------------------------------------------------------
    def _set_status(self, campaign_id: int, status: str, **fields: Any) -> bool:
        sets = ["status = ?"]
        params: list[Any] = [status]
        for k, v in fields.items():
            if v is not None:
                sets.append(f"{k} = ?")
                params.append(v)
        params.append(campaign_id)
        cur = self.conn.execute(
            f"UPDATE improvement_campaigns SET {', '.join(sets)} WHERE id = ?", params)
        self.conn.commit()
        return cur.rowcount > 0

    def approve(self, campaign_id: int, *, approved_by: str = "") -> bool:
        if not self._set_status(campaign_id, APPROVED, approved_by=approved_by,
                                approved_at=_now()):
            return False
        self.storage.log_audit(approved_by or "system", "CAMPAIGN_APPROVED",
                               f"campaign:{campaign_id}", {"status": DRAFT}, {"status": APPROVED})
        return True

    def pause(self, campaign_id: int, *, actor: str = "") -> bool:
        return self._set_status(campaign_id, PAUSED)

    def resume(self, campaign_id: int, *, actor: str = "") -> bool:
        return self._set_status(campaign_id, APPROVED, next_run_at=_now())

    def cancel(self, campaign_id: int, *, actor: str = "") -> bool:
        ok = self._set_status(campaign_id, CANCELLED, finished_at=_now())
        if ok:
            self.storage.log_audit(actor or "system", "CAMPAIGN_CANCELLED",
                                   f"campaign:{campaign_id}", {}, {"status": CANCELLED})
        return ok

    def schedule(self, campaign_id: int, *, policy: str, next_run_at: str | None = None) -> bool:
        return self._set_status(campaign_id, QUEUED, schedule_policy=policy,
                                next_run_at=next_run_at or _now())

    # -- B5: runner ----------------------------------------------------------
    def run(self, campaign_id: int, *, actor: str = "system",
            apply: Any | None = None) -> dict[str, Any] | None:
        """Executa o próximo lote (até max_actions_per_run) reutilizando o executor.

        Cria um AgentRun (intent=improvement_campaign, mode=safe_fix) e aplica as
        ações via `apply_safe_actions` (o MESMO motor do cron). `apply` é injetável
        para testes: callable(actions) -> {executed, skipped, previewed, unverified}.
        """
        from ..services.agent_runs import AgentRunService

        camp = self.get(campaign_id)
        if camp is None or camp["status"] not in (DRAFT, REVIEW_REQUIRED, APPROVED, QUEUED, RUNNING, PARTIAL):
            return None
        pending = [it for it in camp["items"] if it["status"] == ITEM_PENDING][:camp["max_actions_per_run"]]
        if not pending:
            self._set_status(campaign_id, COMPLETED, finished_at=_now())
            self.storage.log_audit(actor, "CAMPAIGN_COMPLETED", f"campaign:{campaign_id}",
                                   {}, {"status": COMPLETED})
            return self.get(campaign_id)

        self._set_status(campaign_id, RUNNING, started_at=camp["started_at"] or _now())
        svc = AgentRunService(self.storage)
        run_id = svc.start_run("hermes-seo-agent", trigger="manual", intent="improvement_campaign",
                               mode="safe_fix", started_by=actor)
        self._set_status(campaign_id, RUNNING, last_run_id=run_id)

        actions = [{
            "rule_id": it["action_type"], "url": it["url"],
            "detail": it["action_type"], "fix": it["fix"],
            "_campaign_fp": it["action_fingerprint"],
        } for it in pending]

        if apply is None:
            from ..connectors.wordpress import WordPressClient
            from ..executor.executor import Executor
            with WordPressClient(self.config) as wp:
                executor = Executor(self.config, wp, self.storage)
                outcome = executor.apply_safe_actions(
                    actions, cycle_id=f"campaign-{campaign_id}",
                    max_actions=camp["max_actions_per_run"], verify=None)
        else:
            outcome = apply(actions)

        executed = {a.get("_campaign_fp") for a in outcome.get("executed", [])}
        unverified = {a.get("_campaign_fp") for a in outcome.get("unverified", [])}
        previewed = {a.get("_campaign_fp") for a in outcome.get("previewed", [])}
        skipped = {a.get("_campaign_fp"): a.get("reason", "") for a in outcome.get("skipped", [])}

        executed_n = failed_n = skipped_n = 0
        for it in pending:
            fp = it["action_fingerprint"]
            if fp in executed:
                self._set_item_status(it["id"], ITEM_EXECUTED, run_id=run_id)
                executed_n += 1
                # B8 — vincula ao pipeline de revalidação (baseline before/after).
                after_vals = list((it.get("after") or {}).values())
                self.storage.record_implemented_outcome(
                    url=it["url"], action_type=it["action_type"],
                    implemented_action=after_vals[0] if after_vals else it["action_type"],
                    before=it.get("before") or {}, after=it.get("after") or {},
                    implemented_at=_now())
            elif fp in unverified:
                self._set_item_status(it["id"], ITEM_FAILED, run_id=run_id,
                                      reason="confirmação REST pós-write falhou")
                failed_n += 1
            elif fp in previewed:
                self._set_item_status(it["id"], ITEM_SKIPPED, run_id=run_id,
                                      reason="dry-run: não executado")
                skipped_n += 1
            elif fp in skipped:
                self._set_item_status(it["id"], ITEM_SKIPPED, run_id=run_id, reason=skipped[fp])
                skipped_n += 1
            else:
                self._set_item_status(it["id"], ITEM_FAILED, run_id=run_id,
                                      reason="sem resultado do executor")
                failed_n += 1

        self._recount(campaign_id)
        camp2 = self.get(campaign_id)
        remaining = camp2["pending_items"]
        if remaining == 0:
            new_status = PARTIAL if failed_n else COMPLETED
        else:
            new_status = PARTIAL if failed_n else QUEUED
        self._set_status(campaign_id, new_status)

        svc.mark_step(run_id, "campaign_batch", "success" if failed_n == 0 else "partial",
                      detail={"executed": executed_n, "failed": failed_n,
                              "skipped": skipped_n, "remaining": remaining})
        svc.complete(run_id, status="success" if failed_n == 0 else "partial",
                     urls=executed_n, safe_fixes=executed_n, executed=executed_n)
        return self.get(campaign_id)

    def _set_item_status(self, item_id: int, status: str, *, run_id: int | None = None,
                         reason: str = "") -> None:
        self.conn.execute(
            "UPDATE improvement_campaign_items SET status = ?, failure_reason = ?, "
            "executed_run_id = ?, executed_at = ?, verified_at = ? WHERE id = ?",
            (status, reason or "", run_id,
             _now() if status == ITEM_EXECUTED else None,
             _now() if status == ITEM_EXECUTED else None, item_id))
        self.conn.commit()

    def _recount(self, campaign_id: int) -> None:
        counts = {r[0]: r[1] for r in self.conn.execute(
            "SELECT status, COUNT(*) FROM improvement_campaign_items WHERE campaign_id = ? "
            "GROUP BY status", (campaign_id,)).fetchall()}
        self.conn.execute(
            "UPDATE improvement_campaigns SET pending_items = ?, executed_items = ?, "
            "failed_items = ?, stale_items = ? WHERE id = ?",
            (counts.get(ITEM_PENDING, 0), counts.get(ITEM_EXECUTED, 0),
             counts.get(ITEM_FAILED, 0), counts.get(ITEM_STALE, 0), campaign_id))
        self.conn.commit()

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _campaign_row(r: tuple) -> dict[str, Any]:
        return {
            "id": r[0], "name": r[1], "action_type": r[2], "status": r[3],
            "created_by": r[4], "approved_by": r[5], "execution_mode": r[6],
            "schedule_policy": r[7], "max_actions_per_run": r[8],
            "total_items": r[9], "pending_items": r[10], "executed_items": r[11],
            "failed_items": r[12], "stale_items": r[13], "created_at": r[14],
            "approved_at": r[15], "started_at": r[16], "finished_at": r[17],
            "last_run_id": r[18], "next_run_at": r[19],
        }
