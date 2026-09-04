"""P1 — Camada de aplicação e read model (OpportunityFeedService).

Projeta as fontes existentes (improvement_checklist, content_briefs,
editorial_backlog, interlink_suggestions) em um contrato unificado
OpportunityDTO, enriquecido com GSC e GA4 do storage.

SEM tabela de escrita: o feed é uma projeção. CLI, Hermes e uma API futura
consomem este mesmo serviço — nenhuma UI depende de Markdown ou de shell.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

_SOURCES = ("checklist", "content_brief", "backlog", "interlink")


@dataclass
class OpportunityDTO:
    id: str
    source: str                    # checklist | content_brief | backlog | interlink
    type: str                      # item / pauta_type / internal_link
    status: str
    url: str
    title: str = ""
    score: float | None = None
    score_breakdown: dict[str, Any] = field(default_factory=dict)
    evidence: str = ""
    recommendation: str = ""
    acceptance_criteria: str = ""
    gsc_metrics: dict[str, Any] = field(default_factory=dict)
    ga4_metrics: dict[str, Any] = field(default_factory=dict)
    measurement_state: str = "not_measurable"
    action_class: str = "approval_required"
    risk: str = "review_required"
    rollback_available: bool = False
    created_at: str = ""
    updated_at: str = ""
    decision_type: str = "review"
    related_recommendations: list[str] = field(default_factory=list)
    projection: dict[str, Any] = field(default_factory=dict)
    top_queries: list[dict[str, Any]] = field(default_factory=list)
    link_context: dict[str, Any] = field(default_factory=dict)
    data_freshness: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "source": self.source, "type": self.type,
            "status": self.status, "url": self.url, "title": self.title,
            "score": self.score, "score_breakdown": self.score_breakdown,
            "evidence": self.evidence, "recommendation": self.recommendation,
            "acceptance_criteria": self.acceptance_criteria,
            "gsc_metrics": self.gsc_metrics, "ga4_metrics": self.ga4_metrics,
            "measurement_state": self.measurement_state,
            "action_class": self.action_class, "risk": self.risk,
            "rollback_available": self.rollback_available,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "decision_type": self.decision_type,
            "related_recommendations": self.related_recommendations,
            "projection": self.projection, "top_queries": self.top_queries,
            "link_context": self.link_context, "data_freshness": self.data_freshness,
        }


class OpportunityFeedService:
    """Read model sobre o Storage (determinístico, sem rede)."""

    def __init__(self, storage: Any):
        self.storage = storage

    @staticmethod
    def _decision_type(action: str) -> str:
        value = (action or "").lower()
        if "título" in value or "title" in value or "meta description" in value:
            return "title_meta"
        if "link" in value or "âncora" in value:
            return "internal_link"
        if "criar" in value or "expand" in value or "conteúdo" in value:
            return "content"
        return "review"

    def _seo_context(self, url: str) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
        if not url:
            return {}, [], {}
        try:
            projection_rows = self.storage.expectations_for(url, limit=1)
        except Exception:
            projection_rows = []
        projection = projection_rows[0] if projection_rows else {}
        try:
            window = self.storage.latest_window_start()
        except Exception:
            window = None
        queries: list[dict[str, Any]] = []
        if window:
            try:
                rows = self.storage.conn.execute(
                    "SELECT query, intent, clicks, impressions, ctr, position FROM query_pages "
                    "WHERE url = ? AND window_start = ? ORDER BY impressions DESC LIMIT 5",
                    (url, window),
                ).fetchall()
            except Exception:
                rows = []
            queries = [{"query": r[0], "intent": r[1] or "", "clicks": r[2] or 0,
                        "impressions": r[3] or 0, "ctr": r[4], "position": r[5]} for r in rows]
        freshness = {"gsc_window_start": window or ""}
        if projection.get("computed_at"):
            freshness["projection_computed_at"] = projection["computed_at"]
        return projection, queries, freshness

    def _page_contexts(self, urls: list[str]) -> dict[str, dict[str, Any]]:
        """Resolve context from the current inventory, falling back to the corpus."""
        unique = list(dict.fromkeys(url for url in urls if url))
        try:
            contexts = self.storage.editorial_contexts(unique)
        except Exception:
            contexts = {}
        missing = [url for url in unique if url not in contexts]
        if not missing:
            return contexts
        placeholders = ", ".join("?" for _ in missing)
        try:
            rows = self.storage.conn.execute(
                f"SELECT url, title, h1, body_text, canonical, is_noindex, status_code "
                f"FROM corpus_documents WHERE url IN ({placeholders})", missing,
            ).fetchall()
        except Exception:
            rows = []
        for row in rows:
            contexts[row[0]] = {"title": row[1] or "", "h1": row[2] or "", "h2s": [],
                                "body_text": row[3] or "", "canonical": row[4] or "",
                                "is_noindex": bool(row[5]), "status_code": row[6] or 0}
        return contexts

    # -- projeções por fonte ------------------------------------------------

    def _checklist(self, status: str = "pending", limit: int = 200) -> list[OpportunityDTO]:
        items = self.storage.list_checklist(status=status, limit=limit)
        contexts = self._page_contexts([it.get("url", "") for it in items])
        out: list[OpportunityDTO] = []
        for it in items:
            url = it.get("url", "")
            page = contexts.get(url, {})
            gsc = self.storage.url_demand(url) if url else {}
            ga4 = self.storage.ga4_metrics_for_url(url) if url else None
            projection, top_queries, freshness = self._seo_context(url)
            measurement_state = "pending"
            if it.get("status") == "done":
                measurement_state = "measured" if it.get("baseline") else "done_no_baseline"
            out.append(OpportunityDTO(
                id=f"checklist:{it['id']}", source="checklist",
                type=it.get("item", ""), status=it.get("status", "pending"),
                url=url, title=page.get("title") or page.get("h1") or "",
                score=it.get("explainable_score"),
                score_breakdown=it.get("score_breakdown") or {},
                evidence=it.get("reason", ""),
                recommendation=it.get("action", ""),
                gsc_metrics=gsc, ga4_metrics=ga4 or {},
                measurement_state=measurement_state,
                created_at=it.get("created_at", ""),
                updated_at=it.get("done_at", "") or it.get("created_at", ""),
                decision_type=self._decision_type(it.get("action", "") or it.get("item", "")),
                projection=projection, top_queries=top_queries, data_freshness=freshness,
            ))
        return out

    def _content_briefs(self, status: str = "proposed", limit: int = 200) -> list[OpportunityDTO]:
        rows = self.storage.conn.execute(
            "SELECT id, url, title, intent, queries_json, gaps_json, action, "
            "priority, status, created_at FROM content_briefs WHERE status = ? "
            "ORDER BY priority DESC LIMIT ?", (status, limit),
        ).fetchall()
        out: list[OpportunityDTO] = []
        for r in rows:
            url = r[1]
            ga4 = self.storage.ga4_metrics_for_url(url) if url else None
            try:
                gaps = json.loads(r[5] or "[]")
            except (TypeError, json.JSONDecodeError):
                gaps = []
            actions = [gap.get("action", "") for gap in gaps if isinstance(gap, dict) and gap.get("action")]
            primary = r[6] or (actions[0] if actions else "")
            projection, top_queries, freshness = self._seo_context(url)
            out.append(OpportunityDTO(
                id=f"content_brief:{r[0]}", source="content_brief",
                type="content_brief", status=r[8], url=url, title=r[2] or "",
                score=float(r[7]) if r[7] is not None else None,
                evidence=f"intenção: {r[3] or ''}", recommendation=primary,
                gsc_metrics=self.storage.url_demand(url) if url else {},
                ga4_metrics=ga4 or {},
                measurement_state="proposed",
                created_at=r[9] or "", updated_at=r[9] or "",
                decision_type=self._decision_type(primary),
                related_recommendations=[action for action in actions if action != primary],
                projection=projection, top_queries=top_queries, data_freshness=freshness,
            ))
        return out

    def _backlog(self, status: str = "proposed", limit: int = 200) -> list[OpportunityDTO]:
        rows = self.storage.conn.execute(
            "SELECT id, pauta_type, title, evidence, scope, score, status, "
            "created_at FROM editorial_backlog WHERE status = ? "
            "ORDER BY score DESC LIMIT ?", (status, limit),
        ).fetchall()
        out: list[OpportunityDTO] = []
        for r in rows:
            out.append(OpportunityDTO(
                id=f"backlog:{r[0]}", source="backlog",
                type=r[1] or "", status=r[6], url="", title=r[2] or "",
                score=float(r[5]) if r[5] is not None else None,
                evidence=r[3] or "", recommendation=r[4] or "",
                measurement_state="proposed",
                created_at=r[7] or "", updated_at=r[7] or "",
            ))
        return out

    def _interlinks(self, status: str = "proposed", limit: int = 200) -> list[OpportunityDTO]:
        rows = self.storage.conn.execute(
            "SELECT id, source_url, target_url, reason, anchor, status, created_at "
            "FROM interlink_suggestions WHERE status = ? ORDER BY id DESC LIMIT ?",
            (status, limit),
        ).fetchall()
        contexts = self._page_contexts([url for row in rows for url in (row[1], row[2])])
        from ..report.interlinks import explain_interlink
        out: list[OpportunityDTO] = []
        for r in rows:
            target = r[2] or ""
            ga4 = self.storage.ga4_metrics_for_url(target) if target else None
            projection, top_queries, freshness = self._seo_context(target)
            inbound = self.storage.conn.execute(
                "SELECT COUNT(*) FROM internal_links WHERE target_url = ?", (target,)).fetchone()[0]
            outbound = self.storage.conn.execute(
                "SELECT COUNT(*) FROM internal_links WHERE source_url = ?", (r[1],)).fetchone()[0]
            explanation = explain_interlink(
                source_url=r[1] or "", target_url=target,
                source_context=contexts.get(r[1], {}), target_context=contexts.get(target, {}),
                stored_anchor=r[4] or "",
            )
            out.append(OpportunityDTO(
                id=f"interlink:{r[0]}", source="interlink",
                type="internal_link", status=r[5], url=target,
                title=f"{r[1]} → {target}",
                evidence=r[3] or "", recommendation=f"âncora: {r[4] or '(gerar)'}",
                gsc_metrics=self.storage.url_demand(target) if target else {},
                ga4_metrics=ga4 or {},
                measurement_state="proposed",
                created_at=r[6] or "", updated_at=r[6] or "",
                decision_type="internal_link", projection=projection,
                top_queries=top_queries, data_freshness=freshness,
                link_context={"source_url": r[1] or "", "target_url": target,
                              "anchor": r[4] or explanation["suggested_anchor"],
                              "target_inbound_links": inbound,
                              "source_outbound_links": outbound, **explanation},
            ))
        return out

    # -- feed unificado ------------------------------------------------------

    def feed(self, *, source: str | None = None, status: str | None = None,
             limit: int = 200) -> list[dict[str, Any]]:
        """Feed unificado, ordenado por score (desconhecido vai para o fim)."""
        if source and source not in _SOURCES:
            raise ValueError(f"fonte desconhecida: {source!r} (válidas: {_SOURCES})")
        dto: list[OpportunityDTO] = []
        if source in (None, "checklist"):
            dto.extend(self._checklist(status=status or "pending", limit=limit))
        if source in (None, "content_brief"):
            dto.extend(self._content_briefs(status=status or "proposed", limit=limit))
        if source in (None, "backlog"):
            dto.extend(self._backlog(status=status or "proposed", limit=limit))
        if source in (None, "interlink"):
            dto.extend(self._interlinks(status=status or "proposed", limit=limit))

        dto.sort(key=lambda o: (o.score is None, -(o.score or 0.0)))
        return [o.to_dict() for o in dto[:limit]]
