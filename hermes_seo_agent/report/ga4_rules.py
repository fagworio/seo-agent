"""GA4 A3 — regras determinísticas de oportunidade (consultivas, alta confiança).

Três tipos apenas, cada um com evidência, janela, amostra, limiar, status do
dado, ação sugerida e limitações. NENHUMA regra dispara com amostra pequena ou
métrica indisponível (measurement_status != available => sem finding).

  * organic_low_engagement:   GSC impressions >= 500, GA4 organic sessions >= 50
                              e engagement_rate abaixo do limiar (default 0.40);
  * engagement_declining:     duas janelas equivalentes, sessions >= amostra
                              mínima na base, queda >= -30% de sessions;
  * search_click_engagement_gap: GSC cliques relevantes (>= 20) e GA4 orgânico
                              fraco (sessions < cliques * 0.5) — promessa do
                              title/snippet versus entrega pós-clique.

low_value_page continua sendo decisão humana: nunca é gerada aqui.
"""

from __future__ import annotations

from typing import Any

# Limiares default (determinísticos, explicáveis).
MIN_GSC_IMPRESSIONS = 500
MIN_GA4_SESSIONS = 50
LOW_ENGAGEMENT_RATE = 0.40          # taxa de engajamento abaixo disso = low
DECLINE_THRESHOLD_PCT = -30.0       # queda de sessions entre janelas
MIN_SESSIONS_BASE = 50              # amostra mínima na janela base do trend
MIN_GSC_CLICKS_GAP = 20
GAP_SESSION_PER_CLICK = 0.5         # sessions < cliques * 0.5 => entrega fraca


def organic_low_engagement(*, gsc_impressions: float | None,
                           ga4_sessions: float | None,
                           engagement_rate: float | None,
                           measurement_status: str,
                           gsc_impressions_threshold: float = MIN_GSC_IMPRESSIONS,
                           min_sessions: float = MIN_GA4_SESSIONS,
                           low_rate: float = LOW_ENGAGEMENT_RATE) -> dict[str, Any] | None:
    """Página com volume no Google mas engajamento fraco pós-clique."""
    if gsc_impressions is None or ga4_sessions is None or engagement_rate is None:
        return None
    if measurement_status != "available":
        return None
    if gsc_impressions < gsc_impressions_threshold or ga4_sessions < min_sessions:
        return None
    if engagement_rate >= low_rate:
        return None
    return {
        "rule": "organic_low_engagement",
        "evidence": {
            "gsc_impressions": gsc_impressions,
            "ga4_organic_sessions": ga4_sessions,
            "engagement_rate": engagement_rate,
        },
        "thresholds": {
            "gsc_impressions": gsc_impressions_threshold,
            "min_sessions": min_sessions,
            "low_engagement_rate": low_rate,
        },
        "measurement_status": measurement_status,
        "suggested_action": "revisar intenção, abertura e estrutura da página",
        "limitations": "engajamento agregado inclui retorno de leitores; CTR alto "
                       "com queda pós-clique sugere promessa x entrega — não prova causa.",
    }


def engagement_declining(*, sessions_a: float | None, sessions_b: float | None,
                         engagement_rate_a: float | None,
                         engagement_rate_b: float | None,
                         measurement_status: str,
                         min_sessions: float = MIN_SESSIONS_BASE,
                         decline_pct: float = DECLINE_THRESHOLD_PCT) -> dict[str, Any] | None:
    """Queda relevante de sessões entre duas janelas equivalentes."""
    if sessions_a is None or sessions_b is None:
        return None
    if measurement_status != "available":
        return None
    if sessions_a < min_sessions:
        return None
    delta_pct = (sessions_b - sessions_a) / sessions_a * 100.0
    if delta_pct > decline_pct:
        return None
    return {
        "rule": "engagement_declining",
        "evidence": {
            "sessions_a": sessions_a,
            "sessions_b": sessions_b,
            "engagement_rate_a": engagement_rate_a,
            "engagement_rate_b": engagement_rate_b,
            "delta_pct": round(delta_pct, 1),
        },
        "thresholds": {"min_sessions": min_sessions,
                       "decline_pct": decline_pct},
        "measurement_status": measurement_status,
        "suggested_action": "revisar atualidade e aderência à intenção de busca",
        "limitations": "janelas curtas sofrem sazonalidade; correlação com datas "
                       "públicas (lançamentos, séries) deve ser checada antes de agir.",
    }


def search_click_engagement_gap(*, gsc_clicks: float | None,
                                ga4_sessions: float | None,
                                engagement_rate: float | None,
                                measurement_status: str,
                                min_clicks: float = MIN_GSC_CLICKS_GAP,
                                session_per_click: float = GAP_SESSION_PER_CLICK) -> dict[str, Any] | None:
    """Cliques relevantes no GSC mas pouca sessão orgânica no GA4."""
    if gsc_clicks is None or ga4_sessions is None:
        return None
    if measurement_status != "available":
        return None
    if gsc_clicks < min_clicks:
        return None
    if ga4_sessions >= gsc_clicks * session_per_click:
        return None
    return {
        "rule": "search_click_engagement_gap",
        "evidence": {
            "gsc_clicks": gsc_clicks,
            "ga4_organic_sessions": ga4_sessions,
            "engagement_rate": engagement_rate,
        },
        "thresholds": {"min_gsc_clicks": min_clicks,
                       "session_per_click": session_per_click},
        "measurement_status": measurement_status,
        "suggested_action": "investigar promessa do title/snippet versus entrega "
                            "da página (revisar title, meta description, primeiro "
                            "bloco de conteúdo)",
        "limitations": "GSC e GA4 medem fenômenos distintos (cliques vs sessões); "
                       "definição de sessão orgânica pode divergir entre "
                       "plataformas — o gap é um sinal, não uma verdade absoluta.",
    }


def evaluate_url(*, gsc: dict[str, Any] | None, ga4: dict[str, Any] | None,
                 ga4_prev: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Aplica as três regras para uma URL, retornando findings com contexto."""
    findings: list[dict[str, Any]] = []
    if not gsc or not ga4:
        return findings  # sem cruzamento GSC×GA4 não há regra segura

    gsc_impressions = gsc.get("impressions")
    gsc_clicks = gsc.get("clicks")
    status = ga4.get("measurement_status", "missing")

    low = organic_low_engagement(
        gsc_impressions=gsc_impressions,
        ga4_sessions=ga4.get("sessions"),
        engagement_rate=ga4.get("engagement_rate"),
        measurement_status=status,
    )
    if low:
        low["window"] = ga4.get("window_start")
        findings.append(low)

    if ga4_prev:
        dec = engagement_declining(
            sessions_a=ga4_prev.get("sessions"),
            sessions_b=ga4.get("sessions"),
            engagement_rate_a=ga4_prev.get("engagement_rate"),
            engagement_rate_b=ga4.get("engagement_rate"),
            measurement_status=status,
        )
        if dec:
            dec["window"] = f"{ga4_prev.get('window_start')} → {ga4.get('window_start')}"
            findings.append(dec)

    gap = search_click_engagement_gap(
        gsc_clicks=gsc_clicks,
        ga4_sessions=ga4.get("sessions"),
        engagement_rate=ga4.get("engagement_rate"),
        measurement_status=status,
    )
    if gap:
        gap["window"] = ga4.get("window_start")
        findings.append(gap)

    return findings
