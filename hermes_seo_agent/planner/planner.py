"""Planner: turn findings into a bounded action plan.

Enforces the blast-radius invariant: at most ``max_safe_fix`` safe actions per
cycle. `approval_required` is a review queue, never an execution queue.
"""

from __future__ import annotations

from typing import Any

from ..rules.registry import get_rule


def build_action_plan(
    findings: list[dict[str, Any]],
    *,
    max_safe_fix: int = 10,
) -> dict[str, list[dict[str, Any]]]:
    safe_actions: list[dict[str, Any]] = []
    approval_required: list[dict[str, Any]] = []

    for finding in findings:
        rule = get_rule(finding.get("rule_id", ""))
        level = rule.level if rule else "observe"
        action = {
            "rule_id": finding.get("rule_id"),
            "url": finding.get("url", ""),
            "severity": finding.get("severity", rule.severity if rule else "info"),
            "detail": finding.get("detail", ""),
            "suggested_action": rule.suggested_action if rule else "review",
        }
        if level == "safe_fix":
            safe_actions.append(action)
        elif level == "approval_required":
            approval_required.append(action)
        # observe-level rules are reported but never queued for execution

    # Blast radius: cap safe actions per cycle.
    if len(safe_actions) > max_safe_fix:
        safe_actions = safe_actions[:max_safe_fix]

    return {
        "safe_actions": safe_actions,
        "approval_required": approval_required,
    }
