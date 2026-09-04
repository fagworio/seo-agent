"""M0 — IntegrationStatus: saúde de TODAS as fontes em um comando.

Checa (sem escrever nada): WordPress, sitemap estático, GSC, GA4 e CrUX.
Cada fonte reporta data_status (available|partial|missing|invalid),
configuração, última coleta persistida e limitação. Uma fonte ausente ou
sem credencial NUNCA aparece como "zero" — fica missing/invalid com motivo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import Config
from ..report.data_status import normalize_status
from ..storage.db import Storage

# Ação de recuperação sugerida por fonte (determinística, legível por humano).
# O agente NUNCA executa; é orientação para o operador.
RECOVERY_HINTS: dict[str, str] = {
    "wordpress": "configure WORDPRESS_URL, gere um Application Password e rode a coleta de inventário editorial.",
    "sitemap": "configure SITEMAP_URL e confirme que o sitemap estático está publicado e acessível.",
    "corpus": "rode um novo run do corpus para atualizar cobertura e reduzir staleness.",
    "gsc": "configure GOOGLE_APPLICATION_CREDENTIALS (service account), autorize a propriedade e rode a coleta do Search Console.",
    "ga4": "confirme GA4_PROPERTY_ID e as permissões de leitura e rode a coleta semanal do Analytics.",
    "crux": "configure CRUX_API_KEY/PAGESPEED_API_KEY; os dados CrUX são eventualmente consistentes.",
    "external": "configure o provedor externo (M4): credenciais, quota e custo.",
}


@dataclass
class SourceStatus:
    source: str
    configured: bool
    data_status: str
    detail: str = ""
    last_window: str = ""
    last_collected_at: str = ""
    rows: int = 0
    limitations: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "configured": self.configured,
            "data_status": self.data_status,
            "detail": self.detail,
            "last_window": self.last_window,
            "last_collected_at": self.last_collected_at,
            "rows": self.rows,
            "limitations": self.limitations,
            "recovery": self.recovery(),
            **self.extras,
        }

    def recovery(self) -> str:
        """Ação determinística de recuperação, legível por humano.

        available => vazio (sem ação). Qualquer outro estado descreve o que o
        operador pode executar para restaurar a fonte. Nunca sugere execução
        automática: o agente não age sem aprovação.
        """
        if self.data_status == "available":
            return ""
        base = RECOVERY_HINTS.get(self.source, "Revise a configuração e rode uma nova coleta.")
        if not self.configured:
            return f"Configuração ausente: {base}"
        if self.data_status == "invalid":
            return f"Fonte indisponível ou bloqueada: {base}"
        return f"{base}"


class IntegrationStatusService:
    """Deterministic health check over configured sources (read-only)."""

    def __init__(self, config: Config, storage: Storage):
        self.config = config
        self.storage = storage

    def check(self, *, live: bool = False, source: str | None = None) -> list[SourceStatus]:
        out = [
            self._wordpress(),
            self._sitemap(),
            self._corpus(),
            self._gsc(),
            self._ga4(),
            self._crux(),
            self._external(),
        ]
        if source:
            out = [s for s in out if s.source == source]
        collected = self._last_collected_map()
        for s in out:
            s.last_collected_at = collected.get(s.source, "")
        if live:
            self._live(out)
        return out

    def _last_collected_map(self) -> dict[str, str]:
        """R13: freshness — timestamp da última coleta persistida por fonte."""
        def q(sql: str) -> str:
            try:
                r = self.storage.conn.execute(sql).fetchone()
                return (r[0] if r and r[0] else "")
            except Exception:
                return ""
        return {
            "wordpress": q("SELECT MAX(last_collected_at) FROM wp_post_state"),
            "sitemap": q("SELECT MAX(crawled_at) FROM editorial_inventory"),
            "gsc": q("SELECT MAX(window_end) FROM query_pages"),
            "ga4": q("SELECT MAX(collected_at) FROM ga4_collection_runs"),
            "corpus": q("SELECT MAX(started_at) FROM corpus_runs"),
            "crux": "",  # CrUX é consultado ao vivo; sem coleta persistida
            "external": "",
        }

    # -- corpus (M2: memória editorial — "não encontrei conteúdo" confiável?) --

    def _corpus(self) -> SourceStatus:
        stats = self.storage.corpus_stats()
        report = self.storage.corpus_coverage_report()
        runs = self.storage.corpus_run_summary()
        global_cov = self.storage.corpus_global_coverage()
        last_run = runs["runs"][0] if runs["runs"] else None
        docs = stats["documents"]
        status = "missing"
        if docs:
            status = "available"
            if report.get("staleness", 0) > 0 or \
                    (last_run and last_run.get("failed", 0) > 0):
                status = "partial"
        return SourceStatus(
            "corpus", True, status,
            detail=f"{docs} docs / {stats['sections']} seções indexadas",
            last_window=(last_run or {}).get("started_at", ""),
            rows=docs,
            limitations="cobertura GLOBAL vs sitemap completo do último run",
            extras={
                "documents": docs, "sections": stats["sections"],
                "entities": stats["entities"],
                "staleness": report.get("staleness", 0),
                "unverifiable_docs": report.get("unverifiable_docs", 0),
                "global_sitemap_total": global_cov["global_sitemap_total"],
                "global_coverage_pct": global_cov["global_coverage_pct"],
                "last_run_status": (last_run or {}).get("status"),
                "last_run_failed": (last_run or {}).get("failed", 0),
            },
        )

    # -- fontes (configuração + última coleta persistida) -------------------

    def _wordpress(self) -> SourceStatus:
        if not self.config.wordpress_url:
            return SourceStatus("wordpress", False, "missing",
                                detail="WORDPRESS_URL vazio")
        # Inventário persistido é o vestígio de que o WP já foi lido.
        row = self.storage.conn.execute(
            "SELECT COUNT(*), MAX(crawled_at) FROM editorial_inventory"
        ).fetchone()
        return SourceStatus(
            "wordpress", True,
            "available" if row and row[0] else "missing",
            detail="URL configurada; inventário editorial é o vestígio de leitura",
            last_window=row[1] or "", rows=row[0] or 0,
            limitations="não faz escrita; exige Application Password p/ meta",
        )

    def _sitemap(self) -> SourceStatus:
        if not self.config.sitemap_url:
            return SourceStatus("sitemap", False, "missing",
                                detail="SITEMAP_URL vazio")
        row = self.storage.conn.execute(
            "SELECT COUNT(*), MAX(crawled_at) FROM editorial_inventory"
        ).fetchone()
        return SourceStatus(
            "sitemap", True,
            "available" if row and row[0] else "missing",
            detail="sitemap configurado; cobertura medida pelo inventário",
            last_window=row[1] or "", rows=row[0] or 0,
            limitations="cobertura canônica = URLs do inventário no sitemap",
        )

    def _gsc(self) -> SourceStatus:
        if not self.config.google_credentials:
            return SourceStatus("gsc", False, "missing",
                                detail="GOOGLE_APPLICATION_CREDENTIALS vazio")
        ws = self.storage.latest_window_start()
        row = self.storage.conn.execute(
            "SELECT COUNT(*) FROM query_pages WHERE window_start = ?",
            (ws,),
        ).fetchone() if ws else None
        rows = row[0] if row else 0
        return SourceStatus(
            "gsc", True,
            "available" if ws and rows else "missing",
            detail="credencial configurada",
            last_window=ws or "", rows=rows,
            limitations="Search Console API não aceita API key (usa service account)",
        )

    def _ga4(self) -> SourceStatus:
        if not self.config.ga4_property_id:
            return SourceStatus("ga4", False, "missing",
                                detail="GA4_PROPERTY_ID vazio")
        ws = self.storage.latest_ga4_window()
        row = self.storage.conn.execute(
            "SELECT COUNT(*) FROM ga4_page_metrics WHERE window_start = ?",
            (ws,),
        ).fetchone() if ws else None
        rows = row[0] if row else 0
        status = "available"
        if not ws or not rows:
            status = "missing"
        elif rows < 100:
            status = "partial"
        return SourceStatus(
            "ga4", True, status,
            detail="property configurada",
            last_window=ws or "", rows=rows,
            limitations="coleta semanal; sessões ≠ cliques GSC (não 1:1)",
        )

    def _crux(self) -> SourceStatus:
        if not self.config.crux_api_key and not self.config.pagespeed_api_key:
            return SourceStatus("crux", False, "missing",
                                detail="CRUX_API_KEY / PAGESPEED_API_KEY vazio")
        return SourceStatus(
            "crux", True, "available",
            detail="API key configurada",
            limitations="CrUX tem eventually-consistency; dados por origem (p75)",
        )

    def _external(self) -> SourceStatus:
        # M4: fonte externa real quando há adaptador configurado (ex.: Trends).
        from .market_intelligence import get_provider
        provider = get_provider(self.config)
        if provider.name == "none":
            return SourceStatus(
                "external", False, "missing",
                detail="nenhum provedor externo configurado (M4 opcional)",
                limitations="exige autorização, quota e custo configurados",
            )
        return SourceStatus(
            "external", True, "partial",
            detail=f"provedor {provider.name} configurado",
            limitations=f"custo {provider.cost_per_call_cents} centavos/chamada; "
                        "quota diária; evidência relativa (não volume absoluto)",
            extras={"provider": provider.name,
                    "cost_per_call_cents": provider.cost_per_call_cents},
        )

    # -- checagens ao vivo (opcionais) --------------------------------------

    def _live(self, out: list[SourceStatus]) -> None:
        # WordPress: tenta listar 1 post (sem escrever).
        try:
            from ..connectors.wordpress import WordPressClient
            with WordPressClient(self.config) as wp:
                posts = wp.list_posts(per_page=1)
                self._update(out, "wordpress",
                             "available" if posts else "partial",
                             "conexão OK; posts lidos")
        except Exception as exc:
            self._update(out, "wordpress", "invalid", f"falha ao conectar: {exc}")

        # Sitemap: tenta resolver a árvore.
        try:
            from ..connectors.static_site import StaticSiteClient
            with StaticSiteClient(self.config) as static:
                urls = static.all_sitemap_urls()
                self._update(out, "sitemap",
                             "available" if urls else "missing",
                             f"sitemap resolvido: {len(urls)} URLs",
                             extras={"sitemap_urls": len(urls)})
        except Exception as exc:
            self._update(out, "sitemap", "invalid", f"sitemap inacessível: {exc}")

        # GSC: consulta page_metrics da janela mais recente persistida.
        if self.config.google_credentials:
            try:
                from ..connectors.search_console import SearchConsoleClient
                import datetime as _dt
                gsc = SearchConsoleClient(self.config)
                end = _dt.date.today()
                start = end - _dt.timedelta(days=28)
                pages = gsc.search_analytics_by_page(
                    start_date=start.isoformat(), end_date=end.isoformat(), row_limit=1)
                self._update(out, "gsc", "available",
                             f"GSC OK; {len(pages)}+ páginas na janela")
            except Exception as exc:
                self._update(out, "gsc", "invalid", f"GSC falhou: {exc}")

        # GA4: status ao vivo (property + quota).
        if self.config.ga4_property_id:
            try:
                from ..connectors.analytics import AnalyticsClient
                import datetime as _dt
                ga4 = AnalyticsClient(self.config)
                end = _dt.date.today() - _dt.timedelta(days=1)
                start = end - _dt.timedelta(days=27)
                st = ga4.status(start_date=start.isoformat(), end_date=end.isoformat())
                self._update(out, "ga4", "available",
                             f"GA4 OK; {st['rows_returned']} linhas na janela",
                             extras={"canonical_urls": st["canonical_urls"]})
            except Exception as exc:
                self._update(out, "ga4", "invalid", f"GA4 falhou: {exc}")

        # CrUX: origem com API key.
        if self.config.crux_api_key:
            try:
                from urllib.parse import urlsplit
                from ..connectors.crux import CruxClient
                origin = f"https://{urlsplit(self.config.static_site_url).netloc}"
                cwv = CruxClient(self.config).origin_cwv(origin)
                self._update(out, "crux", "available",
                             f"CrUX OK; {sorted(cwv)} p75 capturados",
                             extras={"cwv": cwv})
            except Exception as exc:
                self._update(out, "crux", "partial",
                             f"CrUX indisponível agora: {exc}",
                             extras={"note": "eventualmente consistente"})

        # External (M4): uma chamada real — autocomplete funciona sem
        # credencial; explore (tendência/volume) pode estar bloqueado e
        # degrada com data_status explícito.
        from .market_intelligence import get_provider
        provider = get_provider(self.config)
        if provider.name != "none":
            try:
                topics = provider.keyword_suggestions("one piece", limit=3)
                self._update(out, "external", "available",
                             f"{provider.name} OK; {len(topics)} sugestões",
                             extras={"provider": provider.name,
                                     "suggestions": len(topics)})
            except Exception as exc:
                self._update(out, "external", "invalid",
                             f"{provider.name} bloqueado/indisponível: {str(exc)[:120]}",
                             extras={"provider": provider.name})

    def _update(self, out: list[SourceStatus], source: str, status: str,
                detail: str, extras: dict[str, Any] | None = None) -> None:
        for item in out:
            if item.source == source:
                item.data_status = normalize_status(status)
                item.detail = detail
                if extras:
                    item.extras.update(extras)
                return
