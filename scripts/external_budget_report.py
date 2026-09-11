#!/usr/bin/env python3
"""Calibra MAX_EXTERNAL_CALLS a partir da telemetria REAL dos ciclos.

Lê os agent_runs recentes, extrai summary.telemetry e agrupa por INTENT e STATUS.
Runs `partial`/`failed` são EXCLUÍDOS do cálculo do teto: eles podem ter parado
cedo e apresentar artificialmente poucas chamadas. Misturar todos os intents numa
única distribuição (ex.: 95 ciclos leves + 5 deep pesados) produziria um p95 perto
dos leves e abortaria o deep. Por isso a sugestão é:

    MAX_EXTERNAL_CALLS = ceil( max(p95 por intent, só sucessos) * margem )

Como o ExecutionBudget MEDE mesmo com MAX_EXTERNAL_CALLS=0 (sem bloquear), rode
por alguns dias e use este relatório para escolher o teto.

Roda: .venv/bin/python scripts/external_budget_report.py [--days 14] [--limit 500] [--margin 1.25]
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hermes_seo_agent.config import load_config  # noqa: E402
from hermes_seo_agent.storage.db import Storage  # noqa: E402

_SUCCESS = "success"


def _arg(name: str, default: float) -> float:
    if name in sys.argv:
        return float(sys.argv[sys.argv.index(name) + 1])
    return default


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(pct / 100 * len(ordered)) - 1))
    return ordered[idx]


def _group_stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"runs": 0}
    return {
        "runs": len(values),
        "min": int(min(values)),
        "median": int(statistics.median(values)),
        "p95": int(_percentile(values, 95)),
        "max": int(max(values)),
    }


def main() -> int:
    days = int(_arg("--days", 14))
    limit = int(_arg("--limit", 500))
    margin = float(_arg("--margin", 1.25))
    cfg = load_config()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # (intent, status) -> [calls]
    by_intent_status: dict[tuple[str, str], list[float]] = {}
    avoided = total_bytes = total_retries = 0
    with Storage(cfg.sqlite_path) as storage:
        rows = storage.conn.execute(
            "SELECT intent, status, summary_json FROM agent_runs "
            "WHERE COALESCE(finished_at, started_at) >= ? "
            "ORDER BY id DESC LIMIT ?", (cutoff, limit)).fetchall()

    for intent, status, summary_json in rows:
        try:
            summary = json.loads(summary_json) if summary_json else {}
        except json.JSONDecodeError:
            continue
        t = summary.get("telemetry") if isinstance(summary, dict) else None
        if not isinstance(t, dict):
            continue
        n = t.get("calls")
        if not isinstance(n, (int, float)):
            continue
        by_intent_status.setdefault((intent or "unknown", status or "unknown"), []).append(float(n))
        avoided += int(t.get("cache_hits") or 0)
        total_bytes += int(t.get("bytes") or 0)
        total_retries += int(t.get("retries") or 0)

    if not by_intent_status:
        print(json.dumps({
            "status": "no_data",
            "message": (f"Sem telemetria nos últimos {days} dias. Runs anteriores ao "
                        "recurso não têm summary.telemetry; rode ciclos e repita."),
            "runs_with_telemetry": 0,
        }, ensure_ascii=False, indent=2))
        return 0

    # agrupa por intent, separando sucesso de partial/failed.
    groups: dict[str, dict[str, Any]] = {}
    success_p95: dict[str, float] = {}
    for (intent, status), values in sorted(by_intent_status.items()):
        groups.setdefault(intent, {})[status] = _group_stats(values)
        if status == _SUCCESS:
            success_p95[intent] = _percentile(values, 95)

    if success_p95:
        worst_intent = max(success_p95, key=lambda k: success_p95[k])
        suggestion: int | None = int(math.ceil(success_p95[worst_intent] * margin))
        basis = {"intent": worst_intent, "p95": int(success_p95[worst_intent]),
                 "margin": margin}
    else:
        suggestion, basis = None, {"note": "nenhum run 'success' com telemetria"}

    print(json.dumps({
        "status": "ok",
        "window_days": days,
        "runs_with_telemetry": sum(len(v) for v in by_intent_status.values()),
        "excluded_from_teto": "status partial/failed (podem ter parado cedo)",
        "by_intent": groups,
        "suggested_max_external_calls": suggestion,
        "suggestion_basis": basis,
        "cache_hits_avoided": avoided,
        "bytes_total": total_bytes,
        "retries_total": total_retries,
        "note": ("Teto = p95 do intent mais pesado (só sucessos) x margem. "
                 "0 mantém apenas medição (sem bloqueio)."),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
