"""Markdown report renderer (human-readable, mirrors the JSON contract)."""

from __future__ import annotations

import datetime
from typing import Any

_SEVERITY_EMOJI = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🟢",
    "info": "⚪",
}


def render_markdown(
    result: dict[str, Any],
    *,
    title: str = "SEO Audit Report",
) -> str:
    summary = result.get("summary", {})
    findings = result.get("findings", [])
    safe_actions = result.get("safe_actions", [])
    approval_required = result.get("approval_required", [])

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"_Generated {datetime.datetime.now(datetime.timezone.utc).isoformat()} UTC_")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|---|---|")
    for key in sorted(summary):
        lines.append(f"| {key} | {summary[key]} |")
    lines.append("")
    lines.append(f"**Findings:** {len(findings)} · **Safe actions:** {len(safe_actions)} · "
                 f"**Require approval:** {len(approval_required)}")
    lines.append("")

    _render_findings(lines, findings)
    _render_actions(lines, "Approval required (review queue — never auto-executed)",
                    approval_required)
    _render_actions(lines, "Safe actions (low-risk, idempotent)", safe_actions)

    return "\n".join(lines) + "\n"


def _render_findings(lines: list[str], findings: list[dict[str, Any]]) -> None:
    if not findings:
        return
    lines.append("## Findings")
    lines.append("")
    by_severity: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        by_severity.setdefault(f.get("severity", "info"), []).append(f)
    for severity in ("critical", "high", "medium", "low", "info"):
        group = by_severity.get(severity)
        if not group:
            continue
        lines.append(f"### {_SEVERITY_EMOJI.get(severity, '')} {severity.capitalize()}")
        lines.append("")
        lines.append("| Rule | URL | Detail |")
        lines.append("|---|---|---|")
        for f in group:
            url = f.get("url", "")
            detail = (f.get("detail") or "").replace("|", "\\|")
            lines.append(f"| `{f.get('rule_id', '')}` | `{url}` | {detail} |")
        lines.append("")


def _render_actions(lines: list[str], heading: str, actions: list[dict[str, Any]]) -> None:
    if not actions:
        return
    lines.append(f"## {heading}")
    lines.append("")
    lines.append("| Rule | URL | Suggested action |")
    lines.append("|---|---|---|")
    for a in actions:
        url = a.get("url", "")
        lines.append(f"| `{a.get('rule_id', '')}` | `{url}` | {a.get('suggested_action', '')} |")
    lines.append("")
