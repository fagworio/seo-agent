"""R3 — RefreshDataRun: coleta de dados por fonte como estágios de um AgentRun.

Cada fonte é um estágio independente. O orquestrador reutiliza o modelo
AgentRun (mark_step/complete) e os conectores existentes; NUNCA escreve no site
(ADR-0010). Falha de uma fonte não invalida as demais (falha parcial => status
"partial"). A reconciliação é R5; aqui só se coleta (lê) e relata contagens.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Callable

from ..config import Config
from ..storage.db import Storage
from .agent_runs import AgentRunService

# Ordem dos estágios de um refresh (ADR-0010). "reconcile" é R5.
STAGE_ORDER = ("wordpress", "sitemap", "gsc", "ga4", "crux", "corpus")

Collector = Callable[[], "StageResult"]


@dataclass
class StageResult:
    source: str
    status: str = "success"           # success | skipped | failed
    records_read: int = 0
    records_created: int = 0
    records_updated: int = 0
    data_window: str = ""
    error: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def as_detail(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "records_read": self.records_read,
            "records_created": self.records_created,
            "records_updated": self.records_updated,
            "data_window": self.data_window,
            **self.extra,
        }
        if self.error:
            d["error"] = self.error
        return d


def run_refresh(
    storage: Storage,
    run_id: int,
    *,
    sources: list[str],
    collectors: dict[str, Collector],
    reconcile: Collector | None = None,
) -> dict[str, Any]:
    """Executa os estágios de um run refresh_data e registra steps + status final.

    - `sources`: subconjunto de STAGE_ORDER a executar (na ordem canônica).
    - `collectors`: mapa source -> callable que retorna StageResult.
    - `reconcile`: opcional; roda como etapa final (pós-coleta) — R5.
    Retorna o run completo (com steps), já finalizado como success|partial|failed.
    """
    svc = AgentRunService(storage)
    stages = [s for s in STAGE_ORDER if s in sources]
    results: dict[str, dict[str, Any]] = {}
    failures = 0

    for stage in stages:
        collector = collectors.get(stage)
        if collector is None:
            svc.mark_step(run_id, stage, "failed", detail={"error": "coletor não registrado"})
            failures += 1
            results[stage] = {"status": "failed", "error": "coletor não registrado"}
            continue
        try:
            res = collector()
        except Exception as exc:  # um conector estourar não derruba o refresh
            res = StageResult(source=stage, status="failed", error=str(exc))

        if res.status == "failed":
            svc.mark_step(run_id, stage, "failed", detail=res.as_detail())
            failures += 1
        else:
            # success | skipped (skipped mantém a mensagem informativa no detail)
            svc.mark_step(run_id, stage, res.status, detail=res.as_detail())
        results[stage] = {**res.as_detail(), "status": res.status}

    # R5 — reconciliação pós-coleta (não é uma fonte; roda sempre que fornecida)
    if reconcile is not None:
        try:
            rres = reconcile()
        except Exception as exc:
            rres = StageResult(source="reconcile", status="failed", error=str(exc))
        if rres.status == "failed":
            svc.mark_step(run_id, "reconcile", "failed", detail=rres.as_detail())
            failures += 1
        else:
            svc.mark_step(run_id, "reconcile", rres.status, detail=rres.as_detail())
        results["reconcile"] = {**rres.as_detail(), "status": rres.status}

    status = "partial" if failures else "success"
    if failures and failures == len(results):
        status = "failed"
    svc.complete(
        run_id, status=status,
        summary={"sources": stages, "results": results},
        urls=sum(r.get("records_read", 0) for r in results.values()),
    )
    return svc.get_run(run_id)


# -- coletores reais (reutilizam os conectores existentes) -------------------

def build_refresh_collectors(config: Config, storage: Storage) -> dict[str, Collector]:
    return {
        "wordpress": lambda: _collect_wordpress(config, storage),
        "sitemap": lambda: _collect_sitemap(config),
        "gsc": lambda: _collect_gsc(config),
        "ga4": lambda: _collect_ga4(config),
        "crux": lambda: _collect_crux(config),
        "corpus": lambda: _collect_corpus(storage),
    }


def diff_wp_posts(current: list[dict[str, Any]], previous: dict[int, str]) -> dict[str, int]:
    """R4 — classificação incremental de posts vs estado anterior.

    previous: {post_id: modified_at}. Um post é:
      - new: post_id ausente no estado anterior;
      - changed: modified_at > anterior;
      - unchanged: sem mudança de modified;
      - removed: post_id no estado anterior mas ausente da coleta atual.
    """
    seen: set[int] = set()
    new = changed = unchanged = 0
    for p in current:
        pid = p.get("id")
        if pid is None:
            continue
        seen.add(int(pid))
        prev = previous.get(int(pid))
        if prev is None:
            new += 1
        elif (p.get("modified") or "") > prev:
            changed += 1
        else:
            unchanged += 1
    removed = sum(1 for pid in previous if pid not in seen)
    return {"known": len(previous), "new": new, "changed": changed,
            "unchanged": unchanged, "removed": removed}


def _collect_wordpress(config: Config, storage: Storage) -> StageResult:
    if not getattr(config, "wordpress_url", ""):
        return StageResult("wordpress", status="skipped", error="WORDPRESS_URL vazio")
    from ..connectors.wordpress import WordPressClient
    with WordPressClient(config) as wp:
        posts = wp.list_posts(status="publish")
    previous = storage.wp_post_state()
    diff = diff_wp_posts(posts, previous)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    storage.save_wp_post_state(posts, now=now)
    modified = [p.get("modified") or "" for p in posts]
    modified = [m for m in modified if m]
    return StageResult("wordpress", records_read=len(posts),
                       records_created=diff["new"], records_updated=diff["changed"],
                       data_window=max(modified) if modified else "", extra=diff)


def _collect_sitemap(config: Config) -> StageResult:
    if not getattr(config, "sitemap_url", "") and not getattr(config, "static_site_url", ""):
        return StageResult("sitemap", status="skipped", error="SITEMAP_URL/STATIC_SITE_URL vazio")
    from ..connectors.static_site import StaticSiteClient
    with StaticSiteClient(config) as static:
        urls = static.all_sitemap_urls()
    return StageResult("sitemap", records_read=len(urls))


def _collect_gsc(config: Config) -> StageResult:
    if not getattr(config, "google_credentials", ""):
        return StageResult("gsc", status="skipped", error="GOOGLE_APPLICATION_CREDENTIALS vazio")
    from ..connectors.search_console import SearchConsoleClient
    gsc = SearchConsoleClient(config)
    end = datetime.date.today()
    start = end - datetime.timedelta(days=getattr(config, "search_analytics_days", 28))
    rows = gsc.search_analytics_by_page(start_date=start.isoformat(), end_date=end.isoformat())
    return StageResult("gsc", records_read=len(rows),
                       data_window=f"{start.isoformat()} → {end.isoformat()}")


def _collect_ga4(config: Config) -> StageResult:
    if not getattr(config, "ga4_property_id", ""):
        return StageResult("ga4", status="skipped", error="GA4_PROPERTY_ID vazio")
    from ..connectors.analytics import AnalyticsClient
    ga4 = AnalyticsClient(config)
    end = datetime.date.today() - datetime.timedelta(days=1)
    start = end - datetime.timedelta(days=27)
    st = ga4.status(start_date=start.isoformat(), end_date=end.isoformat())
    return StageResult("ga4", records_read=st.get("rows_returned", 0),
                       data_window=f"{start.isoformat()} → {end.isoformat()}")


def _collect_crux(config: Config) -> StageResult:
    if not getattr(config, "crux_api_key", "") and not getattr(config, "pagespeed_api_key", ""):
        return StageResult("crux", status="skipped", error="CRUX_API_KEY/PAGESPEED_API_KEY vazio")
    from urllib.parse import urlsplit
    from ..connectors.crux import CruxClient
    origin = f"https://{urlsplit(config.static_site_url).netloc}"
    cwv = CruxClient(config).origin_cwv(origin)
    return StageResult("crux", records_read=len(cwv), data_window="p75 por origem")


def _collect_corpus(storage: Storage) -> StageResult:
    stats = storage.corpus_stats()
    return StageResult("corpus", records_read=stats.get("documents", 0))


def collect_reconcile(config: Config) -> StageResult:
    """R5: reconciliação WordPress × sitemap (três vias) após a coleta.

    Detecta páginas ausentes no sitemap, órfãs no sitemap e mismatches
    WordPress×estático — modificações feitas FORA do SEO Agent.
    """
    from urllib.parse import urlsplit
    from ..connectors.static_site import StaticSiteClient
    from ..connectors.wordpress import WordPressClient
    from ..inventory.reconcile import reconcile

    static_host = urlsplit(getattr(config, "static_site_url", "")).netloc or "www.unicorniohater.com.br"
    with WordPressClient(config) as wp:
        posts = wp.list_posts(status="publish")
    with StaticSiteClient(config) as static:
        sitemap_urls = static.all_sitemap_urls()
    report = reconcile(posts, sitemap_urls, static_host=static_host)
    return StageResult("reconcile", records_read=len(posts), extra=report.summary())
