"""WP Static Engine triggers (Phase 5) — use what already exists.

The WordPress plugin `wp-static-engine` already exposes `wp wse cdn purge` and
`wp wse rebuild {smart|full}`. This tool shells out to wp-cli instead of
reimplementing purge/rebuild — dry-run blocks the actual command.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..config import Config


class WseError(RuntimeError):
    """Raised when wp-cli is missing or the command fails."""


class WsePreflightError(WseError):
    """Falha comprovada antes de qualquer chamada ao WSE."""


class WseTrigger:
    def __init__(self, config: Config, *, wp_cli: str | None = None,
                 workdir: str | None = None):
        self.config = config
        self.wp_cli = wp_cli or str(getattr(config, "wse_wp_cli", "wp") or "wp")
        self.workdir = (workdir if workdir is not None else
                        str(getattr(config, "wse_workdir", "") or ""))

    def cdn_purge(self, url: str) -> dict[str, Any]:
        """Purge a URL (or '/'-all) from the Cloudflare CDN via wp wse."""
        if self.config.dry_run:
            return {"action": "cdn_purge", "url": url, "executed": False,
                    "note": "dry-run: purge skipped"}
        return self._run(["wse", "cdn", "purge", "--purge-url=" + url])

    def rebuild(self, kind: str = "smart") -> dict[str, Any]:
        """Trigger a static-site rebuild (smart|full|flush)."""
        if kind not in {"smart", "full", "flush"}:
            raise WseError(f"kind must be smart|full|flush, got {kind!r}")
        if self.config.dry_run:
            return {"action": "rebuild", "kind": kind, "executed": False,
                    "note": "dry-run: rebuild skipped"}
        return self._run(["wse", "rebuild", kind])

    def status(self) -> dict[str, Any]:
        return self._run(["wse", "status", "--format=json"])

    def rebuild_state(self) -> str:
        """Classifica o estado do WSE para reconciliar uma chamada incerta.

        O plugin pode variar os nomes dos campos; estados não reconhecidos
        permanecem ``unknown`` para que o caller não reenvie uma solicitação
        potencialmente duplicada.
        """
        return str(self.rebuild_info().get("state") or "unknown")

    def rebuild_info(self) -> dict[str, Any]:
        """Return the WSE state and operation identity, when exposed.

        The WSE plugin has changed the nesting of its JSON responses between
        versions. We therefore inspect only well-known status/id fields and
        keep an unknown result conservative: callers must not issue a second
        rebuild when they cannot prove which operation is active.
        """
        result = self.status()
        if not result.get("executed"):
            return {"state": "unknown", "operation_id": None, "raw": None}
        raw = str(result.get("stdout") or "")
        try:
            payload = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            return {"state": "unknown", "operation_id": None, "raw": None}
        operations = self._operation_records(payload)
        return {
            "state": (operations[0]["state"] if len(operations) == 1
                       else (self._classify_payload(payload)
                             if not operations else "unknown")),
            "operation_id": (operations[0]["operation_id"]
                             if len(operations) == 1 else None),
            "operations": operations,
            "raw": payload,
        }

    @classmethod
    def _classify_values(cls, values: list[str]) -> str:
        text = " ".join(values)
        if any(token in text for token in
               ("running", "pending", "queued", "building", "in_progress")):
            return "active"
        if any(token in text for token in
               ("complete", "completed", "success", "succeeded", "done")):
            return "complete"
        if any(token in text for token in ("idle", "failed", "failure", "error")):
            return "idle"
        return "unknown"

    @classmethod
    def _classify_payload(cls, payload: Any) -> str:
        values: list[str] = []
        stack = [payload]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                for key, value in current.items():
                    if key.lower() in {"status", "state", "phase", "rebuild_status",
                                       "job_status"}:
                        values.append(str(value).strip().lower())
                    elif isinstance(value, (dict, list)):
                        stack.append(value)
            elif isinstance(current, list):
                stack.extend(current)
        return cls._classify_values(values)

    @classmethod
    def _operation_records(cls, payload: Any) -> list[dict[str, Any]]:
        keys = {"operation_id", "operationid", "job_id", "jobid", "request_id",
                "requestid", "rebuild_id", "rebuildid"}
        status_keys = {"status", "state", "phase", "rebuild_status", "job_status"}
        stack = [(payload, None)]
        records: list[dict[str, Any]] = []
        while stack:
            current, scope = stack.pop()
            if isinstance(current, dict):
                operation_id: str | None = None
                states: list[str] = []
                for key, value in current.items():
                    normalized = str(key).lower().replace("-", "_")
                    scoped_id = normalized == "id" and scope in {
                        "job", "jobs", "operation", "operations", "rebuild",
                        "rebuilds", "request", "requests"}
                    if (normalized in keys or scoped_id) and value not in (None, ""):
                        operation_id = str(value)
                    if normalized in status_keys:
                        states.append(str(value).strip().lower())
                    if isinstance(value, (dict, list)):
                        stack.append((value, normalized))
                if operation_id:
                    records.append({"operation_id": operation_id,
                                    "state": cls._classify_values(states),
                                    "raw": current})
            elif isinstance(current, list):
                stack.extend((value, scope) for value in current)
        unique: dict[str, dict[str, Any]] = {}
        for record in records:
            unique.setdefault(record["operation_id"], record)
        return list(unique.values())

    @classmethod
    def _extract_operation_id(cls, payload: Any) -> str | None:
        records = cls._operation_records(payload)
        return records[0]["operation_id"] if len(records) == 1 else None

    @classmethod
    def extract_operation_id(cls, result: dict[str, Any]) -> str | None:
        """Extract an operation id from a successful ``rebuild`` response."""
        raw = str(result.get("stdout") or "")
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return cls._extract_operation_id(payload)

    def _run(self, args: list[str]) -> dict[str, Any]:
        if not self.workdir:
            raise WsePreflightError("WSE_WORKDIR não configurado")
        workdir = Path(self.workdir).expanduser()
        if not workdir.is_dir():
            raise WsePreflightError(f"WSE_WORKDIR não é diretório: {workdir}")
        if not shutil.which(self.wp_cli):
            raise WsePreflightError(f"wp-cli ({self.wp_cli}) not found on PATH")
        try:
            proc = subprocess.run(
                [self.wp_cli, *args],
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise WseError(f"wp wse timed out: {exc}") from exc
        return {
            "action": args[1],
            "executed": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip()[-2000:],
            "stderr": proc.stderr.strip()[-2000:],
        }
