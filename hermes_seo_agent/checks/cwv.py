"""Core Web Vitals checks — deterministic thresholds (Phase 3).

Field data (CrUX) is authoritative when available; PageSpeed is lab data.
Only the numeric comparison is made here — no judgment, no LLM.
"""

from __future__ import annotations

from typing import Any

# Google thresholds (2024+): LCP <= 2.5s, CLS <= 0.1, INP <= 200ms
THRESHOLDS = {"lcp": 2.5, "cls": 0.1, "inp": 200}
# INP is in ms; LCP/CLS in seconds — normalize keys.
_RULE_BY_METRIC = {"lcp": "cwv_lcp_poor", "cls": "cwv_cls_poor", "inp": "cwv_inp_poor"}


def cwv_findings(url: str, values: dict[str, float]) -> list[dict[str, Any]]:
    """Compare CrUX/PSI values against thresholds; return findings.

    Canonical units: LCP seconds, CLS unitless, INP milliseconds (both
    connectors normalize to these).
    """
    findings: list[dict[str, Any]] = []
    for metric, value in values.items():
        threshold = THRESHOLDS.get(metric)
        rule_id = _RULE_BY_METRIC.get(metric)
        if threshold is None or rule_id is None:
            continue
        if value > threshold:
            unit = "ms" if metric == "inp" else "s"
            findings.append(
                {
                    "rule_id": rule_id,
                    "url": url,
                    "severity": "medium",
                    "detail": f"{metric.upper()} = {value:.3f}{unit} "
                              f"(threshold {threshold:.1f}{unit})",
                }
            )
    return findings
