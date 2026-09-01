"""Per-page history: before/after diffs, improvement detection (Phase 6).

Reliable local tracking of what changed on each page over time, so the agent
(and humans) can verify that SEO evolutions produced real improvements.

- ``page_history``: chronological snapshots of one URL.
- ``diff_snapshots``: field-level before -> after diff between two states,
  including CWV (improved/worsened) and GSC signal deltas.
- ``summarize_page``: one-page digest for the agent (JSON-friendly).
- ``aggregate_trends``: whole-site trends across cycles.
"""

from __future__ import annotations

from typing import Any

from ..storage.db import Storage

_TEXT_FIELDS = ("title", "meta_description", "canonical", "meta_robots", "h1")
_CWV_METRICS = ("lcp", "cls", "inp")
_GSC_METRICS = ("impressions", "clicks", "ctr")


def page_history(storage: Storage, url: str, *, limit: int = 50) -> list[dict[str, Any]]:
    return storage.page_snapshots(url, limit=limit)


def diff_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Field-level before -> after between two snapshots of the same URL.

    Returns:
      changed: [{field, before, after}]        (text/status changes)
      content_changed: bool                    (html hash differs)
      cwv: {improved: [{metric, before, after}], worsened: [...]}
      gsc: {delta_impressions, delta_clicks}
    """
    changed: list[dict[str, str]] = []
    for field in _TEXT_FIELDS:
        b = (before.get(field) or "").strip()
        a = (after.get(field) or "").strip()
        if b != a:
            changed.append({"field": field, "before": b, "after": a})

    if before.get("status_code") != after.get("status_code"):
        changed.append({
            "field": "status_code",
            "before": str(before.get("status_code")),
            "after": str(after.get("status_code")),
        })
    if before.get("word_count") != after.get("word_count"):
        changed.append({
            "field": "word_count",
            "before": str(before.get("word_count")),
            "after": str(after.get("word_count")),
        })

    content_changed = bool(
        before.get("content_hash") and after.get("content_hash")
        and before["content_hash"] != after["content_hash"]
    )

    cwv_before = before.get("cwv") or {}
    cwv_after = after.get("cwv") or {}
    cwv_improved: list[dict[str, Any]] = []
    cwv_worsened: list[dict[str, Any]] = []
    for metric in _CWV_METRICS:
        b = cwv_before.get(metric)
        a = cwv_after.get(metric)
        if b is None or a is None or b == a:
            continue
        (cwv_worsened if a > b else cwv_improved).append(
            {"metric": metric, "before": b, "after": a}
        )

    gsc_before = before.get("gsc") or {}
    gsc_after = after.get("gsc") or {}

    return {
        "changed": changed,
        "content_changed": content_changed,
        "cwv": {"improved": cwv_improved, "worsened": cwv_worsened},
        "gsc": {
            "delta_impressions": _delta(gsc_before, gsc_after, "impressions"),
            "delta_clicks": _delta(gsc_before, gsc_after, "clicks"),
        },
    }


def summarize_page(storage: Storage, url: str, *, limit: int = 50) -> dict[str, Any]:
    """One-page digest: timeline + consecutive diffs + SEO expectation."""
    snapshots = page_history(storage, url, limit=limit)
    expectations = storage.expectations_for(url, limit=5)

    if not snapshots:
        return {"url": url, "snapshots": 0, "timeline": [], "expectations": expectations}

    timeline: list[dict[str, Any]] = []
    for index, snap in enumerate(snapshots):
        entry = {
            "captured_at": snap["captured_at"],
            "source": snap["source"],
            "linked_action": snap["linked_action"],
            "status_code": snap["status_code"],
            "title": snap["title"],
            "cwv": snap.get("cwv") or {},
            "gsc": snap.get("gsc") or {},
        }
        if index > 0:
            entry["diff"] = diff_snapshots(snapshots[index - 1], snap)
        timeline.append(entry)

    return {
        "url": url,
        "snapshots": len(snapshots),
        "timeline": timeline,
        "expectations": expectations,
    }


def aggregate_trends(storage: Storage, *, limit_cycles: int = 10) -> dict[str, Any]:
    """Site-wide trends: findings per cycle, CWV evolution, actions executed."""
    cycles = [
        row[0]
        for row in storage.conn.execute(
            "SELECT id FROM cycles ORDER BY started_at DESC LIMIT ?", (limit_cycles,)
        ).fetchall()
    ]

    findings_by_cycle: list[dict[str, Any]] = []
    for cycle_id in cycles:
        rows = storage.conn.execute(
            "SELECT rule_id, severity, COUNT(*) FROM findings "
            "WHERE cycle_id = ? GROUP BY rule_id, severity ORDER BY 3 DESC",
            (cycle_id,),
        ).fetchall()
        findings_by_cycle.append(
            {
                "cycle_id": cycle_id,
                "total": sum(r[2] for r in rows),
                "by_rule": {r[0]: r[2] for r in rows},
            }
        )

    actions = dict(storage.conn.execute(
        "SELECT rule_id, COUNT(*) FROM actions WHERE status = 'executed' "
        "GROUP BY rule_id ORDER BY 2 DESC"
    ).fetchall())

    # CWV trend across the whole site: latest vs previous snapshot per URL.
    improved: dict[str, int] = {}
    worsened: dict[str, int] = {}
    urls = [r[0] for r in storage.conn.execute(
        "SELECT DISTINCT url FROM page_snapshots WHERE cwv_json IS NOT NULL"
    ).fetchall()]
    for url in urls:
        snaps = storage.page_snapshots(url, limit=2)
        if len(snaps) < 2:
            continue
        diff = diff_snapshots(snaps[0], snaps[1])
        for item in diff["cwv"]["improved"]:
            improved[item["metric"]] = improved.get(item["metric"], 0) + 1
        for item in diff["cwv"]["worsened"]:
            worsened[item["metric"]] = worsened.get(item["metric"], 0) + 1

    return {
        "cycles_analyzed": len(cycles),
        "findings_by_cycle": findings_by_cycle,
        "actions_executed_by_rule": actions,
        "cwv_trend": {"improved": improved, "worsened": worsened},
        "pages_tracked": storage.distinct_snapshot_urls(),
        "snapshots_total": storage.snapshot_count(),
    }


def _delta(before: dict[str, Any], after: dict[str, Any], key: str) -> float | None:
    b = before.get(key)
    a = after.get(key)
    if b is None or a is None:
        return None
    return round(float(a) - float(b), 3)
