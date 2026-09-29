"""Sprint 2 — lanes independentes: filas com claim/lease/fencing + política.

Uso:

    from hermes_seo_agent.lanes import LaneQueue, lanes

    q = LaneQueue(store)
    q.enqueue(lanes.LANE_TITLE_EXECUTION, payload=decision, url=url)
    for item in q.claim(lanes.LANE_TITLE_EXECUTION, worker_id="w1", limit=10):
        ...
        q.complete(item["work_item_id"], "w1", item["lease_version"])

`LaneQueue` opera sobre o mesmo `Storage` (mesmo SQLite/transação) — a fila é a
camada de trabalho; `work_item_lifecycle` continua sendo o estado canônico.
"""
from hermes_seo_agent.lanes import policy as lanes
from hermes_seo_agent.lanes.policy import (  # noqa: F401  (reexport de conveniência)
    ALL_LANES, DEFAULT_LANE_LIMITS, LANE_AUDIT, LANE_DEAD_URL, LANE_MEASUREMENT,
    LANE_TECHNICAL, LANE_TITLE_DECISION, LANE_TITLE_EXECUTION,
    backoff_seconds, classify_error, lane_limit, normalize_limit, work_item_key,
)
from hermes_seo_agent.lanes.queue import MAX_RECOVERIES, LaneQueue  # noqa: F401

__all__ = [
    "lanes", "LaneQueue", "MAX_RECOVERIES",
    "ALL_LANES", "DEFAULT_LANE_LIMITS", "LANE_AUDIT", "LANE_DEAD_URL",
    "LANE_MEASUREMENT", "LANE_TECHNICAL", "LANE_TITLE_DECISION",
    "LANE_TITLE_EXECUTION", "backoff_seconds", "classify_error", "lane_limit",
    "work_item_key",
]
