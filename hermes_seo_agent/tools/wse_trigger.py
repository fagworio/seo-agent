"""WP Static Engine triggers (Phase 5) — use what already exists.

The WordPress plugin `wp-static-engine` already exposes `wp wse cdn purge` and
`wp wse rebuild {smart|full}`. This tool shells out to wp-cli instead of
reimplementing purge/rebuild — dry-run blocks the actual command.
"""

from __future__ import annotations

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
        result = self.status()
        if not result.get("executed"):
            return "unknown"
        raw = str(result.get("stdout") or "")
        try:
            import json
            payload = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            return "unknown"
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
