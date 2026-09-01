"""GA4 A4 — integração com ContentBrief, checklist e score (sem substituir GSC).

GA4 melhora o julgamento com EXPLICAÇÃO:
  * blocos de brief: organic_landing, engagement, trend, data_quality;
  * sugestões editoriais concretas pós-clique (title/snippet, resposta no topo,
    seção explicativa, links internos, atualização);
  * ajuste de confiança determinístico (nunca um quarto multiplicador opaco):
    GA4 disponível soma +0.1 à confiança, com `reason` explicado;
  * evidence_source: gsc | ga4 | combined.

Regras: nada nasce de amostra pequena ou métrica indisponível (as regras A3 já
garantem isso; aqui apenas traduzimos findings em itens de checklist).
"""

from __future__ import annotations

from typing import Any

# Ajuste de confiança por qualidade de evidência GA4 (determinístico).
_GA4_CONFIDENCE_DELTA = 0.1

# Mapeamento finding A3 -> item editorial + ação (consultiva, nunca remoção).
_FINDING_TO_ITEM = {
    "search_click_engagement_gap": {
        "item": "title_snippet_mismatch",
        "priority": "high",
        "action": ("Investigar a promessa do title/meta description versus a "
                   "entrega real da página: o Google envia cliques, mas o GA4 "
                   "não confirma sessões orgânicas equivalentes."),
        "section": "rever title e meta description (primeiros 60 caracteres)",
        "accept": "title/snippet refletem com precisão o conteúdo que a query promete",
    },
    "organic_low_engagement": {
        "item": "main_answer_missing_at_top",
        "priority": "high",
        "action": ("Revisar se a resposta principal aparece no PRIMEIRO bloco de "
                   "conteúdo: leitores que chegam do Google estão saindo sem "
                   "engajar — a promessa do snippet não se confirma no topo."),
        "section": "primeiro bloco de conteúdo (acima da dobra)",
        "accept": "resposta direta à intenção nos primeiros ~150 palavras",
    },
    "engagement_declining": {
        "item": "content_stale_update",
        "priority": "medium",
        "action": ("Revisar atualidade e aderência à intenção: o tráfego orgânico "
                   "vem caindo entre janelas equivalentes; conteúdo desatualizado "
                   "é a hipótese mais provável, não a única."),
        "section": "rever datas, fatos e seções que possam ter envelhecido",
        "accept": "conteúdo atualizado e alinhado à intenção atual da query",
    },
}


def ga4_brief_blocks(*, gsc: dict[str, Any] | None,
                     ga4: dict[str, Any] | None,
                     ga4_prev: dict[str, Any] | None = None,
                     findings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Blocos GA4 para o brief: organic_landing, engagement, trend, data_quality."""
    blocks: dict[str, Any] = {}
    if ga4:
        blocks["organic_landing"] = {
            "sessions": ga4.get("sessions"),
            "engaged_sessions": ga4.get("engaged_sessions"),
            "engagement_rate": ga4.get("engagement_rate"),
            "key_events": ga4.get("key_events"),
            "window_start": ga4.get("window_start"),
            "window_end": ga4.get("window_end"),
        }
        blocks["engagement"] = {
            "sessions": ga4.get("sessions"),
            "engagement_rate": ga4.get("engagement_rate"),
            "measurement_status": ga4.get("measurement_status"),
        }
    if ga4 and ga4_prev:
        blocks["trend"] = {
            "sessions_a": ga4_prev.get("sessions"),
            "sessions_b": ga4.get("sessions"),
            "engagement_rate_a": ga4_prev.get("engagement_rate"),
            "engagement_rate_b": ga4.get("engagement_rate"),
        }
    if gsc or ga4:
        sources = []
        if gsc:
            sources.append("gsc")
        if ga4:
            sources.append("ga4")
        blocks["data_quality"] = {
            "evidence_source": "combined" if len(sources) == 2 else sources[0],
            "measurement_status": (ga4 or {}).get("measurement_status", "missing"),
            "gsc_impressions": (gsc or {}).get("impressions"),
            "gsc_clicks": (gsc or {}).get("clicks"),
            "findings": findings or [],
        }
    return blocks


def editorial_suggestions(*, gsc: dict[str, Any] | None,
                          ga4: dict[str, Any] | None,
                          findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Traduz findings A3 em itens de checklist consultivos (nunca remoção)."""
    if not ga4 or ga4.get("measurement_status") != "available":
        return []
    suggestions: list[dict[str, Any]] = []
    for finding in findings:
        rule = finding.get("rule")
        mapping = _FINDING_TO_ITEM.get(rule)
        if not mapping:
            continue
        evidence = _evidence_text(finding, gsc)
        suggestions.append({
            "item": mapping["item"],
            "priority": mapping["priority"],
            "evidence": evidence,
            "action": mapping["action"],
            "evidence_source": "combined" if gsc else "ga4",
            "window": finding.get("window"),
            "suggested_section": mapping["section"],
            "acceptance_criteria": mapping["accept"],
            "ga4_rule": rule,
        })
    return suggestions


def _evidence_text(finding: dict[str, Any], gsc: dict[str, Any] | None) -> str:
    rule = finding.get("rule")
    ev = finding.get("evidence", {})
    if rule == "organic_low_engagement":
        return (f"comportamento pós-clique: {ev.get('ga4_organic_sessions'):.0f} sessões "
                f"orgânicas com taxa de engajamento {ev.get('engagement_rate'):.0%} "
                f"(limiar {finding['thresholds']['low_engagement_rate']:.0%}), apesar de "
                f"{ev.get('gsc_impressions'):.0f} impressões no GSC")
    if rule == "engagement_declining":
        return (f"engajamento em queda: sessões {ev.get('sessions_a'):.0f} → "
                f"{ev.get('sessions_b'):.0f} entre janelas equivalentes "
                f"({ev.get('delta_pct'):+.1f}%)")
    if rule == "search_click_engagement_gap":
        return (f"gap cliques→sessões: {ev.get('gsc_clicks'):.0f} cliques no GSC mas "
                f"apenas {ev.get('ga4_organic_sessions'):.0f} sessões orgânicas no GA4")
    return str(finding)


def confidence_delta_for_ga4(*, ga4: dict[str, Any] | None,
                             ga4_prev: dict[str, Any] | None = None,
                             findings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Ajuste de confiança EXPLICADO (não multiplicador opaco).

    GA4 disponível (measurement_status=available): +0.1 com motivo. Finding
    presente reforça o motivo. NUNCA reduz a confiança abaixo de 0.
    """
    if not ga4 or ga4.get("measurement_status") != "available":
        return {"delta": 0.0, "reason": "sem evidência GA4 disponível"}
    reasons = ["evidência pós-clique GA4 disponível (sessões orgânicas)"]
    if ga4_prev and ga4_prev.get("sessions") is not None:
        reasons.append("tendência entre duas janelas comparável")
    if findings:
        rules = ", ".join(sorted({f.get("rule", "") for f in findings if f.get("rule")}))
        reasons.append(f"regras A3 ativas: {rules}")
    return {"delta": _GA4_CONFIDENCE_DELTA, "reason": "; ".join(reasons)}
