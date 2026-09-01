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

    Hoje nenhum adaptador real está implementado (M4 é o CONTRATO); quando um
    provedor for autorizado (API key + quota + custo), registre aqui.
    """
    return NoopProvider(config)
