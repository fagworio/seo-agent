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


@dataclass
class SourceStatus:
    source: str
    configured: bool
    data_status: str
    detail: str = ""
    last_window: str = ""
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
            "rows": self.rows,
            "limitations": self.limitations,
            **self.extras,
        }


class IntegrationStatusService:
    """Deterministic health check over configured sources (read-only)."""

    def __init__(self, config: Config, storage: Storage):
        self.config = config
        self.storage = storage

    def check(self, *, live: bool = False) -> list[SourceStatus]:
        out = [
            self._wordpress(),
            self._sitemap(),
            self._gsc(),
            self._ga4(),
            self._crux(),
            self._external(),
        ]
        if live:
            self._live(out)
        return out

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
        return SourceStatus(
            "external", False, "missing",
            detail="nenhum provedor externo configurado (M4 opcional)",
            limitations="exige autorização, quota e custo configurados",
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

    def _update(self, out: list[SourceStatus], source: str, status: str,
                detail: str, extras: dict[str, Any] | None = None) -> None:
        for item in out:
            if item.source == source:
                item.data_status = normalize_status(status)
                item.detail = detail
                if extras:
                    item.extras.update(extras)
                return
