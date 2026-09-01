"""M0 — Contrato operacional e qualidade de dados.

Padroniza `data_status` e a proveniência de TODAS as métricas e sugestões:

  * data_status: available | partial | missing | invalid (uma fonte ausente
    NUNCA aparece como métrica zero nem gera sugestão falsa);
  * proveniência: fonte, janela, data de coleta, cobertura e limitações.

Mapeia os status legados (ex.: measurement_status do GA4 que usava
available|missing|invalid|partial) para o vocabulário canônico.
"""

from __future__ import annotations

from typing import Any

# Vocabulário canônico de qualidade de dados (ordem de severidade).
DATA_STATUSES = ("available", "partial", "missing", "invalid")

# Sinônimos de fontes internas (para proveniência consistente).
SOURCES = ("gsc", "ga4", "sitemap", "wordpress", "crux", "pagespeed",
           "external", "corpus", "checklist", "backlog")

# mapeamento de status legados -> canônico
_STATUS_ALIASES = {
    "ok": "available",
    "complete": "available",
    "healthy": "available",
    "valid": "available",
    "done": "available",
    "measured": "available",
    "partial": "partial",
    "degraded": "partial",
    "empty": "missing",
    "unavailable": "missing",
    "absent": "missing",
    "not_collected": "missing",
    "not_configured": "missing",
    "failed": "invalid",
    "error": "invalid",
    "invalid": "invalid",
    "missing": "missing",
    "available": "available",
}


def normalize_status(value: Any) -> str:
    """Normaliza qualquer status legado para o vocabulário canônico."""
    if value is None:
        return "missing"
    key = str(value).strip().lower()
    return _STATUS_ALIASES.get(key, "missing" if key in {"", "none"} else "invalid")


def merge_status(*statuses: Any) -> str:
    """Combina status de múltiplas fontes.

    Regra: qualquer invalid -> invalid; senão qualquer missing -> missing;
    senão qualquer partial -> partial; senão available.
    """
    norm = [normalize_status(s) for s in statuses]
    if "invalid" in norm:
        return "invalid"
    if "missing" in norm:
        return "missing"
    if "partial" in norm:
        return "partial"
    return "available"


def provenance(*, source: str, window_start: str = "", window_end: str = "",
               collected_at: str = "", coverage: float | None = None,
               limitations: str = "", data_status: str = "available",
               extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Bloco de proveniência padrão para métricas e sugestões."""
    if source not in SOURCES:
        raise ValueError(f"fonte desconhecida: {source!r} (válidas: {SOURCES})")
    block: dict[str, Any] = {
        "source": source,
        "data_status": normalize_status(data_status),
        "window": {"start": window_start, "end": window_end} if (window_start or window_end) else None,
        "collected_at": collected_at,
        "coverage": coverage,
        "limitations": limitations,
    }
    if extra:
        block.update(extra)
    return block


def attach_provenance(metric: dict[str, Any], *, source: str, **kw: Any) -> dict[str, Any]:
    """Adiciona proveniência a um dict de métricas (in-place-friendly clone)."""
    return {**metric, "provenance": provenance(source=source, **kw)}
