"""Tests for Phase 5 tools: wayback, schema, screaming frog, wse, notify."""

import json

import httpx
import pytest

from hermes_seo_agent.checks.schema import extract_json_ld, validate_schema
from hermes_seo_agent.config import Config
from hermes_seo_agent.connectors.base import HttpClient
from hermes_seo_agent.connectors.static_site import PageSnapshot
from hermes_seo_agent.connectors.wayback import WaybackClient
from hermes_seo_agent.report.notify import Notifier
from hermes_seo_agent.tools.screaming_frog import import_crawl_csv, summary
from hermes_seo_agent.tools.wse_trigger import WseError, WseTrigger


def _config(dry_run=True) -> Config:
    return Config(wordpress_url="http://localhost", dry_run=dry_run)


# -- Wayback ----------------------------------------------------------------

def test_wayback_availability_archived(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "archived_snapshots": {"closest": {
                "url": "http://web.archive.org/web/20260101/https://x.com/a/",
                "timestamp": "20260101000000", "status": "200"}}
        })

    client = WaybackClient(_config(), http=HttpClient(transport=httpx.MockTransport(handler)))
    result = client.availability("https://x.com/a/")
    assert result["archived"] is True
    assert "web.archive.org" in result["snapshot_url"]


def test_wayback_availability_never_archived():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"archived_snapshots": {}})

    client = WaybackClient(_config(), http=HttpClient(transport=httpx.MockTransport(handler)))
    result = client.availability("https://x.com/new/")
    assert result["archived"] is False
    assert result["snapshot_url"] is None


def test_wayback_snapshot_count():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[["timestamp"], ["20260101"], ["20260102"]])

    client = WaybackClient(_config(), http=HttpClient(transport=httpx.MockTransport(handler)))
    assert client.snapshot_count("https://x.com/a/") == 2


# -- Schema validation ------------------------------------------------------

def test_extract_json_ld():
    html = ('<script type="application/ld+json">{"@type":"Article","headline":"X"}</script>'
            '<script type="application/ld+json">[{"@type":"FAQPage","mainEntity":[]}]</script>')
    blocks = extract_json_ld(html)
    assert len(blocks) == 2


def test_validate_schema_missing_fields():
    page = PageSnapshot("https://x.com/a/", 200)
    page.html = '<script type="application/ld+json">{"@type":"Article","headline":"X"}</script>'
    page.title = "X"
    findings = validate_schema(page)
    rules = {f["rule_id"] for f in findings}
    assert "structured_data_invalid" in rules  # missing author/datePublished
    assert "structured_data_missing" not in rules


def test_validate_schema_missing_entirely():
    page = PageSnapshot("https://x.com/a/", 200)
    page.html = "<html><body>no schema</body></html>"
    page.title = "A page"
    findings = validate_schema(page)
    assert findings[0]["rule_id"] == "structured_data_missing"


# -- Screaming Frog CSV -----------------------------------------------------

def test_import_crawl_csv(tmp_path):
    csv_path = tmp_path / "crawl.csv"
    csv_path.write_text(
        "Address,Status Code,Title 1\n"
        "https://x.com/a/,200,Title A\n"
        "https://x.com/b/,404,Title B\n"
        "https://x.com/c/,500,\n",
        encoding="utf-8-sig",
    )
    rows = import_crawl_csv(csv_path)
    assert len(rows) == 3
    assert rows[0]["status_code"] == 200
    summ = summary(rows)
    assert summ["urls"] == 3
    assert summ["not_found_404"] == 1
    assert summ["errors_5xx"] == 1


def test_import_crawl_csv_missing_address(tmp_path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("Name\nfoo\n")
    with pytest.raises(ValueError):
        import_crawl_csv(csv_path)


# -- WP Static Engine trigger -----------------------------------------------

def test_wse_dry_run_does_not_execute(monkeypatch):
    trigger = WseTrigger(_config(dry_run=True))
    outcome = trigger.cdn_purge("https://x.com/a/")
    assert outcome["executed"] is False
    assert "dry-run" in outcome["note"]


def test_wse_missing_wp_cli(monkeypatch):
    monkeypatch.setattr("hermes_seo_agent.tools.wse_trigger.shutil.which", lambda name: None)
    trigger = WseTrigger(_config(dry_run=False))
    with pytest.raises(WseError):
        trigger.rebuild("smart")


def test_wse_invalid_kind():
    trigger = WseTrigger(_config(dry_run=True))
    with pytest.raises(WseError):
        trigger.rebuild("nope")


def test_wse_executes_command(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        import subprocess
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

    monkeypatch.setattr("hermes_seo_agent.tools.wse_trigger.shutil.which", lambda name: "/usr/bin/wp")
    monkeypatch.setattr("hermes_seo_agent.tools.wse_trigger.subprocess.run", fake_run)
    trigger = WseTrigger(_config(dry_run=False))
    outcome = trigger.rebuild("smart")
    assert outcome["executed"] is True
    assert calls[0][1:] == ["wse", "rebuild", "smart"]


# -- Notifier ---------------------------------------------------------------

def test_notifier_threshold_not_reached():
    http = HttpClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(500, text="should not be called")))
    notifier = Notifier("https://hooks.example/x", http=http)
    assert notifier.maybe_alert(findings=[{"severity": "high"}] * 2, high_threshold=10) is False


def test_notifier_sends_when_threshold_crossed():
    received = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    notifier = Notifier("https://hooks.example/x", http=HttpClient(transport=httpx.MockTransport(handler)))
    sent = notifier.maybe_alert(
        findings=[{"severity": "high"}] * 8 + [{"severity": "critical"}] * 3,
        high_threshold=10,
    )
    assert sent is True
    assert received["body"]["summary"]["critical"] == 3
    assert received["body"]["summary"]["high"] == 8
