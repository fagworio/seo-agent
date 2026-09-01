"""Alert notifier (Phase 5) — configurable webhook, threshold-gated.

Deterministic: fires only when the high/critical finding count crosses the
threshold. Uses a generic webhook URL (Slack/Telegram/n8n style); no LLM.
"""

from __future__ import annotations

from typing import Any

from ..connectors.base import HttpClient


class Notifier:
    def __init__(self, webhook_url: str, http: HttpClient | None = None):
        self.webhook_url = webhook_url
        self.http = http or HttpClient(timeout=10)

    def maybe_alert(
        self,
        *,
        findings: list[dict[str, Any]],
        high_threshold: int = 10,
        title: str = "SEO Agent",
    ) -> bool:
        """Send an alert when high/critical findings exceed the threshold."""
        critical = sum(1 for f in findings if f.get("severity") == "critical")
        high = sum(1 for f in findings if f.get("severity") == "high")
        if critical + high < high_threshold:
            return False
        payload = {
            "text": f"[{title}] {critical} critical / {high} high findings "
                    f"(threshold {high_threshold})",
            "summary": {
                "critical": critical,
                "high": high,
                "total_findings": len(findings),
            },
        }
        response = self.http.post(self.webhook_url, json_body=payload)
        return response.status_code in {200, 201, 202, 204}
