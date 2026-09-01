"""Hermes SEO Agent CLI — Phase 1 (deterministic core).

Commands:
  inventory     Three-way reconciliation (WP vs static sitemap vs static pages)
  audit         Inventory + deterministic checks on a bounded URL sample
  report        Audit + Markdown report (also persists a cycle snapshot)
  cycle         Recommended Hermes entry point: inventory + audit + report
  diff-sitemap  Deterministic set diff between two URL lists/sitemaps

Output contract (stdout JSON): {status, summary, findings, safe_actions,
approval_required}. `--dry-run` is the default posture; no writes happen
unless DRY_RUN=false in .env AND the executor exists (Phase 4).
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import uuid
from datetime import date, timedelta
from typing import Any

from .checks import meta as meta_check
from .checks import robots as robots_check
from .checks.cwv import cwv_findings
from .checks.http import check_http
from .config import ConfigError, load_config
from .connectors.analytics import AnalyticsClient
from .connectors.base import ConnectorError
from .connectors.crux import CruxClient
from .connectors.pagespeed import PageSpeedClient
from .connectors.search_console import SearchConsoleClient
from .connectors.static_site import StaticSiteClient
from .connectors.wordpress import WordPressClient
from .executor.executor import Executor
from .inventory.reconcile import normalize_url, reconcile, wp_link_to_static
from .planner.planner import build_action_plan
from .queue.inspection import build_queue_entries, remaining_budget
from .report.markdown import render_markdown
from .rules.registry import get_rule
from .storage.db import Storage
from .tools.sitemap_diff import sitemap_diff

_OUTPUT_CONTRACT = ("status", "summary", "findings", "safe_actions", "approval_required")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0

    try:
        config = load_config()
    except ConfigError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2

    try:
        return args.func(args, config)
    except Exception as exc:  # any failure -> machine-readable error frame
        print(json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False))
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-seo-agent", description="Autonomous SEO audit")
    sub = parser.add_subparsers(dest="command")

    for name, help_text in (
        ("inventory", "Three-way URL reconciliation"),
        ("audit", "Inventory + deterministic checks"),
        ("report", "Audit + Markdown report + cycle snapshot"),
        ("cycle", "inventory + audit + report (Hermes entry point)"),
        ("inspect", "Build + drain the URL Inspection queue (GSC)"),
        ("opportunities", "Search Analytics + Core Web Vitals opportunities"),
        ("apply", "Execute safe_fix actions (dry-run by default)"),
        ("wayback", "Archive evidence for a URL (Wayback Machine)"),
        ("validate-schema", "Validate JSON-LD structured data on a page"),
        ("import-crawl", "Import a Screaming Frog CSV crawl export"),
        ("wse", "Trigger WP Static Engine actions (cdn purge / rebuild / status)"),
        ("telemetry", "Observability summary from the SQLite state"),
        ("schedule", "Run the right phase by time-of-day (watchdog)"),
        ("snapshot", "Capture a page state snapshot (local history)"),
        ("history", "Per-page before/after history"),
        ("trends", "Site-wide trends across cycles"),
        ("title-opportunities", "Research top queries -> title candidates (GSC)"),
        ("impact", "Measure before/after SEO impact (GSC)"),
        ("set-title", "Set a post's SEO title directly (rank_math_title)"),
        ("reindex-status", "Google position + last crawl (reindexation) per page"),
        ("expectations", "Deterministic CTR/click improvement projection per page"),
        ("post-audit", "Post improvement analysis: suggestions + gains + checklist"),
        ("checklist", "View/manage the improvement checklist (pending/done)"),
        ("link-graph", "E0: internal link graph, orphans and hubs"),
        ("demand", "E1: persist query×page demand, intent and cannibalization"),
        ("content-brief", "E2: content-gap diagnosis + manual action brief per post"),
        ("editorial-backlog", "E3: generate revisable pautas (content ideas)"),
        ("interlinks", "E4: internal link suggestions (same-cluster)"),
        ("backlog", "E5: editorial workflow (list/approve/reject/publish/measure)"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--limit", type=int, default=0, help="cap URLs audited (0 = config max)")
        p.add_argument("--json", action="store_true", help="force JSON output")
        p.add_argument("--markdown", action="store_true", help="Markdown report output")
        if name == "inspect":
            p.add_argument("--budget", type=int, default=0,
                           help="URL Inspection budget for this run (0 = config daily budget)")
            p.add_argument("--dry-run", action="store_true", help="preview the queue, no API calls")
        if name == "apply":
            p.add_argument("--limit-actions", type=int, default=0,
                           help="max safe_fix actions to execute (0 = config blast radius)")
            p.add_argument("actions_file",
                           help="JSON file: list of actions with fix specs "
                                "(see executor/executor.py)")
        if name == "wayback":
            p.add_argument("url", help="URL to check for archived history")
        if name == "validate-schema":
            p.add_argument("url", help="URL to validate structured data on")
        if name == "import-crawl":
            p.add_argument("csv", help="Screaming Frog CSV export")
        if name == "wse":
            p.add_argument("action", choices=["purge", "rebuild", "status"])
            p.add_argument("target", nargs="?", default="",
                           help="purge: URL or 'all'; rebuild: smart|full|flush")
        if name == "telemetry":
            p.add_argument("--notify", action="store_true",
                           help="send webhook alert if high findings exceed threshold")
        if name == "snapshot":
            p.add_argument("url", help="URL to capture (local history)")
        if name == "history":
            p.add_argument("url", help="URL to inspect history for")
            # --limit já é adicionado pelo loop base a todos os subcomandos.
        if name == "title-opportunities":
            p.add_argument("--min-impressions", type=int, default=500,
                           help="impressions mínimas para considerar uma página")
            p.add_argument("--max-ctr", type=float, default=0.02,
                           help="CTR máximo para considerar (oportunidade de título)")
            p.add_argument("--write", action="store_true",
                           help="grava title-opportunities-fixes.json")
        if name == "impact":
            p.add_argument("--days", type=int, default=28,
                           help="janela antes/depois em dias")
            p.add_argument("--min-after-days", type=int, default=7,
                           help="dias mínimos após a mudança para medir")
        if name == "set-title":
            p.add_argument("target", help="URL ou slug do post")
            p.add_argument("title", help="novo título SEO (entre aspas)")
        if name == "reindex-status":
            p.add_argument("--url", dest="single_url", default="",
                           help="checar uma única URL (senão: páginas alteradas)")
        if name == "expectations":
            p.add_argument("--url", dest="single_url", default="",
                           help="projetar uma única URL (senão: páginas alteradas)")
        if name == "post-audit":
            p.add_argument("--min-impressions", type=int, default=50,
                           help="impressões mínimas para entrar na análise")
            p.add_argument("--write", action="store_true",
                           help="grava reports/content-improvements.md")
        if name == "checklist":
            p.add_argument("action", nargs="?", default="list",
                           choices=["list", "done", "reject", "snooze", "supersede",
                                    "pending", "measure", "rescore"],
                           help="list | done|reject|snooze|supersede|pending|measure|rescore")
            p.add_argument("item_id", nargs="?", type=int, default=None,
                           help="id do item")
            p.add_argument("--all", action="store_true", help="listar todos (não só pending)")
            p.add_argument("--reason", default="", help="motivo (reject)")
            p.add_argument("--responsible", default="", help="responsável")
            p.add_argument("--deadline", default="", help="prazo (ISO)")
            p.add_argument("--intervention-type", default="",
                           help="tipo: title_meta|expand|interlink|update")
            p.add_argument("--min-days", type=int, default=0,
                           help="janela mínima pós-implementação p/ measure")
        if name == "link-graph":
            p.add_argument("--store", action="store_true",
                           help="persistir as arestas no SQLite (internal_links)")
        if name == "demand":
            p.add_argument("--store", action="store_true",
                           help="persistir os pares query×página no SQLite")
            p.add_argument("--min-impressions", type=int, default=10,
                           help="FILTRO DE PERSISTÊNCIA: queries abaixo disso NÃO entram "
                                "em query_pages. Define a base de url_demand() usada por "
                                "rescore/content-brief (reduzir -> base mais fiel ao GSC; "
                                "0 -> todas as queries da janela)")
        if name == "content-brief":
            p.add_argument("--url", dest="single_url", default="",
                           help="gerar brief para uma URL específica")
            p.add_argument("--store", action="store_true",
                           help="persistir os briefs no SQLite (content_briefs)")
        if name == "editorial-backlog":
            p.add_argument("--write", action="store_true",
                           help="grava reports/editorial-backlog.md")
        if name == "interlinks":
            p.add_argument("--store", action="store_true",
                           help="persistir sugestões no SQLite (interlink_suggestions)")
            p.add_argument("action", nargs="?", default="generate",
                           choices=["generate", "list", "approve", "reject", "snooze",
                                    "done", "supersede"],
                           help="generate | list | approve|reject|snooze|done|supersede <id>")
            p.add_argument("item_id", nargs="?", type=int, default=None)
            p.add_argument("--reason", default="", help="motivo (reject/supersede)")
            p.add_argument("--status", default="", help="filtro no list (ex.: proposed)")
            p.add_argument("--all", action="store_true", help="listar todos")
        if name == "backlog":
            p.add_argument("action", nargs="?", default="list",
                           choices=["list", "approve", "reject", "snooze", "supersede",
                                    "expire", "publish", "measure"],
                           help="list | approve|reject|snooze|supersede|expire|publish|measure")
            p.add_argument("item_id", nargs="?", type=int, default=None)
            p.add_argument("--url", dest="published_url", default="",
                           help="URL publicada (publish)")
            p.add_argument("--status", default="proposed",
                           help="filtro de status no list (default proposed)")
            p.add_argument("--reason", default="", help="motivo (reject/supersede)")
            p.add_argument("--responsible", default="", help="responsável")
            p.add_argument("--deadline", default="", help="prazo (ISO, snooze)")
        if name == "schedule":
            p.add_argument("--inspect-hours", default="6",
                           help="comma-separated hours (local) for the daily GSC inspect")
            p.add_argument("--deep-weekday", type=int, default=1,
                           help="weekday (0=Mon..6=Sun) for the weekly deep report")
        if name in {"audit", "report", "cycle"}:
            p.set_defaults(func=_cmd_audit)
        elif name == "inspect":
            p.set_defaults(func=_cmd_inspect)
        elif name == "opportunities":
            p.set_defaults(func=_cmd_opportunities)
        elif name == "apply":
            p.set_defaults(func=_cmd_apply)
        elif name == "wayback":
            p.set_defaults(func=_cmd_wayback)
        elif name == "validate-schema":
            p.set_defaults(func=_cmd_validate_schema)
        elif name == "import-crawl":
            p.set_defaults(func=_cmd_import_crawl)
        elif name == "wse":
            p.set_defaults(func=_cmd_wse)
        elif name == "telemetry":
            p.set_defaults(func=_cmd_telemetry)
        elif name == "snapshot":
            p.set_defaults(func=_cmd_snapshot)
        elif name == "history":
            p.set_defaults(func=_cmd_history)
        elif name == "trends":
            p.set_defaults(func=_cmd_trends)
        elif name == "title-opportunities":
            p.set_defaults(func=_cmd_title_opportunities)
        elif name == "impact":
            p.set_defaults(func=_cmd_impact)
        elif name == "set-title":
            p.set_defaults(func=_cmd_set_title)
        elif name == "reindex-status":
            p.set_defaults(func=_cmd_reindex_status)
        elif name == "expectations":
            p.set_defaults(func=_cmd_expectations)
        elif name == "post-audit":
            p.set_defaults(func=_cmd_post_audit)
        elif name == "checklist":
            p.set_defaults(func=_cmd_checklist)
        elif name == "link-graph":
            p.set_defaults(func=_cmd_link_graph)
        elif name == "demand":
            p.set_defaults(func=_cmd_demand)
        elif name == "content-brief":
            p.set_defaults(func=_cmd_content_brief)
        elif name == "editorial-backlog":
            p.set_defaults(func=_cmd_editorial_backlog)
        elif name == "interlinks":
            p.set_defaults(func=_cmd_interlinks)
        elif name == "backlog":
            p.set_defaults(func=_cmd_backlog)
        elif name == "schedule":
            p.set_defaults(func=_cmd_schedule)
        else:
            p.set_defaults(func=_cmd_inventory)

    p = sub.add_parser("diff-sitemap", help="Deterministic diff between two URL lists")
    p.add_argument("url_a", help="first sitemap URL (or file:// path)")
    p.add_argument("url_b", help="second sitemap URL (or file:// path)")
    p.set_defaults(func=_cmd_diff_sitemap)

    p = sub.add_parser("reconcile", help="Alias of inventory")
    p.set_defaults(func=_cmd_inventory)

    parser.add_argument("--dry-run", action="store_true", help="no-op; safety posture (default)")
    return parser


# -- commands ---------------------------------------------------------------


def _cmd_inventory(args: argparse.Namespace, config: Any) -> int:
    with WordPressClient(config) as wp, StaticSiteClient(config) as static:
        posts = wp.list_posts(status="publish")
        sitemap_urls = static.all_sitemap_urls()
        report = reconcile(posts, sitemap_urls, static_host=_static_host(config))

    result = {
        "status": "ok",
        "summary": {"command": "inventory", **report.summary()},
        "findings": [],
        "safe_actions": [],
        "approval_required": [],
    }
    _emit(result, force_json=args.json)
    return 0


def _cmd_audit(args: argparse.Namespace, config: Any) -> int:
    limit = args.limit or config.max_urls_per_run
    started = _now()
    cycle_id = f"cycle-{uuid.uuid4().hex[:12]}"

    with WordPressClient(config) as wp, StaticSiteClient(config) as static:
        posts = wp.list_posts(status="publish")
        sitemap_urls = static.all_sitemap_urls()
        report = reconcile(posts, sitemap_urls, static_host=_static_host(config))

        # Robots first: one fetch, used by all sitemap-blocked checks.
        robots = static.fetch_robots()
        blocked = robots_check.sitemap_urls_blocked(robots, sitemap_urls)

        # Bounded deterministic audit of the sitemap sample.
        sample = sitemap_urls[:limit]
        findings: list[dict[str, Any]] = []
        pages = [static.fetch_page(url) for url in sample]

        # Local history: every analyzed page gets a snapshot (before/after basis).
        with Storage(config.sqlite_path) as snap_storage:
            for page in pages:
                _save_page_snapshot(snap_storage, page, cycle_id=cycle_id, source="audit")

        # HTTP health pass: status >= 400, redirect chains, redirect loops.
        for url in sample:
            state = check_http(static.http, url, max_hops=config.max_redirect_hops)
            if state.get("redirect_loop"):
                findings.append({"rule_id": "redirect_loop", "url": url,
                                 "severity": "critical", "detail": state.get("error", "loop")})
            elif state.get("error") and state["status_code"] == 0:
                findings.append({"rule_id": "broken_internal_link", "url": url,
                                 "severity": "high", "detail": state.get("error", "unreachable")})
            elif state["status_code"] >= 400:
                findings.append({"rule_id": "broken_internal_link", "url": url,
                                 "severity": "high",
                                 "detail": f"HTTP {state['status_code']} (final {state['final_url']})"})
            elif state.get("redirect_hops", 0) > 1:
                findings.append({"rule_id": "redirect_chain", "url": url,
                                 "severity": "medium",
                                 "detail": f"{state['redirect_hops']} hops -> {state['final_url']}"})

        # wp_static_mismatch: published post whose expected static URL is not
        # rendered (bounded sample, deterministic GET).
        for post in posts[:limit]:
            expected = wp_link_to_static(post.get("link", ""), _static_host(config))
            state = check_http(static.http, expected, max_hops=config.max_redirect_hops)
            if state.get("redirect_loop"):
                findings.append({"rule_id": "redirect_loop", "url": expected,
                                 "severity": "critical", "detail": "loop on expected static URL"})
            elif state["status_code"] == 0 or state["status_code"] >= 400:
                findings.append(
                    {
                        "rule_id": "wp_static_mismatch",
                        "url": post.get("link", ""),
                        "severity": "high",
                        "detail": f"expected static URL {expected} -> HTTP {state['status_code']}"
                                  f" ({state.get('error', 'not rendered')})",
                    }
                )

        for page in pages:
            expected = _expected_canonical(page.url, config)
            findings.extend(
                _finding(f, page.url) for f in meta_check.meta_findings(page)
            )
            findings.extend(
                _finding(f, page.url) for f in meta_check.canonical_findings(page, expected_canonical=expected)
            )
        for f in meta_check.duplicate_title_findings(pages):
            rule = get_rule("title_duplicate")
            findings.append(
                {
                    "rule_id": "title_duplicate",
                    "url": ", ".join(f.get("urls", [])),
                    "severity": rule.severity if rule else "medium",
                    "detail": f.get("detail", ""),
                }
            )
        findings.extend(
            {
                "rule_id": "sitemap_blocked",
                "url": item["url"],
                "severity": "high",
                "detail": f"blocked by robots.txt rule {item['rule']!r}",
            }
            for item in blocked
        )
        findings.extend(
            {
                "rule_id": "wp_static_mismatch",
                "url": item.get("wp_link", ""),
                "severity": "high",
                "detail": f"expected static URL {item.get('expected_static', '')} not rendered",
            }
            for item in report.wp_static_mismatch[:limit]
        )

    plan = build_action_plan(findings, max_safe_fix=config.max_safe_fix_per_cycle)
    summary = {"command": "audit", "cycle_id": cycle_id, **report.summary(),
               "audited_urls": len(sample), "findings": len(findings)}

    result = {
        "status": "ok",
        "summary": summary,
        "findings": findings,
        "safe_actions": plan["safe_actions"],
        "approval_required": plan["approval_required"],
    }

    if getattr(args, "markdown", False) or args.command in {"report", "cycle"}:
        # Persist a cycle snapshot for later diffs.
        try:
            storage = Storage(config.sqlite_path)
            storage.save_cycle(cycle_id, started, _now(), summary)
            storage.save_findings(cycle_id, findings, _now())
            storage.close()
        except Exception as exc:  # state must never break the audit
            result.setdefault("warnings", []).append(f"state persist failed: {exc}")
        if not getattr(args, "json", False):
            sys.stdout.write(render_markdown(result))
            return 0

    _emit(result, force_json=args.json)
    return 0


def _cmd_diff_sitemap(args: argparse.Namespace, config: Any) -> int:
    a = _load_url_list(args.url_a, config)
    b = _load_url_list(args.url_b, config)
    diff = sitemap_diff(a, b)
    result = {
        "status": "ok",
        "summary": {"command": "diff-sitemap", **diff.summary()},
        "findings": [],
        "safe_actions": [],
        "approval_required": [],
        "diff": {"added": diff.added, "removed": diff.removed},
    }
    _emit(result, force_json=True)
    return 0


def _cmd_inspect(args: argparse.Namespace, config: Any) -> int:
    """Build the persistent URL Inspection queue and drain it within budget."""
    warnings: list[str] = []
    with Storage(config.sqlite_path) as storage:
        # Crash recovery: rows stuck in_progress from interrupted runs.
        storage.reset_stuck_in_progress()
        with WordPressClient(config) as wp, StaticSiteClient(config) as static:
            posts = wp.list_posts(status="publish")
            sitemap_urls = static.all_sitemap_urls()

        modified_by_url = {
            normalize_url(p.get("link", "")): (p.get("modified") or "")
            for p in posts if p.get("link")
        }

        # GSC impressions (optional): tiers 2-3 need Search Analytics.
        impressions: dict[str, float] = {}
        prev_impressions: dict[str, float] = {}
        gsc: SearchConsoleClient | None = None
        if config.google_credentials:
            gsc = SearchConsoleClient(config)
            end = date.today()
            start = end - timedelta(days=config.search_analytics_days)
            prev_start = start - timedelta(days=config.search_analytics_days)
            try:
                for row in gsc.search_analytics_by_page(
                    start_date=start.isoformat(), end_date=end.isoformat()
                ):
                    impressions[normalize_url(row["keys"][0])] = float(row.get("impressions", 0))
                for row in gsc.search_analytics_by_page(
                    start_date=prev_start.isoformat(),
                    end_date=(start - timedelta(days=1)).isoformat(),
                ):
                    prev_impressions[normalize_url(row["keys"][0])] = float(row.get("impressions", 0))
            except ConnectorError as exc:
                warnings.append(f"GSC fetch failed: {exc}")
        else:
            warnings.append("GSC não configurado (GOOGLE_APPLICATION_CREDENTIALS); tiers 2-3 pulados")

        entries = build_queue_entries(
            sitemap_urls,
            modified_by_url=modified_by_url,
            impressions_by_url=impressions,
            prev_impressions_by_url=prev_impressions,
            grace_hours=config.url_inspection_grace_period_hours,
        )
        inserted = storage.enqueue_urls(entries)

        budget_cap = args.budget or config.url_inspection_daily_budget
        used = storage.budget_used()
        remaining = remaining_budget(budget_cap, used)

        inspected: list[dict[str, Any]] = []
        can_run = (not config.dry_run) and gsc is not None and not getattr(args, "dry_run", False)
        if can_run:
            for item in storage.dequeue_next(limit=remaining):
                try:
                    result = gsc.inspect_url(item["url"])
                    storage.mark_done(item["id"], result)
                    storage.budget_consume(1)
                    inspected.append({"url": item["url"], "priority": item["priority"]})
                except ConnectorError as exc:
                    storage.mark_failed(item["id"], str(exc))
                    warnings.append(f"inspect {item['url']} falhou: {exc}")
        else:
            warnings.append(
                "dry-run: fila construída, nenhuma chamada à URL Inspection (use DRY_RUN=false "
                "+ credenciais GSC para executar)"
            )
        # Recompute AFTER the loop: budget_consume runs inside it.
        used = storage.budget_used()
        remaining = remaining_budget(budget_cap, used)

        summary = {
            "command": "inspect",
            "queue_inserted": inserted,
            "budget_used": used,
            "budget_remaining": remaining,
            "inspected": len(inspected),
            **storage.queue_stats(),
        }
        result = {
            "status": "ok",
            "summary": summary,
            "findings": [],
            "safe_actions": [],
            "approval_required": [],
            "warnings": warnings,
            "pending_top": storage.pending_snapshot(10),
        }
        _emit(result, force_json=True)
        return 0


def _cmd_opportunities(args: argparse.Namespace, config: Any) -> int:
    """Search Analytics + Core Web Vitals opportunities (deterministic gates)."""
    warnings: list[str] = []
    findings: list[dict[str, Any]] = []

    # -- tier A: low CTR / zero-click (needs GSC) ----------------------------
    if config.google_credentials:
        gsc = SearchConsoleClient(config)
        end = date.today()
        start = end - timedelta(days=config.search_analytics_days)
        try:
            rows = gsc.search_analytics_by_page(
                start_date=start.isoformat(), end_date=end.isoformat()
            )
            for row in rows:
                impressions = float(row.get("impressions", 0))
                clicks = float(row.get("clicks", 0))
                ctr = float(row.get("ctr", 0))
                page = (row.get("keys") or [""])[0]
                if impressions >= 100 and ctr <= 0.02:
                    findings.append({
                        "rule_id": "low_ctr_opportunity",
                        "url": page,
                        "severity": "medium",
                        "detail": f"{impressions:.0f} impressões, CTR {ctr:.1%}",
                    })
                if impressions >= 50 and clicks == 0:
                    findings.append({
                        "rule_id": "zero_click_impression",
                        "url": page,
                        "severity": "medium",
                        "detail": f"{impressions:.0f} impressões, 0 cliques",
                    })
        except ConnectorError as exc:
            warnings.append(f"GSC failed: {exc}")
    else:
        warnings.append("GSC não configurado — oportunidades de CTR/impressões puladas")

    # -- tier B: Core Web Vitals (CrUX field data; PSI lab fallback) ---------
    if config.crux_api_key:
        crux = CruxClient(config)
        try:
            cwv_values = crux.origin_cwv(_origin(config.static_site_url))
            findings.extend(cwv_findings("origin", cwv_values))
            # History: snapshot tagged with CWV so trends track improvement.
            with Storage(config.sqlite_path) as storage:
                storage.save_snapshot(
                    url=config.static_site_url, captured_at=_now(),
                    source="opportunities", cwv=cwv_values,
                )
        except ConnectorError as exc:
            warnings.append(f"CrUX origin failed: {exc}")
    else:
        warnings.append("CRUX_API_KEY não configurada — CWV de campo pulados")

    # PageSpeed lab data for the home URL (bounded: 1 Lighthouse run).
    if config.pagespeed_api_key:
        psi = PageSpeedClient(config)
        try:
            result = psi.run(config.static_site_url, strategy="mobile")
            findings.extend(
                cwv_findings(config.static_site_url, PageSpeedClient.cwv_values(result))
            )
        except ConnectorError as exc:
            warnings.append(f"PageSpeed failed: {exc}")
    else:
        warnings.append("PAGESPEED_API_KEY não configurada — CWV de laboratório pulados")

    summary = {
        "command": "opportunities",
        "findings": len(findings),
        "window_days": config.search_analytics_days,
    }
    result = {
        "status": "ok",
        "summary": summary,
        "findings": findings,
        "safe_actions": [],
        "approval_required": [],
        "warnings": warnings,
    }
    _emit(result, force_json=True)
    return 0


def _cmd_apply(args: argparse.Namespace, config: Any) -> int:
    """Execute safe_fix actions from a JSON file (mechanical executor).

    The file is the agent/human intent: [{rule_id, url, detail, fix:{...}}].
    Supported fix types: wp_media_alt, wp_post_meta. Dry-run by default.
    """
    actions = _load_actions_file(args.actions_file)
    if not actions:
        print(json.dumps({"status": "error", "error": "no actions in file"},
                         ensure_ascii=False))
        return 2

    cycle_id = f"apply-{uuid.uuid4().hex[:12]}"
    with Storage(config.sqlite_path) as storage, WordPressClient(config) as wp:
        executor = Executor(config, wp, storage)

        def _verify_post_write(fix: dict[str, Any], after: Any) -> bool:
            """Confirmação REST pós-write: relê o recurso e confere o valor
            persistido (meta do post ou alt_text da mídia). Falha aqui vira
            status unverified — retry permitido, não conta como executed."""
            try:
                if fix.get("type") == "wp_post_meta":
                    fresh = wp.get_post(fix["post_id"])
                    meta = fresh.get("meta") or {}
                    return all(
                        (meta.get(k) or "") == (v or "")
                        for k, v in (fix.get("meta") or {}).items()
                    )
                if fix.get("type") == "wp_media_alt":
                    media = wp.get_media(fix["media_id"])
                    return (media.get("alt_text") or "") == (fix.get("alt_text") or "")
            except Exception:
                return False
            return True

        outcome = executor.apply_safe_actions(
            actions, cycle_id=cycle_id,
            max_actions=args.limit_actions or config.max_safe_fix_per_cycle,
            verify=_verify_post_write,
        )

        # Local history: re-capture the affected pages post-fix (before/after
        # evidence tied to the executed action fingerprint). Only REAL changes
        # (executed) — previews and unverified must not pollute the history.
        affected = outcome["executed"]
        if affected:
            with StaticSiteClient(config) as static:
                for action in affected:
                    url = action.get("url")
                    if not url:
                        continue
                    page = static.fetch_page(url)
                    _save_page_snapshot(
                        storage, page,
                        cycle_id=cycle_id, source="executor",
                        linked_action=action.get("fingerprint", ""),
                    )
                    # Deterministic SEO projection stored automatically.
                    _capture_expectation(config, storage, url, source="apply",
                                         changed_at=_now())

    result = {
        "status": "ok",
        "summary": {
            "command": "apply",
            "cycle_id": cycle_id,
            "dry_run": outcome["dry_run"],
            "executed": len(outcome["executed"]),
            "previewed": len(outcome["previewed"]),
            "unverified": len(outcome["unverified"]),
            "skipped": len(outcome["skipped"]),
        },
        "findings": [],
        "safe_actions": outcome["executed"] + outcome["previewed"],
        "approval_required": [],
        "skipped_actions": outcome["skipped"],
        "unverified_actions": outcome["unverified"],
    }
    _emit(result, force_json=True)
    return 0


def _cmd_wayback(args: argparse.Namespace, config: Any) -> int:
    """Archive evidence: availability + snapshot count (never delete blindly)."""
    from .connectors.wayback import WaybackClient

    with WaybackClient(config) as client:
        available = client.availability(args.url)
        count = client.snapshot_count(args.url)
    result = {
        "status": "ok",
        "summary": {"command": "wayback", "url": args.url,
                    "archived": available["archived"], "snapshots": count},
        "findings": [],
        "safe_actions": [],
        "approval_required": [],
        "archive": {**available, "snapshot_count": count},
    }
    _emit(result, force_json=True)
    return 0


def _cmd_validate_schema(args: argparse.Namespace, config: Any) -> int:
    from .checks.schema import validate_schema
    from .rules.registry import get_rule

    with StaticSiteClient(config) as static:
        page = static.fetch_page(args.url)
    findings = validate_schema(page)
    for f in findings:
        rule = get_rule(f.get("rule_id", ""))
        f["severity"] = rule.severity if rule else "info"
    result = {
        "status": "ok",
        "summary": {"command": "validate-schema", "url": args.url,
                    "findings": len(findings)},
        "findings": findings,
        "safe_actions": [],
        "approval_required": [],
    }
    _emit(result, force_json=True)
    return 0


def _cmd_import_crawl(args: argparse.Namespace, config: Any) -> int:
    from .tools.screaming_frog import import_crawl_csv, summary

    try:
        rows = import_crawl_csv(args.csv)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    summ = summary(rows)
    non_200 = [r["url"] for r in rows if 400 <= r.get("status_code", 0) < 600]
    result = {
        "status": "ok",
        "summary": {"command": "import-crawl", **summ},
        "findings": [],
        "safe_actions": [],
        "approval_required": [],
        "non_200_urls": non_200[: config.max_urls_per_run],
    }
    _emit(result, force_json=True)
    return 0


def _cmd_wse(args: argparse.Namespace, config: Any) -> int:
    from .tools.wse_trigger import WseError, WseTrigger

    trigger = WseTrigger(config)
    try:
        if args.action == "purge":
            target = args.target or "all"
            outcome = trigger.cdn_purge(target)
        elif args.action == "rebuild":
            kind = args.target or "smart"
            outcome = trigger.rebuild(kind)
        else:
            outcome = trigger.status()
    except WseError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    result = {
        "status": "ok",
        "summary": {"command": "wse", "action": args.action,
                    "executed": outcome.get("executed", False)},
        "findings": [],
        "safe_actions": [],
        "approval_required": [],
        "wse": outcome,
    }
    _emit(result, force_json=True)
    return 0


def _cmd_telemetry(args: argparse.Namespace, config: Any) -> int:
    """Observability: findings by rule/severity, queue, budget, actions."""
    from .report.notify import Notifier

    try:
        storage = Storage(config.sqlite_path)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2

    findings_by_rule = dict(storage.conn.execute(
        "SELECT rule_id, COUNT(*) FROM findings GROUP BY rule_id ORDER BY 2 DESC"
    ).fetchall())
    findings_by_severity = dict(storage.conn.execute(
        "SELECT severity, COUNT(*) FROM findings GROUP BY severity ORDER BY 2 DESC"
    ).fetchall())
    last_cycles = [r[0] for r in storage.conn.execute(
        "SELECT id FROM cycles ORDER BY started_at DESC LIMIT 3"
    ).fetchall()]
    queue = storage.queue_stats()
    budget = storage.budget_used()
    actions_executed = storage.conn.execute(
        "SELECT COUNT(*) FROM actions WHERE status = 'executed'"
    ).fetchone()[0]
    audit_entries = storage.conn.execute(
        "SELECT COUNT(*) FROM audit_log"
    ).fetchone()[0]
    storage.close()

    summary = {
        "command": "telemetry",
        "findings_by_rule": findings_by_rule,
        "findings_by_severity": findings_by_severity,
        "last_cycles": last_cycles,
        "inspection_queue": queue,
        "budget_used_today": budget,
        "actions_executed": actions_executed,
        "audit_entries": audit_entries,
    }
    result = {
        "status": "ok",
        "summary": summary,
        "findings": [],
        "safe_actions": [],
        "approval_required": [],
    }

    # Optional alert: high/critical findings above threshold -> webhook.
    if getattr(args, "notify", False) and config.alert_webhook_url:
        high = findings_by_severity.get("high", 0)
        critical = findings_by_severity.get("critical", 0)
        sent = Notifier(config.alert_webhook_url).maybe_alert(
            findings=[{"severity": s} for s in ("high",) * high + ("critical",) * critical],
            high_threshold=config.alert_high_threshold,
        )
        result["summary"]["alert_sent"] = sent

    _emit(result, force_json=True)
    return 0


def _cmd_schedule(args: argparse.Namespace, config: Any) -> int:
    """Watchdog: run the right phase by time-of-day (publish-cron pattern).

    Always: bounded audit + report. Daily window (default hour 6): also GSC
    inspect. Weekly window (default Monday): also opportunities + deep report.
    Silently reports what ran — empty findings mean nothing urgent.
    """
    import contextlib
    import datetime
    import io

    now = datetime.datetime.now()
    steps: list[str] = []

    def run_silently(func, **kw) -> None:
        """Run an internal command swallowing its stdout (single JSON out)."""
        with contextlib.redirect_stdout(io.StringIO()):
            func(**kw)

    # 1) Bounded audit + report (always).
    run_silently(_cmd_audit, args=_ns(limit=config.max_urls_per_run, json=True,
                                      markdown=False, command="report"), config=config)
    steps.append("audit")

    # 2) Daily GSC inspect window.
    inspect_hours = {int(h) for h in str(args.inspect_hours).split(",") if h.strip()}
    if now.hour in inspect_hours:
        run_silently(_cmd_inspect, args=_ns(budget=0, dry_run=False, json=True), config=config)
        # Background: mantém a fila de melhorias crescendo diariamente.
        run_silently(_cmd_post_audit, args=_ns(limit=20, min_impressions=50,
                                               write=False, json=True), config=config)
        steps.append("inspect")
        steps.append("post-audit")

    # 3) Weekly deep report + opportunities + deep post-audit.
    if now.weekday() == args.deep_weekday and now.hour == min(inspect_hours or {6}):
        run_silently(_cmd_opportunities, args=_ns(json=True), config=config)
        run_silently(_cmd_audit, args=_ns(limit=config.max_urls_per_run * 2, json=True,
                                          markdown=False, command="report"), config=config)
        run_silently(_cmd_post_audit, args=_ns(limit=50, min_impressions=50,
                                               write=True, json=True), config=config)
        steps.append("deep_report")
        steps.append("post-audit-deep")

    result = {
        "status": "ok",
        "summary": {"command": "schedule", "steps": steps,
                    "hour": now.hour, "weekday": now.weekday()},
        "findings": [],
        "safe_actions": [],
        "approval_required": [],
    }
    _emit(result, force_json=True)
    return 0


def _ns(**kw) -> argparse.Namespace:
    """Build a Namespace for internal CLI calls."""
    return argparse.Namespace(**kw)


def _cmd_snapshot(args: argparse.Namespace, config: Any) -> int:
    """Capture a page snapshot into the local history (read-only)."""
    from .report.history import summarize_page

    with Storage(config.sqlite_path) as storage, StaticSiteClient(config) as static:
        page = static.fetch_page(args.url)
        _save_page_snapshot(storage, page, cycle_id="", source="manual")
        digest = summarize_page(storage, args.url, limit=10)
    result = {
        "status": "ok",
        "summary": {"command": "snapshot", "url": args.url,
                    "status_code": page.status_code,
                    "snapshots": digest["snapshots"]},
        "findings": [],
        "safe_actions": [],
        "approval_required": [],
        "latest": {
            "title": page.title,
            "meta_description": page.meta_description,
            "canonical": page.canonical,
            "meta_robots": page.meta_robots,
            "content_hash": _content_hash(page),
        },
    }
    _emit(result, force_json=True)
    return 0


def _cmd_history(args: argparse.Namespace, config: Any) -> int:
    """Per-page before/after history (agent + human readable)."""
    from .report.history import summarize_page

    # --limit default é 0 ("0 = config max" do parser global), mas aqui 0
    # viraria literal `LIMIT 0` no SQL e esconderia todo o histórico.
    limit = args.limit if args.limit and args.limit > 0 else 50
    with Storage(config.sqlite_path) as storage:
        digest = summarize_page(storage, args.url, limit=limit)
    result = {
        "status": "ok",
        "summary": {"command": "history", "url": args.url,
                    "snapshots": digest["snapshots"]},
        "findings": [],
        "safe_actions": [],
        "approval_required": [],
        "history": digest,
    }
    _emit(result, force_json=True)
    return 0


def _cmd_trends(args: argparse.Namespace, config: Any) -> int:
    """Site-wide trends across cycles (before/after verification)."""
    from .report.history import aggregate_trends

    with Storage(config.sqlite_path) as storage:
        trends = aggregate_trends(storage, limit_cycles=10)
    result = {
        "status": "ok",
        "summary": {"command": "trends", **{k: v for k, v in trends.items()
                                            if k != "findings_by_cycle"}},
        "findings": [],
        "safe_actions": [],
        "approval_required": [],
        "trends": trends,
    }
    _emit(result, force_json=True)
    return 0


def _save_page_snapshot(
    storage: Storage,
    page: Any,
    *,
    cycle_id: str,
    source: str,
    linked_action: str = "",
) -> None:
    """Persist one page's SEO-relevant state into the local history."""
    storage.save_snapshot(
        url=page.url,
        captured_at=_now(),
        cycle_id=cycle_id,
        source=source,
        linked_action=linked_action,
        status_code=page.status_code,
        title=page.title,
        meta_description=page.meta_description,
        canonical=page.canonical,
        meta_robots=page.meta_robots,
        h1=" | ".join(page.h1),
        word_count=_word_count(page.body_text or page.html),
        content_hash=_content_hash(page),
    )


def _content_hash(page: Any) -> str:
    import hashlib

    raw = page.html or ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest() if raw else ""


def _word_count(html: str) -> int:
    import re

    text = re.sub(r"<[^>]+>", " ", html or "")
    return len([w for w in re.split(r"\s+", text) if w.strip()])


def _title_matches_visible(expected: str, visible: str) -> bool:
    """O título renderizado confere com o esperado, tolerando sufixo de marca
    ou template (ex.: 'Título | Unicórnio Hater') e diferenças de acentuação:
    normaliza (lowercase, sem acentos, espaços colapsados) e aceita
    igualdade ou sufixo de marca após o título. Conteúdo extra que NÃO
    começa por separador de marca (ex.: título antigo mais longo que o novo,
    '...série até o momento — UnicórnioHater') NÃO conta como confirmação —
    senão o rebuild pendente nunca é detectado quando o novo título é
    prefixo do antigo."""
    import re
    import unicodedata

    def norm(s: str) -> str:
        s = (s or "").lower().strip()
        s = "".join(c for c in unicodedata.normalize("NFKD", s)
                    if not unicodedata.combining(c))
        return re.sub(r"\s+", " ", s)

    exp, vis = norm(expected), norm(visible)
    if len(exp) < 3 or len(vis) < 3:
        return bool(exp) and exp == vis
    if exp == vis:
        return True
    if vis in exp:
        # renderizado é um prefixo/truncamento do esperado — aceita.
        return True
    if exp in vis:
        # esperado é prefixo do renderizado: só vale se o resto for marca
        # (separador típico) — conteúdo extra real indica rebuild pendente.
        rest = vis[vis.index(exp) + len(exp):].lstrip()
        return bool(rest) and rest[0] in {"|", "-", "—", "–", ":"}
    return False


def _cmd_title_opportunities(args: argparse.Namespace, config: Any) -> int:
    """Research real queries -> title candidates anchored in GSC data."""
    from .tools.title_opportunities import candidate_title, pick_top_query

    warnings: list[str] = []
    if not config.google_credentials:
        print(json.dumps({"status": "error",
                          "error": "GSC não configurado (GOOGLE_APPLICATION_CREDENTIALS)"},
                         ensure_ascii=False))
        return 2

    gsc = SearchConsoleClient(config)
    end = date.today()
    start = end - timedelta(days=config.search_analytics_days)

    try:
        pages = gsc.search_analytics_by_page(start_date=start.isoformat(),
                                             end_date=end.isoformat())
    except ConnectorError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2

    candidates_rows: list[dict[str, Any]] = []
    low_ctr = [
        r for r in pages
        if float(r.get("impressions", 0)) >= args.min_impressions
        and float(r.get("ctr", 0)) <= args.max_ctr
    ]
    low_ctr.sort(key=lambda r: float(r.get("impressions", 0)), reverse=True)
    targets = low_ctr[: args.limit or 20]

    with StaticSiteClient(config) as static, WordPressClient(config) as wp:
        for row in targets:
            url = (row.get("keys") or [""])[0]
            try:
                queries = gsc.top_queries(url, start_date=start.isoformat(),
                                          end_date=end.isoformat(), row_limit=15)
            except ConnectorError as exc:
                warnings.append(f"{url}: {exc}")
                continue
            top_query = pick_top_query(queries)
            suggested = candidate_title(top_query)
            page = static.fetch_page(url)
            post = wp.get_post_by_slug(url.rstrip("/").split("/")[-1])
            candidates_rows.append({
                "url": url,
                "current_title": page.title,
                "impressions": float(row.get("impressions", 0)),
                "clicks": float(row.get("clicks", 0)),
                "ctr": float(row.get("ctr", 0)),
                "position": float(row.get("position", 0)),
                "top_query": top_query,
                "top_queries": [
                    {"query": q["keys"][0], "impressions": q["impressions"],
                     "position": q["position"], "ctr": q["ctr"]}
                    for q in queries[:5]
                ],
                "suggested_title": suggested,
                "post_id": post["id"] if post else None,
            })

    result = {
        "status": "ok",
        "summary": {"command": "title-opportunities",
                    "candidates": len(candidates_rows),
                    "window_days": config.search_analytics_days},
        "findings": [],
        "safe_actions": [],
        "approval_required": [],
        "candidates": candidates_rows,
        "warnings": warnings,
    }

    if getattr(args, "write", False):
        fixes = [
            {
                "rule_id": "title_opportunity",
                "url": c["url"],
                "detail": f"título ancorado na query '{c['top_query']}'",
                "fix": {"type": "wp_post_meta", "post_id": c["post_id"],
                        "meta": {"rank_math_title": c["suggested_title"]}},
            }
            for c in candidates_rows if c["post_id"] and c["suggested_title"]
        ]
        from pathlib import Path
        Path("title-opportunities-fixes.json").write_text(
            json.dumps(fixes, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result["summary"]["fixes_written"] = len(fixes)

    _emit(result, force_json=True)
    return 0


def _cmd_impact(args: argparse.Namespace, config: Any) -> int:
    """Measure before/after SEO impact using GSC data around change dates."""
    from .report.history import diff_snapshots
    from .report.impact import aggregate_impact, impact_deltas

    if not config.google_credentials:
        print(json.dumps({"status": "error",
                          "error": "GSC não configurado (GOOGLE_APPLICATION_CREDENTIALS)"},
                         ensure_ascii=False))
        return 2

    gsc = SearchConsoleClient(config)
    today = date.today()

    with Storage(config.sqlite_path) as storage:
        # Changed pages: URLs with >=2 snapshots where a diff detected a change,
        # or any snapshot with a linked_action (agent edit).
        changed: list[dict[str, Any]] = []
        urls = [r[0] for r in storage.conn.execute(
            "SELECT DISTINCT url FROM page_snapshots"
        ).fetchall()]
        for url in urls:
            snaps = storage.page_snapshots(url, limit=50)
            for i in range(1, len(snaps)):
                diff = diff_snapshots(snaps[i - 1], snaps[i])
                if diff["changed"] or diff["content_changed"]:
                    changed.append({"url": url, "changed_at": snaps[i]["captured_at"]})
                    break
            if not any(c["url"] == url for c in changed):
                for s in snaps:
                    if s.get("linked_action"):
                        changed.append({"url": url, "changed_at": s["captured_at"]})
                        break

        changed = changed[: args.limit or 50]
        rows: list[dict[str, Any]] = []
        for entry in changed:
            try:
                changed_dt = datetime.datetime.fromisoformat(
                    entry["changed_at"].replace("Z", "+00:00")
                )
            except ValueError:
                changed_dt = datetime.datetime.now(datetime.timezone.utc)
            changed_date = changed_dt.date()
            after_days = (today - changed_date).days
            if after_days < args.min_after_days:
                rows.append({"url": entry["url"], "changed_at": entry["changed_at"],
                             "verdict": "insufficient_after_data",
                             "note": f"apenas {after_days}d desde a mudança "
                                     f"(mínimo {args.min_after_days}d)"})
                continue
            before = gsc.page_metrics(
                entry["url"],
                start_date=(changed_date - timedelta(days=args.days)).isoformat(),
                end_date=(changed_date - timedelta(days=1)).isoformat(),
            )
            after = gsc.page_metrics(
                entry["url"],
                start_date=changed_date.isoformat(),
                end_date=today.isoformat(),
            )
            deltas = impact_deltas(before, after)
            rows.append({
                "url": entry["url"],
                "changed_at": entry["changed_at"],
                "before": before,
                "after": after,
                **deltas,
            })

    result = {
        "status": "ok",
        "summary": {"command": "impact", "changed_pages": len(changed),
                    "measured": len([r for r in rows if r.get("verdict") not in
                                    ("insufficient_after_data", "unknown")]),
                    **aggregate_impact(rows)},
        "findings": [],
        "safe_actions": [],
        "approval_required": [],
        "impact": rows,
    }
    _emit(result, force_json=True)
    return 0


def _cmd_set_title(args: argparse.Namespace, config: Any) -> int:
    """Set a post's SEO title (rank_math_title) directly, with history."""
    from urllib.parse import urlparse

    from .executor.executor import Executor

    title = (args.title or "").strip()
    if not title:
        print(json.dumps({"status": "error", "error": "title vazio"}, ensure_ascii=False))
        return 2

    # target pode ser URL completa ou só o slug.
    parsed = urlparse(args.target)
    if parsed.scheme in {"http", "https"}:
        slug = parsed.path.strip("/").split("/")[-1]
    else:
        slug = args.target.strip("/").split("/")[-1]

    warnings: list[str] = []
    if len(title) > 65:
        warnings.append(f"título tem {len(title)} chars (> 65); o Google pode truncar")

    cycle_id = f"set-title-{uuid.uuid4().hex[:12]}"
    with Storage(config.sqlite_path) as storage, WordPressClient(config) as wp:
        post = wp.get_post_by_slug(slug)
        if not post:
            print(json.dumps({"status": "error",
                              "error": f"post não encontrado para o slug {slug!r}"},
                             ensure_ascii=False))
            return 2
        action = {
            "rule_id": "title_manual",
            "url": f"{config.static_site_url}/{slug}/",
            "detail": f"ajustar título manual ({len(title)} chars)",
            "fix": {"type": "wp_post_meta", "post_id": post["id"],
                    "meta": {"rank_math_title": title}},
        }

        # Snapshot ANTES (estado pré-alteração do site publicado): garante o par
        # antes/depois para o impact detectar a mudança por diff. Só em escrita
        # real — dry-run não toca o histórico local (mesmo contrato do apply).
        before_visible = ""
        if not config.dry_run:
            try:
                with StaticSiteClient(config) as static:
                    page_before = static.fetch_page(action["url"])
                    _save_page_snapshot(storage, page_before, cycle_id=cycle_id,
                                        source="set-title")
                    before_visible = page_before.title or ""
            except Exception:
                warnings.append("não foi possível capturar snapshot ANTES (site estático "
                                "indisponível); o impact depende de snapshot anterior")

        executor = Executor(config, wp, storage)

        def _verify_title_persisted(fix: dict[str, Any], after: Any) -> bool:
            """Confirmação REST pós-write: relê o post e verifica que o meta
            realmente foi persistido (não apenas aceito pela resposta)."""
            fresh = wp.get_post(fix["post_id"])
            expected = (fix.get("meta") or {}).get("rank_math_title", "")
            return ((fresh.get("meta") or {}).get("rank_math_title") or "") == expected

        outcome = executor.apply_safe_actions(
            [action], cycle_id=cycle_id, max_actions=1, verify=_verify_title_persisted
        )

        if outcome["unverified"]:
            warnings.append(
                "rank_math_title NÃO confirmado por re-leitura REST — ação registrada "
                "como unverified (retry liberado). Corrija o mu-plugin Rank Math / "
                "permissões e re-execute o comando."
            )
        if outcome["executed"]:
            # Snapshot DEPOIS: só quando o rebuild já está visível (título novo no
            # site estático). Senão, o par é completado pelo próximo audit/cycle
            # pós-rebuild — o diff antes/depois alimenta o impact.
            try:
                with StaticSiteClient(config) as static:
                    page_after = static.fetch_page(action["url"])
                    after_visible = page_after.title or ""
                    if _title_matches_visible(title, after_visible):
                        _save_page_snapshot(
                            storage, page_after, cycle_id=cycle_id,
                            source="set-title",
                            linked_action=outcome["executed"][0].get("fingerprint", ""),
                        )
                    else:
                        warnings.append(
                            "rebuild pendente: site estático ainda mostra o título "
                            "antigo; rode o rebuild e o próximo audit/cycle capturará "
                            "o snapshot pós-deploy (diff alimenta o impact)")
            except Exception:
                warnings.append("não foi possível capturar snapshot DEPOIS")
            _capture_expectation(config, storage, action["url"], source="set-title",
                                 changed_at=_now())

    result = {
        "status": "ok",
        "summary": {
            "command": "set-title",
            "slug": slug,
            "post_id": post["id"],
            "title_length": len(title),
            "dry_run": outcome["dry_run"],
            "executed": len(outcome["executed"]),
            "previewed": len(outcome["previewed"]),
            "unverified": len(outcome["unverified"]),
            "confirmed_via_rest": len(outcome["executed"]) > 0 and not outcome["unverified"],
            "snapshot_before": bool(before_visible),
        },
        "findings": [],
        "safe_actions": outcome["executed"] + outcome["previewed"],
        "approval_required": [],
        "skipped_actions": outcome["skipped"],
        "unverified_actions": outcome["unverified"],
        "warnings": warnings,
    }
    _emit(result, force_json=True)
    return 0


def _cmd_reindex_status(args: argparse.Namespace, config: Any) -> int:
    """Google position + last crawl time (reindexation) for changed pages."""
    from .report.history import diff_snapshots

    if not config.google_credentials:
        print(json.dumps({"status": "error",
                          "error": "GSC não configurado (GOOGLE_APPLICATION_CREDENTIALS)"},
                         ensure_ascii=False))
        return 2

    gsc = SearchConsoleClient(config)
    end = date.today()
    start = end - timedelta(days=config.search_analytics_days)

    with Storage(config.sqlite_path) as storage:
        # targets: uma URL pedida, ou as páginas alteradas detectadas no histórico.
        if args.single_url:
            targets = [{"url": args.single_url, "changed_at": ""}]
        else:
            targets = _find_changed_pages(storage, limit=args.limit or 20)

        rows: list[dict[str, Any]] = []
        for entry in targets:
            url = entry["url"]
            row: dict[str, Any] = {"url": url, "changed_at": entry.get("changed_at", "")}
            try:
                metrics = gsc.page_metrics(url, start_date=start.isoformat(),
                                           end_date=end.isoformat())
                row.update({
                    "position": metrics.get("position"),
                    "clicks": metrics.get("clicks"),
                    "impressions": metrics.get("impressions"),
                    "ctr": metrics.get("ctr"),
                })
            except ConnectorError as exc:
                row["error"] = str(exc)
                rows.append(row)
                continue
            try:
                inspection = gsc.inspect_url(url)  # consome 1 do orçamento
                index_status = inspection.get("indexStatusResult") or {}
                last_crawl = index_status.get("lastCrawlTime", "")
                row.update({
                    "last_crawl_time": last_crawl,
                    "index_verdict": index_status.get("verdict", ""),
                    "coverage_state": index_status.get("coverageState", ""),
                })
                if last_crawl and entry.get("changed_at"):
                    row["reindexed_since_change"] = last_crawl > entry["changed_at"]
            except ConnectorError as exc:
                row["inspection_error"] = str(exc)
            rows.append(row)

    reindexed = sum(1 for r in rows if r.get("reindexed_since_change"))
    result = {
        "status": "ok",
        "summary": {
            "command": "reindex-status",
            "pages": len(rows),
            "reindexed_since_change": reindexed,
            "awaiting_reindexation": len(rows) - reindexed,
        },
        "findings": [],
        "safe_actions": [],
        "approval_required": [],
        "pages": rows,
    }
    _emit(result, force_json=True)
    return 0


def _find_changed_pages(storage: Storage, *, limit: int = 50) -> list[dict[str, Any]]:
    """URLs with a detected change (title/canonical/content) or a linked_action."""
    from .report.history import diff_snapshots

    changed: list[dict[str, Any]] = []
    urls = [r[0] for r in storage.conn.execute(
        "SELECT DISTINCT url FROM page_snapshots"
    ).fetchall()]
    for url in urls:
        snaps = storage.page_snapshots(url, limit=50)
        found = False
        for i in range(1, len(snaps)):
            diff = diff_snapshots(snaps[i - 1], snaps[i])
            if diff["changed"] or diff["content_changed"]:
                changed.append({"url": url, "changed_at": snaps[i]["captured_at"]})
                found = True
                break
        if not found:
            for s in snaps:
                if s.get("linked_action"):
                    changed.append({"url": url, "changed_at": s["captured_at"]})
                    break
        if len(changed) >= limit:
            break
    return changed[:limit]


def _cmd_expectations(args: argparse.Namespace, config: Any) -> int:
    """Deterministic CTR/click improvement projection per page (no AI)."""
    from .report.expectations import build_expectation

    if not config.google_credentials:
        print(json.dumps({"status": "error",
                          "error": "GSC não configurado (GOOGLE_APPLICATION_CREDENTIALS)"},
                         ensure_ascii=False))
        return 2

    gsc = SearchConsoleClient(config)
    end = date.today()
    start = end - timedelta(days=config.search_analytics_days)

    with Storage(config.sqlite_path) as storage:
        if args.single_url:
            targets = [{"url": args.single_url, "changed_at": ""}]
        else:
            targets = _find_changed_pages(storage, limit=args.limit or 20)

        rows: list[dict[str, Any]] = []
        for entry in targets:
            url = entry["url"]
            try:
                metrics = gsc.page_metrics(url, start_date=start.isoformat(),
                                           end_date=end.isoformat())
            except ConnectorError as exc:
                rows.append({"url": url, "error": str(exc)})
                continue
            expectation = build_expectation(metrics)
            storage.save_expectation(
                url=url, computed_at=_now(), source="expectations",
                changed_at=entry.get("changed_at", ""), expectation=expectation,
            )
            rows.append({"url": url, **expectation})

    total_gap = round(sum(r.get("gap_clicks") or 0 for r in rows), 1)
    result = {
        "status": "ok",
        "summary": {
            "command": "expectations",
            "pages": len(rows),
            "total_gap_clicks": total_gap,
            "total_conservative_clicks": round(
                sum(r.get("conservative_clicks") or 0 for r in rows), 1),
            "total_realistic_clicks": round(
                sum(r.get("realistic_clicks") or 0 for r in rows), 1),
            "total_optimistic_clicks": round(
                sum(r.get("optimistic_clicks") or 0 for r in rows), 1),
        },
        "findings": [],
        "safe_actions": [],
        "approval_required": [],
        "expectations": rows,
    }
    _emit(result, force_json=True)
    return 0


def _capture_expectation(config: Any, storage: Storage, url: str,
                         *, source: str, changed_at: str = "") -> None:
    """Best-effort: store the deterministic expectation for a page post-change."""
    if not config.google_credentials:
        return
    from .report.expectations import build_expectation

    try:
        gsc = SearchConsoleClient(config)
        end = date.today()
        start = end - timedelta(days=config.search_analytics_days)
        metrics = gsc.page_metrics(url, start_date=start.isoformat(),
                                   end_date=end.isoformat())
        if metrics:
            storage.save_expectation(
                url=url, computed_at=_now(), source=source, changed_at=changed_at,
                expectation=build_expectation(metrics),
            )
    except Exception:
        pass  # projection must never break the apply


def _cmd_post_audit(args: argparse.Namespace, config: Any) -> int:
    """Read-only post improvement analysis with evidence-backed content briefs."""
    from .report.content_brief import build_content_brief
    from .report.expectations import build_expectation
    from .report.post_audit import LOST_TRAFFIC_RATIO, content_checklist, priority_score, total_gain
    from .report.scoring import confidence_for, score_factors

    if not config.google_credentials:
        print(json.dumps({"status": "error",
                          "error": "GSC não configurado (GOOGLE_APPLICATION_CREDENTIALS)"},
                         ensure_ascii=False))
        return 2

    gsc = SearchConsoleClient(config)
    end = date.today()
    start = end - timedelta(days=config.search_analytics_days)
    prev_start = start - timedelta(days=config.search_analytics_days)

    pages = gsc.search_analytics_by_page(start_date=start.isoformat(),
                                         end_date=end.isoformat())
    # BASE AO VIVO: métricas por página vêm direto do GSC (janela atual), não de
    # query_pages persistido. É a fonte da verdade da medição — difere de
    # url_demand() (janela persistida + filtro --min-impressions da coleta) apenas
    # quando a janela persistida não coincide com a janela atual ou há filtro.
    candidates = [p for p in pages if float(p.get("impressions", 0)) >= args.min_impressions]
    # Prioriza CTR baixo + muito volume.
    candidates.sort(key=lambda r: (float(r.get("ctr", 1)), -float(r.get("impressions", 0))))
    pool = candidates[: (args.limit or 20) * 3]

    rows: list[dict[str, Any]] = []
    with Storage(config.sqlite_path) as storage, \
            StaticSiteClient(config) as static, WordPressClient(config) as wp:
        for row in pool:
            url = (row.get("keys") or [""])[0]
            metrics = build_expectation({
                "impressions": float(row.get("impressions", 0)),
                "clicks": float(row.get("clicks", 0)),
                "ctr": float(row.get("ctr", 0)),
                "position": float(row.get("position", 0)),
            })

            # Rendered-page analysis is advisory only: it never creates a write action.
            snap = storage.latest_snapshot(url)
            word_count = (snap or {}).get("word_count")
            try:
                page = static.fetch_page(url)
                rendered_words = _word_count(page.body_text or page.html)
                word_count = rendered_words if rendered_words else word_count
            except Exception:
                page = None
            slug = url.rstrip("/").split("/")[-1]
            age_days = None
            try:
                post = wp.get_post_by_slug(slug)
                # Freshness is based on last meaningful WP update, not publication age.
                if post and (post.get("modified") or post.get("date")):
                    changed = post.get("modified") or post["date"]
                    changed_at = datetime.datetime.fromisoformat(changed.replace("Z", "+00:00"))
                    age_days = (datetime.datetime.now(datetime.timezone.utc) - changed_at).days
            except Exception:
                pass
            lost = False
            try:
                prev = gsc.page_metrics(
                    url, start_date=prev_start.isoformat(),
                    end_date=(start - timedelta(days=1)).isoformat(),
                )
                lost = prev.get("impressions", 0) > float(row.get("impressions", 0)) * LOST_TRAFFIC_RATIO
            except Exception:
                pass

            queries: list[dict[str, Any]] = []
            try:
                queries = gsc.top_queries(url, start_date=start.isoformat(),
                                          end_date=end.isoformat(), row_limit=15)
            except Exception:
                pass  # Lack of query detail must not prevent the broader audit.
            brief = build_content_brief(page, queries) if page else {"signals": {}, "suggestions": []}
            content = {"word_count": word_count, "age_days": age_days, "lost_traffic": lost,
                       **brief["signals"]}
            checklist = content_checklist(metrics, content)
            # Content-brief suggestions are manual, evidence-backed checklist items.
            checklist.extend({
                "item": item["item"], "reason": item["evidence"], "action": item["action"],
                "gain_clicks": None, "priority": item["priority"],
            } for item in brief["suggestions"])
            if not checklist:
                continue
            # Score explicável uniforme (impacto × confiança × facilidade).
            enriched = []
            for ci in checklist:
                factors = score_factors(
                    item=ci["item"], gain_clicks=ci.get("gain_clicks"),
                    evidence_quality=confidence_for(
                        has_queries=bool(queries), impressions=float(row.get("impressions", 0)),
                        word_count=word_count,
                    ),
                )
                enriched.append({**ci, **factors})
            checklist = enriched
            rows.append({
                "url": url,
                "title": page.title if page else (snap or {}).get("title", ""),
                "score": priority_score(metrics, content),
                "metrics": {k: metrics.get(k) for k in
                            ("position", "impressions", "clicks", "ctr", "expected_clicks")},
                "content": content,
                "content_brief": brief,
                "checklist": checklist,
                "total_gain_clicks": total_gain(checklist),
            })

        from .report.content_brief import cannibalization_suggestions
        cannibalization = cannibalization_suggestions(rows)
        for item in rows:
            for suggestion in cannibalization.get(item["url"], []):
                checklist_item = {
                    "item": suggestion["item"], "reason": suggestion["evidence"],
                    "action": suggestion["action"], "gain_clicks": None,
                    "priority": suggestion["priority"],
                    "related_urls": suggestion["related_urls"],
                }
                factors = score_factors(
                    item=checklist_item["item"], gain_clicks=None,
                    evidence_quality=confidence_for(
                        has_queries=bool(item["content_brief"].get("signals", {}).get("queries_considered")),
                        impressions=float(item["metrics"].get("impressions", 0)),
                        word_count=item["content"].get("word_count"),
                    ),
                )
                checklist_item.update(factors)
                item["checklist"].append(checklist_item)
                item["content_brief"]["suggestions"].append(suggestion)
            item["explainable_score"] = max(
                (i.get("score") or 0.0) for i in item["checklist"]
            )
            # Persist only manual suggestions.  This is a task queue, never a write queue.
            for checklist_item in item["checklist"]:
                storage.save_checklist_item(
                    url=item["url"], item=checklist_item["item"], reason=checklist_item["reason"],
                    action=checklist_item["action"], gain_clicks=checklist_item["gain_clicks"],
                    explainable_score=checklist_item.get("score"),
                    score_breakdown=checklist_item.get("score_breakdown"),
                )

        # Ordena pela pontuação explicável uniforme.
        rows.sort(key=lambda r: r["explainable_score"], reverse=True)
        rows = rows[: args.limit or 20]

    total_checklist = sum(len(r["checklist"]) for r in rows)
    total_gain_all = round(sum(r["total_gain_clicks"] for r in rows), 1)
    result = {
        "status": "ok",
        "summary": {
            "command": "post-audit",
            "posts_analyzed": len(rows),
            "checklist_items": total_checklist,
            "total_projected_gain_clicks": total_gain_all,
        },
        "findings": [],
        "safe_actions": [],
        "approval_required": [],
        "posts": rows,
    }

    if getattr(args, "write", False):
        _write_content_improvements_md(rows, result["summary"])
        result["summary"]["report_written"] = "reports/content-improvements.md"

    _emit(result, force_json=True)
    return 0


def _write_content_improvements_md(posts: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    from pathlib import Path

    lines = ["# Content Improvement Checklist (manual)", "",
             f"Gerado automaticamente pelo `post-audit` — {summary['posts_analyzed']} posts, "
             f"{summary['checklist_items']} melhorias, ganho projetado: "
             f"{summary['total_projected_gain_clicks']} cliques/mês.", "",
             "| Post | Score | Pos | Impr | Evidência | Melhoria | Ganho estimado |",
             "|---|---|---|---|---|---|---|"]
    for p in posts:
        m = p["metrics"]
        score = p.get("explainable_score", p.get("score", 0))
        for item in p["checklist"]:
            gain = f"{item['gain_clicks']:+.0f} cliques" if item["gain_clicks"] else "—"
            lines.append(
                f"| {p['url'][:55]} | {score} | {m.get('position', '—')} | "
                f"{m.get('impressions', 0):.0f} | {item['reason'][:70]} | "
                f"{item['action'][:60]} | {gain} |"
            )
    lines.append("")
    lines.append("> Fluxo manual: faça as melhorias e marque em `hermes-seo-agent checklist done <id>`.")
    Path("reports").mkdir(exist_ok=True)
    Path("reports/content-improvements.md").write_text("\n".join(lines), encoding="utf-8")


def _cmd_checklist(args: argparse.Namespace, config: Any) -> int:
    """View or update the improvement checklist (incl. workflow states)."""
    with Storage(config.sqlite_path) as storage:
        if args.action in {"done", "reject", "snooze", "supersede", "pending"}:
            if not args.item_id:
                print(json.dumps({"status": "error",
                                  "error": f"informe o id: checklist {args.action} <id>"},
                                 ensure_ascii=False))
                return 2
            status_map = {"done": "done", "reject": "rejected", "snooze": "snoozed",
                          "supersede": "superseded", "pending": "pending"}
            baseline = None
            if args.action == "done" and config.google_credentials:
                item = storage.get_checklist_item(args.item_id)
                if item and item.get("url"):
                    gsc = SearchConsoleClient(config)
                    end = date.today()
                    start = end - timedelta(days=config.search_analytics_days)
                    try:
                        baseline = gsc.page_metrics(
                            item["url"], start_date=start.isoformat(), end_date=end.isoformat()
                        ) or None
                    except ConnectorError:
                        baseline = None
            if args.action == "done":
                item = storage.get_checklist_item(args.item_id)
                # "Nunca contra {}": item mensurável (com URL) exige baseline real.
                if item and item.get("url") and baseline is None:
                    reason = ("GSC não configurado" if not config.google_credentials
                              else "falha ao capturar baseline GSC")
                    print(json.dumps(
                        {"status": "error",
                         "error": f"baseline obrigatório para item mensurável: {reason}"},
                        ensure_ascii=False))
                    return 2
            ok = storage.transition_checklist(
                args.item_id, status_map[args.action],
                reason=getattr(args, "reason", ""),
                responsible=getattr(args, "responsible", ""),
                deadline=getattr(args, "deadline", ""),
                intervention_type=getattr(args, "intervention_type", ""),
                baseline=baseline,
            )
            result = {
                "status": "ok",
                "summary": {"command": "checklist", "action": args.action,
                            "item_id": args.item_id, "ok": ok,
                            "baseline_captured": bool(baseline)},
                "findings": [], "safe_actions": [], "approval_required": [],
            }
            _emit(result, force_json=True)
            return 0

        if args.action == "rescore":
            """Backfill: re-score pending items deterministically (no re-crawl),
            using stored demand (query_pages) + inventory (body word count)."""
            from .report.scoring import confidence_for, score_factors
            limit = getattr(args, "limit", 0) or 5000
            rows = storage.conn.execute(
                "SELECT id, url, item, gain_clicks, explainable_score FROM improvement_checklist "
                "WHERE status = 'pending' ORDER BY (explainable_score IS NULL) DESC, id ASC "
                "LIMIT ?",
                (limit,),
            ).fetchall()
            re_scored = 0
            already = 0
            no_demand = 0
            for row in rows:
                cid, url, item, gain_clicks, score = row
                if score is not None and not getattr(args, "all", False):
                    already += 1
                    continue
                # Demanda AGREGADA da URL (mesma base de content-brief/post-audit).
                demand = storage.url_demand(url)
                impressions = demand["impressions"]
                body = storage.conn.execute(
                    "SELECT body_text FROM editorial_inventory WHERE url = ?", (url,)
                ).fetchone()
                words = len((body[0] or "").split()) if body else None
                if not demand["has_queries"]:
                    no_demand += 1
                factors = score_factors(
                    item=item, gain_clicks=gain_clicks,
                    evidence_quality=confidence_for(
                        has_queries=demand["has_queries"], impressions=impressions,
                        word_count=words,
                    ),
                )
                storage.set_checklist_score(cid, factors["score"], factors["score_breakdown"])
                re_scored += 1
            result = {
                "status": "ok",
                "summary": {"command": "checklist", "action": "rescore",
                            "re_scored": re_scored, "already_scored": already,
                            "without_demand": no_demand},
                "findings": [], "safe_actions": [], "approval_required": [],
            }
            _emit(result, force_json=True)
            return 0

        if args.action == "measure":
            from .report.impact import impact_deltas
            item = storage.get_checklist_item(args.item_id or 0)
            if not item or not item.get("url") or not config.google_credentials:
                print(json.dumps({"status": "error",
                                  "error": "item não encontrado ou GSC não configurado"},
                                 ensure_ascii=False))
                return 2
            # Janela mínima pós-implementação (implemented_at > done_at).
            ref = item.get("implemented_at") or item.get("done_at")
            if not ref:
                print(json.dumps({"status": "error",
                                  "error": "item não marcado como done (implemente antes de medir)"},
                                 ensure_ascii=False))
                return 2
            impl_date = datetime.datetime.fromisoformat(ref.replace("Z", "+00:00")).date()
            elapsed_days = (date.today() - impl_date).days
            min_days = getattr(args, "min_days", 0) or config.editorial_measurement_min_days
            if elapsed_days < min_days:
                print(json.dumps({"status": "error",
                                  "error": "janela pós-implementação insuficiente",
                                  "elapsed_days": elapsed_days, "minimum_days": min_days},
                                 ensure_ascii=False))
                return 2
            end = date.today()
            start = end - timedelta(days=config.search_analytics_days)
            gsc = SearchConsoleClient(config)
            now_metrics = gsc.page_metrics(item["url"], start_date=start.isoformat(),
                                           end_date=end.isoformat())
            baseline = item.get("baseline") or {}
            if item.get("measurement_unavailable") or not baseline:
                print(json.dumps({"status": "error",
                                  "error": "baseline nunca capturado / medição indisponível "
                                           "(done exige baseline GSC para itens mensuráveis)"},
                                 ensure_ascii=False))
                return 2
            deltas = impact_deltas(baseline, now_metrics)
            result = {
                "status": "ok",
                "summary": {"command": "checklist", "action": "measure",
                            "item_id": item["id"], "verdict": deltas["verdict"],
                            "elapsed_days": elapsed_days},
                "findings": [], "safe_actions": [], "approval_required": [],
                "measurement": {
                    "url": item["url"], "item": item["item"],
                    "intervention_type": item.get("intervention_type", ""),
                    "implemented_at": item.get("implemented_at"),
                    "baseline": baseline, "now": now_metrics, "deltas": deltas,
                },
            }
            _emit(result, force_json=True)
            return 0

        status = None if args.all else "pending"
        items = storage.list_checklist(status=status, limit=200)
        stats = storage.checklist_stats()

    result = {
        "status": "ok",
        "summary": {"command": "checklist", "items": len(items),
                    "pending": stats.get("pending", 0), "done": stats.get("done", 0)},
        "findings": [], "safe_actions": [], "approval_required": [],
        "items": items,
    }
    _emit(result, force_json=True)
    return 0


def _cmd_link_graph(args: argparse.Namespace, config: Any) -> int:
    """E0: internal link graph + editorial inventory with explicit coverage."""
    from .tools.link_graph import build_graph

    limit = args.limit or 300
    with Storage(config.sqlite_path) as storage, StaticSiteClient(config) as static:
        sitemap_urls = static.all_sitemap_urls()
        sample = list(dict.fromkeys([config.static_site_url.rstrip("/") + "/", *sitemap_urls]))[:limit]

        # Crawl with explicit failure tracking (coverage report).
        pages: list[Any] = []
        failures: list[dict[str, str]] = []
        for url in sample:
            try:
                page = static.fetch_page(url)
                if page.status_code >= 400:
                    failures.append({"url": url, "status_code": page.status_code})
                    continue
                pages.append(page)
            except Exception as exc:
                failures.append({"url": url, "error": str(exc)[:120]})

        graph = build_graph(pages)

        stored = 0
        stats: dict[str, int] = {}
        if getattr(args, "store", False):
            # converte chaves de path -> URLs completas antes de persistir
            from .inventory.reconcile import normalize_url as _norm
            url_by_key = {_norm(p.url): p.url for p in pages}
            edges_full: dict[str, list[str]] = {}
            for src_key, targets in graph["edges"].items():
                edges_full[url_by_key.get(src_key, src_key)] = [
                    url_by_key.get(t, t) for t in targets
                ]
            stored = storage.replace_internal_links(edges_full, _now())
            storage.save_editorial_inventory(pages, crawled_at=_now())
        stats = storage.link_graph_stats()
        inventoried_total = storage.conn.execute(
            "SELECT COUNT(*) FROM editorial_inventory"
        ).fetchone()[0]
        # Cobertura do CRAWL ATUAL: páginas bem-sucedidas nesta execução,
        # não COUNT(total) — registros antigos podem mascarar falhas recentes.
        coverage = round(len(pages) / len(sample) * 100, 1) if sample else 0.0

    result = {
        "status": "ok",
        "summary": {
            "command": "link-graph",
            "crawled": graph["crawled_pages"],
            "sitemap_sample": len(sample),
            "crawl_coverage_pct": coverage,
            "inventory_total_db": inventoried_total,
            "crawl_failures": len(failures),
            "orphans": len(graph["orphans"]),
            "hubs": len(graph["hubs"]),
            "edges_stored": stored,
            **stats,
        },
        "findings": [],
        "safe_actions": [],
        "approval_required": [],
        "orphans": graph["orphans"][:50],
        "hubs": [{"url": u, "in_links": c} for u, c in graph["hubs"]],
        "crawl_failures": failures[:50],
    }
    _emit(result, force_json=True)
    return 0


def _cmd_demand(args: argparse.Namespace, config: Any) -> int:
    """E1: collect + persist query×page demand, classify intent, find cannibalization."""
    from .tools.intent import classify_intent, normalize_query

    if not config.google_credentials:
        print(json.dumps({"status": "error",
                          "error": "GSC não configurado (GOOGLE_APPLICATION_CREDENTIALS)"},
                         ensure_ascii=False))
        return 2

    gsc = SearchConsoleClient(config)
    end = date.today()
    start = end - timedelta(days=config.search_analytics_days)

    rows = gsc.search_analytics_query_page(start_date=start.isoformat(),
                                           end_date=end.isoformat())
    stored = 0
    with Storage(config.sqlite_path) as storage:
        kept = 0
        for row in rows:
            keys = row.get("keys") or []
            if len(keys) < 2:
                continue
            query = normalize_query(keys[0])
            impressions = float(row.get("impressions", 0))
            if impressions < args.min_impressions:
                continue
            kept += 1
        if getattr(args, "store", False):
            payload = []
            for row in rows:
                keys = row.get("keys") or []
                if len(keys) < 2:
                    continue
                query = normalize_query(keys[0])
                if float(row.get("impressions", 0)) < args.min_impressions:
                    continue
                payload.append({
                    "query": query, "url": keys[1],
                    "clicks": float(row.get("clicks", 0)),
                    "impressions": float(row.get("impressions", 0)),
                    "ctr": float(row.get("ctr", 0)),
                    "position": float(row.get("position", 0)),
                    "intent": classify_intent(query),
                })
            stored = storage.save_query_pages(payload, window_start=start.isoformat(),
                                              window_end=end.isoformat())

        cannibalization = storage.cannibalization_candidates(
            min_impressions=float(args.min_impressions), window_start=start.isoformat()
        )
        top = storage.top_demand(min_impressions=50, limit=20)

        # Tendência das top queries entre as duas janelas mais recentes.
        windows = storage.demand_windows()
        trends: list[dict[str, Any]] = []
        if len(windows) >= 2:
            window_b, window_a = windows[-1], windows[-2]
            for item in top:
                trends.append(storage.demand_trend(item["query"], window_a=window_a,
                                                   window_b=window_b))
        trend_counts: dict[str, int] = {}
        for t in trends:
            trend_counts[t["trend"]] = trend_counts.get(t["trend"], 0) + 1

    # Intent distribution (deterministic)
    intents: dict[str, int] = {}
    for row in rows:
        keys = row.get("keys") or []
        if len(keys) < 2:
            continue
        intent = classify_intent(keys[0])
        intents[intent] = intents.get(intent, 0) + 1

    result = {
        "status": "ok",
        "summary": {
            "command": "demand",
            "query_page_pairs": kept,
            "stored": stored,
            "cannibalization_candidates": len(cannibalization),
            "intent_distribution": intents,
            "trend_counts": trend_counts,
            "windows_available": len(windows),
        },
        "findings": [],
        "safe_actions": [],
        "approval_required": [],
        "cannibalization": cannibalization[:20],
        "top_demand": top,
        "trends": trends,
    }
    _emit(result, force_json=True)
    return 0


def _cmd_content_brief(args: argparse.Namespace, config: Any) -> int:
    """E2 (unificado): content diagnosis via build_content_brief + checklist.

    Converges with post-audit on the SAME opportunity entity: evidence-backed
    suggestions from report/content_brief.py, gains from expectations, all
    persisted in improvement_checklist.
    """
    from .report.content_brief import build_content_brief
    from .report.expectations import build_expectation
    from .report.post_audit import content_checklist, priority_score, total_gain

    with Storage(config.sqlite_path) as storage:
        if args.single_url:
            targets = [args.single_url]
        else:
            targets = [url for url, _ in storage.top_pages_for_brief(limit=args.limit or 20)]

        gsc = SearchConsoleClient(config) if config.google_credentials else None
        end = date.today()
        start = end - timedelta(days=config.search_analytics_days)

        briefs: list[dict[str, Any]] = []
        with StaticSiteClient(config) as static:
            for url in targets:
                try:
                    page = static.fetch_page(url)
                except Exception:
                    continue
                queries_rows = storage.queries_for_url(url, limit=10)
                queries = [
                    {"keys": [q["query"]], "impressions": q.get("impressions") or 0,
                     "clicks": q.get("clicks") or 0, "position": q.get("position") or 0}
                    for q in queries_rows
                ]
                brief = build_content_brief(page, queries)

                # Score usa a DEMANDA AGREGADA da URL (mesma base do rescore):
                # todas as queries persistidas da janela — não apenas as top-10
                # usadas no diagnóstico textual acima.
                demand = storage.url_demand(url)
                impressions = demand["impressions"]
                clicks = demand["clicks"]
                page_words = _word_count(page.body_text or page.html)
                position = demand["position"]
                metrics = build_expectation({
                    "impressions": impressions, "clicks": clicks,
                    "ctr": (clicks / impressions) if impressions else 0.0,
                    "position": position or 0.0,
                })
                content = {
                    "word_count": page_words,
                    "age_days": None, "lost_traffic": False,
                    **brief["signals"],
                }
                checklist = content_checklist(metrics, content)
                checklist.extend({
                    "item": item["item"], "reason": item["evidence"],
                    "action": item["action"], "gain_clicks": None,
                } for item in brief["suggestions"])
                # Score explicável: impacto × confiança × facilidade.
                from .report.scoring import confidence_for, score_factors
                enriched = []
                for item in checklist:
                    factors = score_factors(
                        item=item["item"], gain_clicks=item.get("gain_clicks"),
                        evidence_quality=confidence_for(
                            has_queries=demand["has_queries"], impressions=impressions,
                            word_count=page_words,
                        ),
                    )
                    enriched.append({**item, **factors})
                checklist = enriched
                if not checklist:
                    continue
                if getattr(args, "store", False):
                    for item in checklist:
                        storage.save_checklist_item(
                            url=url, item=item["item"], reason=item.get("reason", ""),
                            action=item.get("action", ""),
                            gain_clicks=item.get("gain_clicks"),
                            explainable_score=item.get("score"),
                            score_breakdown=item.get("score_breakdown"),
                        )
                briefs.append({
                    "url": url,
                    "title": page.title,
                    "score": priority_score(metrics, content),
                    "explainable_score": max(
                        (i.get("score") or 0.0) for i in checklist
                    ),
                    "content_brief": brief,
                    "checklist": checklist,
                    "total_gain_clicks": total_gain(checklist),
                })

        # Ordena pela pontuação explicável (impacto × confiança × facilidade).
        briefs.sort(key=lambda b: b["explainable_score"], reverse=True)

    result = {
        "status": "ok",
        "summary": {"command": "content-brief", "briefs": len(briefs),
                    "checklist_items": sum(len(b["checklist"]) for b in briefs)},
        "findings": [],
        "safe_actions": [],
        "approval_required": [],
        "briefs": briefs,
    }
    _emit(result, force_json=True)
    return 0


def _cmd_editorial_backlog(args: argparse.Namespace, config: Any) -> int:
    """E3: generate revisable pautas from stored signals (deterministic)."""
    import json as _json

    from .report.backlog import generate_pautas

    with Storage(config.sqlite_path) as storage:
        cannibalization = storage.cannibalization_candidates(min_impressions=20)
        top_demand = storage.top_demand(min_impressions=200, limit=30)

        # briefs stored (content_briefs table)
        brief_rows = storage.conn.execute(
            "SELECT url, title, intent, gaps_json, action, priority FROM content_briefs "
            "ORDER BY priority DESC LIMIT 30"
        ).fetchall()
        briefs = [
            {"url": r[0], "title": r[1], "intent": r[2],
             "gaps": _json.loads(r[3] or "[]"), "action": r[4], "priority": r[5]}
            for r in brief_rows
        ]

        # categorias a partir das URLs com demanda
        category_urls: dict[str, list[str]] = {}
        category_titles: dict[str, list[str]] = {}
        for url, _ in storage.top_pages_for_brief(limit=60):
            cat = url.rstrip("/").split("/")[-2] if "/" in url.rstrip("/") else ""
            if not cat:
                continue
            category_urls.setdefault(cat, []).append(url)
        for cat, urls in category_urls.items():
            contexts = storage.editorial_contexts(urls)
            category_titles[cat] = [contexts.get(url, {}).get("title") or url.split("/")[-1].replace("-", " ") for url in urls]

        existing_pages = [dict(context, url=url) for url, context in storage.editorial_contexts().items()]

        # Tendência por query (duas janelas mais recentes) para não pautar demanda em queda.
        windows = storage.demand_windows()
        demand_trends: dict[str, str] = {}
        if len(windows) >= 2:
            window_b, window_a = windows[-1], windows[-2]
            for item in top_demand:
                demand_trends[item["query"]] = storage.demand_trend(
                    item["query"], window_a=window_a, window_b=window_b
                )["trend"]

        pautas = generate_pautas(
            cannibalization=cannibalization,
            briefs=briefs,
            top_demand=top_demand,
            category_urls=category_urls,
            category_titles=category_titles,
            existing_pages=existing_pages,
            demand_trends=demand_trends,
        )
        stored = sum(1 for p in pautas if storage.save_pauta(p))

    if getattr(args, "write", False):
        from pathlib import Path
        lines = ["# Editorial Backlog (revisão humana)", "",
                 f"Gerado por `editorial-backlog` — {len(pautas)} pautas propostas.", "",
                 "| Tipo | Pauta | Evidência | Score |", "|---|---|---|---|"]
        for p in pautas[:40]:
            lines.append(f"| {p['pauta_type']} | {p['title'][:50]} | {p['evidence'][:60]} | {p['score']} |")
        Path("reports").mkdir(exist_ok=True)
        Path("reports/editorial-backlog.md").write_text("\n".join(lines), encoding="utf-8")

    result = {
        "status": "ok",
        "summary": {"command": "editorial-backlog", "pautas": len(pautas), "stored": stored},
        "findings": [],
        "safe_actions": [],
        "approval_required": [],
        "pautas": pautas[:40],
    }
    _emit(result, force_json=True)
    return 0


def _cmd_interlinks(args: argparse.Namespace, config: Any) -> int:
    """E4: internal link suggestions + workflow (list/approve/reject/snooze/done)."""
    with Storage(config.sqlite_path) as storage:
        action = getattr(args, "action", None) or "generate"

        if action != "generate":
            if action == "list":
                status = None if getattr(args, "all", False) else (
                    getattr(args, "status", None) or None)
                items = storage.list_interlinks(status=status, limit=100)
                result = {
                    "status": "ok",
                    "summary": {"command": "interlinks", "action": "list",
                                "items": len(items)},
                    "findings": [], "safe_actions": [], "approval_required": [],
                    "suggestions": items,
                }
                _emit(result, force_json=True)
                return 0
            if not args.item_id:
                print(json.dumps({"status": "error",
                                  "error": f"informe o id: interlinks {action} <id>"},
                                 ensure_ascii=False))
                return 2
            status_map = {"approve": "approved", "reject": "rejected",
                          "snooze": "snoozed", "done": "done", "supersede": "superseded"}
            ok = storage.transition_interlink(
                args.item_id, status_map[action],
                reason=getattr(args, "reason", ""),
            )
            result = {
                "status": "ok",
                "summary": {"command": "interlinks", "action": action,
                            "item_id": args.item_id, "ok": ok},
                "findings": [], "safe_actions": [], "approval_required": [],
            }
            _emit(result, force_json=True)
            return 0

        from .report.interlinks import suggest_interlinks
        contexts = storage.editorial_contexts()
        sources = list(contexts)[:300]
        targets = list(contexts)[:2000]
        existing_out = {
            source: storage.out_links_for(source) for source in sources
        }
        suggestions = suggest_interlinks(
            sources=sources, targets=targets, existing_out=existing_out,
            contexts=contexts,
            limit_per_source=3,
        )
        stored = 0
        if getattr(args, "store", False):
            for s in suggestions:
                if storage.save_interlink(source_url=s["source_url"],
                                          target_url=s["target_url"], reason=s["reason"],
                                          anchor=s["anchor"]):
                    stored += 1

    result = {
        "status": "ok",
        "summary": {"command": "interlinks", "suggestions": len(suggestions),
                    "stored": stored},
        "findings": [],
        "safe_actions": [],
        "approval_required": [],
        "suggestions": suggestions[:30],
    }
    _emit(result, force_json=True)
    return 0


def _cmd_backlog(args: argparse.Namespace, config: Any) -> int:
    """E5: editorial workflow — list and transition pauta status."""
    from .report.impact import impact_deltas

    with Storage(config.sqlite_path) as storage:
        if args.action == "list":
            status = None if args.status == "all" else args.status
            items = storage.list_backlog(status=status, limit=100)
            result = {
                "status": "ok",
                "summary": {"command": "backlog", "items": len(items)},
                "findings": [], "safe_actions": [], "approval_required": [],
                "pautas": items,
            }
            _emit(result, force_json=True)
            return 0

        if not args.item_id:
            print(json.dumps({"status": "error", "error": "informe o id"},
                             ensure_ascii=False))
            return 2

        if args.action == "approve":
            ok = storage.transition_backlog(args.item_id, "approved",
                                            responsible=getattr(args, "responsible", ""))
        elif args.action == "reject":
            ok = storage.transition_backlog(args.item_id, "rejected",
                                            reason=getattr(args, "reason", ""))
        elif args.action == "snooze":
            ok = storage.transition_backlog(args.item_id, "snoozed",
                                            deadline=getattr(args, "deadline", ""),
                                            responsible=getattr(args, "responsible", ""))
        elif args.action == "supersede":
            ok = storage.transition_backlog(args.item_id, "superseded",
                                            reason=getattr(args, "reason", ""))
        elif args.action == "expire":
            expired = storage.expire_overdue()
            result = {
                "status": "ok",
                "summary": {"command": "backlog", "expired_items": expired},
                "findings": [], "safe_actions": [], "approval_required": [],
            }
            _emit(result, force_json=True)
            return 0
        elif args.action == "publish":
            baseline = {}
            if config.google_credentials and args.published_url:
                gsc = SearchConsoleClient(config)
                end = date.today()
                start = end - timedelta(days=config.search_analytics_days)
                try:
                    baseline = gsc.page_metrics(
                        args.published_url, start_date=start.isoformat(),
                        end_date=end.isoformat(),
                    )
                except ConnectorError:
                    baseline = {}
            ok = storage.transition_backlog(args.item_id, "published",
                                            published_url=args.published_url,
                                            baseline=baseline or None)
        elif args.action == "measure":
            items = storage.list_backlog(status="published", limit=500)
            target = next((i for i in items if i["id"] == args.item_id), None)
            if not target or not target.get("published_url"):
                print(json.dumps({"status": "error",
                                  "error": "pauta não está publicada (publish primeiro)"},
                                 ensure_ascii=False))
                return 2
            published_at = storage.published_at(args.item_id)
            if not published_at:
                print(json.dumps({"status": "error", "error": "data de publicação não registrada"}, ensure_ascii=False))
                return 2
            published_date = datetime.datetime.fromisoformat(published_at).date()
            elapsed_days = (date.today() - published_date).days
            if elapsed_days < config.editorial_measurement_min_days:
                print(json.dumps({"status": "error", "error": "janela pós-publicação insuficiente",
                                  "elapsed_days": elapsed_days,
                                  "minimum_days": config.editorial_measurement_min_days}, ensure_ascii=False))
                return 2
            if not config.google_credentials:
                print(json.dumps({"status": "error", "error": "GSC não configurado"}, ensure_ascii=False))
                return 2
            gsc = SearchConsoleClient(config)
            end = date.today()
            start = end - timedelta(days=config.search_analytics_days)
            now_metrics = gsc.page_metrics(target["published_url"],
                                           start_date=start.isoformat(),
                                           end_date=end.isoformat())
            import json as _json
            baseline = _json.loads(target.get("baseline_json") or "{}")
            deltas = impact_deltas(baseline, now_metrics)
            storage.transition_backlog(args.item_id, "measured")
            result = {
                "status": "ok",
                "summary": {"command": "backlog", "measured": args.item_id,
                            "verdict": deltas["verdict"], "elapsed_days": elapsed_days},
                "findings": [], "safe_actions": [], "approval_required": [],
                "measurement": {**target, "deltas": deltas, "now": now_metrics},
            }
            _emit(result, force_json=True)
            return 0
        else:
            ok = False

    result = {
        "status": "ok",
        "summary": {"command": "backlog", "action": args.action,
                    "item_id": args.item_id, "ok": ok},
        "findings": [], "safe_actions": [], "approval_required": [],
    }
    _emit(result, force_json=True)
    return 0


# -- helpers ----------------------------------------------------------------


def _load_actions_file(path: str) -> list[dict[str, Any]]:
    from pathlib import Path

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("safe_actions"), list):
        return data["safe_actions"]
    return []


def _origin(url: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _load_url_list(source: str, config: Any) -> list[str]:
    if source.startswith("file://"):
        from pathlib import Path

        path = Path(source[len("file://"):])
        return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")]
    with StaticSiteClient(config) as static:
        return static.all_sitemap_urls(sitemap_url=source)


def _static_host(config: Any) -> str:
    from urllib.parse import urlparse

    return urlparse(config.static_site_url).netloc


def _expected_canonical(url: str, config: Any) -> str:
    """Expected canonical of a sitemap URL is the URL itself (static site)."""
    return url


def _finding(f: dict[str, Any], url: str) -> dict[str, Any]:
    rule = get_rule(f.get("rule_id", ""))
    return {
        "rule_id": f.get("rule_id"),
        "url": url,
        "severity": rule.severity if rule else "info",
        "detail": f.get("detail", ""),
    }


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _emit(result: dict[str, Any], *, force_json: bool = False) -> None:
    if not force_json:
        # Keep the contract keys first for stable diffs.
        ordered = {key: result.get(key) for key in _OUTPUT_CONTRACT}
        for key in result:
            if key not in ordered:
                ordered[key] = result[key]
        result = ordered
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
