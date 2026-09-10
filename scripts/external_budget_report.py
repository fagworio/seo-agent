#!/usr/bin/env python3
"""Calibra MAX_EXTERNAL_CALLS a partir da telemetria REAL dos ciclos.

Lê os agent_runs recentes, extrai summary.telemetry (calls, cache_hits, bytes,
duration_s) e reporta a distribuição de chamadas externas por run + uma sugestão
de teto (p95 x margem). Como o ExecutionBudget agora MEDE mesmo com
MAX_EXTERNAL_CALLS=0 (sem bloquear), rode por alguns dias e use este relatório
para escolher o teto.

Roda: .venv/bin/python scripts/external_budget_report.py [--days 14] [--limit 500]
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hermes_seo_agent.config import load_config  # noqa: E402
from hermes_seo_agent.storage.db import Storage  # noqa: E402


def _arg(name: str, default: int) -> int:
    if name in sys.argv:
        return int(sys.argv[sys.argv.index(name) + 1])
    return default


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(pct / 100 * len(ordered)) - 1))
    return ordered[idx]


def main() -> int:
    days = _arg("--days", 14)
    limit = _arg("--limit", 500)
    cfg = load_config()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    calls: list[float] = []
    avoided = 0
    total_bytes = 0
    total_retries = 0
    with Storage(cfg.sqlite_path) as storage:
        rows = storage.conn.execute(
            "SELECT intent, status, started_at, summary_json FROM agent_runs "
            "WHERE COALESCE(finished_at, started_at) >= ? "
            "ORDER BY id DESC LIMIT ?", (cutoff, limit)).fetchall()

    for intent, status, started, summary_json in rows:
        try:
            summary = json.loads(summary_json) if summary_json else {}
        except json.JSONDecodeError:
            continue
        t = summary.get("telemetry") if isinstance(summary, dict) else None
        if not isinstance(t, dict):
            continue
        n = t.get("calls")
        if isinstance(n, (int, float)):
            calls.append(float(n))
        avoided += int(t.get("cache_hits") or 0)
        total_bytes += int(t.get("bytes") or 0)
        total_retries += int(t.get("retries") or 0)

    if not calls:
        print(json.dumps({
            "status": "no_data",
            "message": (
                f"Sem telemetria nos últimos {days} dias. Os runs anteriores ao "
                "recurso não têm summary.telemetry; rode alguns ciclos e repita."),
            "runs_with_telemetry": 0,
        }, ensure_ascii=False, indent=2))
        return 0

    p95 = _percentile(calls, 95)
    suggestion = int(math.ceil(p95 * 1.25))
    report = {
        "status": "ok",
        "window_days": days,
        "runs_with_telemetry": len(calls),
        "calls": {
            "min": int(min(calls)), "median": int(statistics.median(calls)),
            "p95": int(p95), "max": int(max(calls)),
        },
        "cache_hits_avoided": avoided,
        "bytes_total": total_bytes,
        "retries_total": total_retries,
        "suggested_max_external_calls": suggestion,
        "note": (
            "Sugestão = p95 x 1.25. Defina MAX_EXTERNAL_CALLS no .env com folga "
            "para o pior ciclo observado; 0 mantém só medição (sem bloqueio)."),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
