"""WP Static Engine triggers (Phase 5) — use what already exists.

The WordPress plugin `wp-static-engine` already exposes `wp wse cdn purge` and
`wp wse rebuild {smart|full}`. This tool shells out to wp-cli instead of
reimplementing purge/rebuild — dry-run blocks the actual command.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from ..config import Config


class WseError(RuntimeError):
    """Raised when wp-cli is missing or the command fails."""


class WseTrigger:
    def __init__(self, config: Config, *, wp_cli: str = "wp", workdir: str = "."):
        self.config = config
        self.wp_cli = wp_cli
        self.workdir = workdir

    def cdn_purge(self, url: str) -> dict[str, Any]:
        """Purge a URL (or '/'-all) from the Cloudflare CDN via wp wse."""
        if self.config.dry_run:
            return {"action": "cdn_purge", "url": url, "executed": False,
                    "note": "dry-run: purge skipped"}
        return self._run(["wse", "cdn", "purge", "--url=" + url])

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

    def _run(self, args: list[str]) -> dict[str, Any]:
        if not shutil.which(self.wp_cli):
            raise WseError(f"wp-cli ({self.wp_cli}) not found on PATH")
        try:
            proc = subprocess.run(
                [self.wp_cli, *args],
                cwd=self.workdir,
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
