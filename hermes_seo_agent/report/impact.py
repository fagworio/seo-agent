"""Impact measurement — before/after deltas from Google data (Phase 6).

Given a page's GSC metrics for a before window and an after window, compute
how much it improved/worsened (clicks, impressions, CTR, position) and a
verdict. Pure and testable; the CLI wires it to Search Console.
"""

from __future__ import annotations

from typing import Any

_METRICS = ("clicks", "impressions", "ctr", "position")


def impact_deltas(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Absolute and relative deltas between two GSC metric windows."""
    deltas: dict[str, Any] = {}
    for key in _METRICS:
        b = before.get(key)
        a = after.get(key)
        if b is None or a is None:
            deltas[f"{key}_delta"] = None
            deltas[f"{key}_pct"] = None
            continue
        b, a = float(b), float(a)
        deltas[f"{key}_delta"] = round(a - b, 2)
        deltas[f"{key}_pct"] = round(((a - b) / b * 100), 1) if b else None
    deltas["verdict"] = verdict(deltas)
    return deltas


def verdict(d: dict[str, Any]) -> str:
    """Classify a before/after change.

    Lower position = better; more clicks = better; more impressions = better.
    """
    clicks = d.get("clicks_delta")
    impressions = d.get("impressions_delta")
    position = d.get("position_delta")

    improved = False
    worsened = False
    if clicks is not None:
        improved |= clicks > 0
        worsened |= clicks < 0
    if impressions is not None:
        improved |= impressions > 0
        worsened |= impressions < 0
    if position is not None:
        improved |= position < -0.5   # moved up
        worsened |= position > 0.5    # moved down

    if improved and not worsened:
        return "improved"
    if worsened and not improved:
        return "worsened"
    if improved and worsened:
        return "mixed"
    return "neutral"


def aggregate_impact(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate verdicts + total deltas across many pages."""
    counts = {"improved": 0, "worsened": 0, "mixed": 0, "neutral": 0, "unknown": 0}
    total_clicks = 0.0
    total_impressions = 0.0
    measured = 0
    for item in items:
        verdict = item.get("verdict", "unknown")
        counts[verdict] = counts.get(verdict, 0) + 1
        clicks = item.get("clicks_delta")
        impressions = item.get("impressions_delta")
        if clicks is not None:
            total_clicks += clicks
            measured += 1
        if impressions is not None:
            total_impressions += impressions
    return {
        "pages_measured": measured,
        "verdict_counts": counts,
        "total_clicks_delta": round(total_clicks, 1),
        "total_impressions_delta": round(total_impressions, 1),
    }
