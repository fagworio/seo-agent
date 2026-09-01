"""M4 — Inteligência externa, opcional e desacoplada.

MarketIntelligenceProvider: contrato para provedores de keywords/SERP
(Ubersuggest, DataForSEO, Google Keyword Planner, Google Trends, …).

Regras M4:
  * nenhum provedor externo vira dependência obrigatória;
  * custo, quota, data e origem são gravados em CADA evidência;
  * resultados externos NUNCA ignoram a checagem contra o corpus interno;
  * uma keyword externa gera um CANDIDATO de pesquisa, não uma pauta automática.

O provider base é um adaptador vazio (None); cada provedor implementa os
métodos do contrato. Evidências externas entram com data_status e proveniência
(M0) e só geram candidatos após cruzar com o corpus (M2).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..report.data_status import provenance

# custo por chamada (centavos) declarado pelo adaptador; 0 = sem custo informado
# quota: chaves de limite consumidas/devolvidas pelo provedor

_METHODS = ("keyword_metrics", "keyword_suggestions", "competitor_gap",
            "serp_snapshot", "trend_signal")


class MarketIntelligenceProvider(ABC):
    """Contrato de um provedor externo (um adaptador por provedor).

    Subclasses DEVEM preencher `name` e `cost_per_call_cents`, e podem
    implementar qualquer subconjunto de métodos — os não implementados
    retornam None (fonte ausente, nunca zero).
    """

    name: str = "base"
    cost_per_call_cents: int = 0
    config_key: str = ""             # chave de config usada (ex.: DATAFORSEO_KEY)

    def __init__(self, config: Any):
        self.config = config

    # -- contrato ------------------------------------------------------------

    @abstractmethod
    def keyword_metrics(self, keyword: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Métricas de keywords (volume, dificuldade, CPC, tendência)."""

    @abstractmethod
    def keyword_suggestions(self, seed: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Sugestões de keywords relacionadas a um seed."""

    @abstractmethod
    def competitor_gap(self, topic: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Keywords onde concorrentes rankeiam e o site não."""

    @abstractmethod
    def serp_snapshot(self, keyword: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Snapshot de resultados SERP para uma keyword."""

    @abstractmethod
    def trend_signal(self, keyword: str) -> dict[str, Any]:
        """Sinal de tendência (crescente/estável/decrescente)."""

    # -- infra comum ---------------------------------------------------------

    def _evidence(self, keyword: str, *, method: str, rows: list[dict[str, Any]],
                  quota: dict[str, Any] | None = None) -> dict[str, Any]:
        """Envolve o resultado com origem, custo, quota, data e data_status."""
        from ..storage.db import _now
        return {
            "provider": self.name,
            "method": method,
            "keyword": keyword,
            "rows": rows,
            "cost_cents": self.cost_per_call_cents if rows else 0,
            "quota": quota or {},
            "collected_at": _now(),
            "data_status": "available" if rows else "missing",
        }

    def check_corpus(self, storage: Any, keyword: str, *, limit: int = 10
                     ) -> dict[str, Any]:
        """Checagem OBRIGATÓRIA contra o corpus interno (M4/M2).

        Retorna cobertura interna para a keyword: docs via FTS + entidades.
        Resultado externo que não passa por aqui NUNCA vira pauta.
        """
        docs = storage.corpus_search(keyword, limit=limit)
        return {
            "keyword": keyword,
            "internal_docs": len(docs),
            "internal_urls": [d["url"] for d in docs],
            "data_status": "available" if docs else "missing",
            "limitations": "documentos internos casam lexicalmente; não é prova de autoridade",
        }

    def candidate(self, storage: Any, keyword: str, *, method: str,
                  external: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Uma keyword externa vira um CANDIDATO de pesquisa (nunca pauta).

        Combina evidência externa (se houver) + checagem interna. Se o corpus
        já cobre a keyword, o candidato sugere expandir/interlink; senão,
        new_content — sempre para REVISÃO HUMANA.
        """
        corpus = self.check_corpus(storage, keyword)
        candidate: dict[str, Any] = {
            "keyword": keyword,
            "source": self.name,
            "method": method,
            "internal": corpus,
            "corpus_covers": corpus["internal_docs"] > 0,
            "suggested_action": "expand_existing" if corpus["internal_docs"] > 0
                                else "new_content",
            "needs_human_review": True,
        }
        if external is not None:
            candidate["external_evidence"] = self._evidence(
                keyword, method=method, rows=external)
        return candidate


class NoopProvider(MarketIntelligenceProvider):
    """Provedor vazio: quando nenhum adaptador está configurado.

    Todos os métodos retornam lista vazia/None com data_status=missing —
    uma fonte externa ausente NUNCA gera métrica zero nem candidato.
    """

    name = "none"
    config_key = ""

    def __init__(self, config: Any):
        super().__init__(config)

    def keyword_metrics(self, keyword, *, limit=10):
        return []

    def keyword_suggestions(self, seed, *, limit=20):
        return []

    def competitor_gap(self, topic, *, limit=10):
        return []

    def serp_snapshot(self, keyword, *, limit=10):
        return []

    def trend_signal(self, keyword):
        return {}


def get_provider(config: Any) -> MarketIntelligenceProvider:
    """Factory: retorna o adaptador configurado ou NoopProvider.

    Google Trends (alpha) é o primeiro adaptador real: usa a mesma chave de
    API do Google (GOOGLE_API_KEY / TRENDS_API_KEY), custo por chamada 0,
    quota diária da API. Não é dependência obrigatória — sem chave, Noop.
    """
    trends_key = getattr(config, "trends_api_key", "") or getattr(
        config, "pagespeed_api_key", "") or ""
    if trends_key:
        return TrendsProvider(config)
    return NoopProvider(config)


class TrendsProvider(MarketIntelligenceProvider):
    """Google Trends Data API (alpha) — interesse relativo ao longo do tempo.

    Discovery: https://trends.googleapis.com/$discovery/rest?version=v1beta
    Base: https://www.googleapis.com/trends/v1beta
    Métodos reais (GET, API key):
      * getGraph:          /graph  ?terms=&restrictions.geo=&restrictions.startDate=
                                   &restrictions.endDate=  -> {lines:[{term,points}]}
      * getTopQueries:     /topQueries   ?term=&restrictions.geo=&restrictions.startDate=
      * getRisingQueries:  /risingQueries?term=&restrictions.geo=&restrictions.startDate=

    Trends NÃO dá volume absoluto (interesse relativo 0-100). Evidência externa
    entra como sinal relativo + checagem obrigatória contra o corpus (M4).
    """

    name = "google_trends"
    cost_per_call_cents = 0
    config_key = "GOOGLE_API_KEY / TRENDS_API_KEY"

    _BASE = "https://www.googleapis.com/trends/v1beta"
    _COUNTRY = "BR"

    def __init__(self, config: Any):
        super().__init__(config)
        from ..connectors.base import HttpClient
        self._http = HttpClient(timeout=getattr(config, "http_timeout", 15.0))
        self._key = getattr(config, "trends_api_key", "") or getattr(
            config, "pagespeed_api_key", "") or ""

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        from ..connectors.base import ConnectorError
        url = f"{self._BASE}{path}"
        params = {**params, "key": self._key}
        response = self._http.get(url, params=params)
        if response.status_code != 200:
            raise ConnectorError(
                f"Google Trends API failed: HTTP {response.status_code} "
                f"{response.text[:200]}")
        data = response.json()
        if not isinstance(data, dict):
            raise ConnectorError("Google Trends API returned an invalid payload")
        return data

    def _window(self) -> tuple[str, str]:
        import datetime
        end = datetime.date.today()
        start = end - datetime.timedelta(days=90)
        return start.strftime("%Y-%m"), end.strftime("%Y-%m")

    def _timeline(self, keyword: str) -> list[dict[str, Any]]:
        """Interesse relativo por ponto no tempo (graph)."""
        start, end = self._window()
        data = self._get("/graph", {
            "terms": keyword,
            "restrictions.geo": self._COUNTRY,
            "restrictions.startDate": start,
            "restrictions.endDate": end,
        })
        return _parse_timeline(data, keyword)

    # -- contrato M4 ---------------------------------------------------------

    def keyword_metrics(self, keyword: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Métricas relativas: interesse por ponto, média, máximo e tendência."""
        points = self._timeline(keyword)
        if not points:
            return []
        values = [p["value"] for p in points]
        avg = sum(values) / len(values) if values else 0.0
        return [{
            "keyword": keyword,
            "relative_interest_avg": round(avg, 1),
            "relative_interest_max": round(max(values), 1),
            "points": len(points),
            "period": "90d",
            "note": "interesse relativo (0-100), não volume absoluto",
        }]

    def keyword_suggestions(self, seed: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Top queries relacionadas (getTopQueries) — sinal de demanda."""
        start, end = self._window()
        try:
            data = self._get("/topQueries", {
                "term": seed,
                "restrictions.geo": self._COUNTRY,
                "restrictions.startDate": start,
                "restrictions.endDate": end,
            })
        except Exception:
            return []
        rows = []
        for item in (data.get("item") or [])[:limit]:
            title = item.get("title")
            value = item.get("value")
            if title:
                try:
                    rows.append({"keyword": title, "relative_interest": float(value)})
                except (TypeError, ValueError):
                    rows.append({"keyword": title, "relative_interest": None})
        return rows

    def competitor_gap(self, topic: str, *, limit: int = 10) -> list[dict[str, Any]]:
        return []  # requer dados SERP de concorrentes (outro adaptador)

    def serp_snapshot(self, keyword: str, *, limit: int = 10) -> list[dict[str, Any]]:
        return []  # requer provedor SERP

    def trend_signal(self, keyword: str) -> dict[str, Any]:
        """Sinal de tendência: metade atual vs metade anterior da série 90d."""
        points = self._timeline(keyword)
        if len(points) < 4:
            return {"trend": "unknown", "delta_pct": None,
                    "note": "pontos insuficientes para tendência"}
        mid = len(points) // 2
        a = sum(p["value"] for p in points[:mid]) / max(mid, 1)
        b = sum(p["value"] for p in points[mid:]) / max(len(points) - mid, 1)
        delta = round((b - a) / a * 100, 1) if a else None
        trend = "stable"
        if delta is not None:
            if delta <= -20:
                trend = "declining"
            elif delta >= 20:
                trend = "growing"
        return {"trend": trend, "delta_pct": delta, "points": len(points),
                "period": "90d"}


def _parse_timeline(data: dict[str, Any], keyword: str) -> list[dict[str, Any]]:
    """Extrai pontos de interesse de respostas da Trends (formato tolerante).

    Schema oficial (getGraph): {lines: [{term, points: [{date, value}]}]}.
    Também reconhece formatos legados (timeline/interest_over_time) e qualquer
    estrutura inesperada -> [] (a evidência registra data_status=missing).
    """
    points: list[dict[str, Any]] = []

    # formato oficial: graph lines — respeita o filtro de termo e NÃO cai no
    # fallback se a linha não é do termo (linha de outro termo = vazio real).
    lines = data.get("lines")
    if isinstance(lines, list):
        for line in lines:
            if not isinstance(line, dict):
                continue
            term = line.get("term")
            if term and keyword and keyword.lower() not in str(term).lower():
                continue
            for p in line.get("points") or []:
                if isinstance(p, dict) and p.get("date") is not None \
                        and p.get("value") is not None:
                    try:
                        points.append({"date": str(p["date"])[:10],
                                       "value": float(p["value"])})
                    except (TypeError, ValueError):
                        continue
        points.sort(key=lambda p: p["date"])
        return points

    candidates: list[Any] = []

    def _walk(value: Any) -> None:
        if isinstance(value, dict):
            for key in ("timeline", "interest_over_time", "interest", "points"):
                if key in value and isinstance(value[key], list):
                    candidates.append(value[key])
            for v in value.values():
                _walk(v)
        elif isinstance(value, list):
            candidates.append(value)
            for v in value:
                _walk(v)

    _walk(data)
    for candidate in candidates:
        for item in candidate:
            if not isinstance(item, dict):
                continue
            date = item.get("date") or item.get("time") or item.get("dateTime")
            value = item.get("value") or item.get("interest")
            if date is not None and value is not None:
                try:
                    points.append({"date": str(date)[:10],
                                   "value": float(value)})
                except (TypeError, ValueError):
                    continue
        if points:
            break
    points.sort(key=lambda p: p["date"])
    return points

