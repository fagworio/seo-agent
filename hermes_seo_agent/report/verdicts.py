"""Veredito MULTIAXIAL + separação medição → diagnóstico → decisão (SEO-INC-012).

Ordem correta (evita salto causal):

  MEASUREMENT  o que os dados mostram (veredito + eixos independentes)
  DIAGNOSIS    o que é explicável (alinhamento, anomalia de CTR) — códigos
               determinísticos, nunca inferência de causa externa
  DECISION     o que fazer (actionability + ação recomendada)

Por que não basta `verdict == "regressed"`: regressão significa apenas que
algum indicador de visibilidade/aquisição piorou — não que o título causou.
Perda de posição, sazonalidade, concorrência, atualização do Google, mudança
de intenção e dezenas de outras causas produzem o mesmo sinal.

Tolerância: relativa (5% por padrão) com piso absoluto por métrica. O piso
existe porque sem ele "+1 impressão" viraria movimento (a versão anterior
perdia o `before` no fluxo integrado e comparava em termos absolutos).
"""

from __future__ import annotations

from typing import Any

UP, DOWN, FLAT, MIXED, UNKNOWN = "up", "down", "flat", "mixed", "unknown"

_TOL_REL = 0.05          # 5% de variação mínima para não tratar ruído como movimento
_FLOOR = {
    "impressions": 10.0,   # 10 impressões de diferença não é movimento
    "clicks": 1.0,
    "sessions": 1.0,
    "ctr": 0.002,          # 0,2 ponto percentual
    "engagement_rate": 0.05,  # 5 pontos percentuais
    "position": 0.5,       # meia posição média
}


def axis_of(delta: Any, *, before: Any = None, metric: str = "",
            invert: bool = False) -> str:
    """Classifica um delta em up/down/flat/unknown.

    O limite é o MAIOR entre a tolerância relativa (5% da base) e o piso
    absoluto da métrica — assim base pequena não gera movimento falso.
    `invert=True` para métricas em que menor é melhor (posição).
    """
    if delta is None:
        return UNKNOWN
    try:
        v = float(delta)
    except (TypeError, ValueError):
        return UNKNOWN
    if invert:
        v = -v
    try:
        ref = abs(float(before)) if before not in (None, "") else 0.0
    except (TypeError, ValueError):
        ref = 0.0
    piso = _FLOOR.get(metric, 0.0)
    limite = max(ref * _TOL_REL, piso) if ref else piso
    if v > limite:
        return UP
    if v < -limite:
        return DOWN
    return FLAT


def merge_axes(*signals: str) -> str:
    """Combina sinais PRESERVANDO o conflito (up + down => mixed).

    A agregação anterior deixava `down` dominar: impressões caindo + posição
    melhorando virava `visibility=down`, destruindo a evidência de melhora.
    """
    known = {s for s in signals if s != UNKNOWN}
    if not known:
        return UNKNOWN
    if UP in known and DOWN in known:
        return MIXED
    if DOWN in known:
        return DOWN
    if UP in known:
        return UP
    return FLAT


def multiaxial_verdict(gsc: dict[str, Any], ga4: dict[str, Any]) -> tuple[str, dict[str, str]]:
    """Veredito composto + eixos independentes (visibility/acquisition/engagement).

    Regras (determinísticas):
      regressed     vis ou acq down e NENHUMA melhora em nenhum eixo
      mixed         melhora e piora em eixos diferentes (ex: vis down + acq up)
      traffic_up    acquisition up (e sem down estrutural)
      visibility_up visibility up (aquisição não subiu — não afirmamos "sem clique")
      engagement_up só engajamento subiu
      no_change     tudo estável
    """
    vis = merge_axes(
        axis_of(gsc.get("impressions_delta"), before=gsc.get("impressions_before"),
                metric="impressions"),
        axis_of(gsc.get("position_delta"), before=gsc.get("position_before"),
                metric="position", invert=True),
    )
    acq = merge_axes(
        axis_of(gsc.get("clicks_delta"), before=gsc.get("clicks_before"),
                metric="clicks"),
        axis_of(gsc.get("ctr_delta"), before=gsc.get("ctr_before"), metric="ctr"),
    )
    eng = merge_axes(
        axis_of(ga4.get("sessions_delta"), before=ga4.get("sessions_before"),
                metric="sessions"),
        axis_of(ga4.get("engagement_rate_delta"),
                before=ga4.get("engagement_rate_before"), metric="engagement_rate"),
    )
    axes = {"visibility": vis, "acquisition": acq, "engagement": eng}

    if vis == UNKNOWN and acq == UNKNOWN and eng == UNKNOWN:
        return "insufficient_data", axes
    if (vis == DOWN or acq == DOWN) and UP not in (vis, acq, eng):
        return "regressed", axes
    # melhora num eixo e piora em outro: não é sucesso nem fracasso
    if (vis == DOWN and acq == UP) or (acq == DOWN and vis == UP):
        return "mixed", axes
    if acq == UP:
        return "traffic_up", axes
    if vis == UP:
        return "visibility_up", axes
    if eng == UP and vis != DOWN and acq != DOWN:
        return "engagement_up", axes
    if MIXED in (vis, acq, eng):
        return "mixed", axes
    if vis == FLAT and acq == FLAT and eng in (FLAT, UNKNOWN):
        return "no_change", axes
    return "mixed", axes


# --------------------------------------------------------------------------
# DIAGNOSIS — códigos determinísticos (substituem strings soltas)
# --------------------------------------------------------------------------

def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def diagnosis_codes(gsc: dict[str, Any], ga4: dict[str, Any], *,
                    query_aligned: bool | None = None,
                    baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    """Códigos de diagnóstico — o que é OBSERVÁVEL, sem inferir causa externa.

    `cause` permanece "undetermined" por contrato: a API do Search Console não
    expõe recorte de busca generativa (AI Overviews/AI Mode), então possível
    influência NÃO é influência confirmada.
    """
    codes: list[str] = []

    if query_aligned is True:
        codes.append("query_title_aligned")
    elif query_aligned is False:
        codes.append("query_title_gap")

    pos = gsc.get("position_after")
    if pos is None:
        pos = gsc.get("position_before")
    impressions = max(_f(gsc.get("impressions_after")), _f(gsc.get("impressions_before")))
    ctr_after = gsc.get("ctr_after")
    # CTR julgado contra o BASELINE DO PROPRIO SITE (nunca benchmark externo):
    #   ctr_below_baseline  - abaixo do P10 do proprio contexto
    #   ctr_zero_sitewide   - o segmento inteiro captura ~0 (padrao do site,
    #                         nao da pagina: investigar estrutural, nao titulo)
    if ctr_after is not None and pos is not None:
        from .baseline import ctr_verdict as _ctr_verdict
        _vb = _ctr_verdict(None, position=pos, impressions=impressions,
                           ctr=ctr_after, baseline=baseline) if baseline else None
        _bucket = (_vb or {}).get("bucket") or {}
        if _vb and _vb.get("verdict") == "below_p10":
            codes.append("ctr_below_baseline")
        elif (_f(ctr_after) <= 0.002 and _f(_bucket.get("p50")) <= 0.002
              and int(_bucket.get("n") or 0) >= 5):
            codes.append("ctr_zero_sitewide")
        elif baseline is None and _f(ctr_after) < 0.01 and impressions >= 100 and _f(pos) <= 10:
            # sem baseline disponivel: mantem o criterio conservador anterior
            codes.append("ctr_anomaly")

    if _f(gsc.get("impressions_delta")) < 0 and _f(gsc.get("impressions_pct")) <= -20:
        codes.append("visibility_loss")
    if _f(gsc.get("clicks_delta")) < 0 and _f(gsc.get("clicks_pct")) <= -20:
        codes.append("traffic_loss")
    if _f(gsc.get("position_delta")) > 1:
        codes.append("ranking_loss")
    if _f(ga4.get("engagement_rate_pct")) <= -20:
        codes.append("engagement_loss")
    if impressions < 100 and not codes:
        codes.append("insufficient_data")
    if not codes:
        codes.append("unknown_cause")

    return {
        "codes": codes,
        "ctr_anomaly": bool({"ctr_anomaly", "ctr_below_baseline",
                             "ctr_zero_sitewide"} & set(codes)),
        "query_alignment": ("ok" if "query_title_aligned" in codes else
                            "gap" if "query_title_gap" in codes else "unknown"),
        # NUNCA inferir causa externa: a API não expõe o recorte de IA
        "cause": "undetermined",
        "confidence": "low",
    }


# --------------------------------------------------------------------------
# DECISION — o que fazer (nunca "rever título" apenas por ter regredido)
# --------------------------------------------------------------------------

def recommend(verdict: str, axes: dict[str, str], diag: dict[str, Any]) -> dict[str, Any]:
    """Ação recomendada a partir de medição + diagnóstico."""
    codes = set(diag.get("codes") or [])
    vis = axes.get("visibility")

    if verdict == "insufficient_data":
        return {"actionability": "monitor", "recommended_action": "gather_more_data",
                "review_required": False,
                "rationale": "sem base de comparação suficiente"}

    # Anomalia de CTR com query alinhada e visibilidade não pior: NÃO mexer
    if "ctr_zero_sitewide" in codes:
        return {"actionability": "investigate", "recommended_action": "no_title_change",
                "review_required": True,
                "rationale": "CTR do segmento inteiro ~0 (padrão do site): "
                             "investigar snippet/estrutura, não título"}
    if (codes & {"ctr_anomaly", "ctr_below_baseline"}) and \
            "query_title_aligned" in codes and vis in (UP, FLAT):
        return {"actionability": "monitor", "recommended_action": "no_title_change",
                "review_required": False,
                "rationale": "alinhamento ok; CTR abaixo do baseline do próprio contexto"}

    # Perda de tráfego COM gap de query/título: aí sim o título é candidato
    if "traffic_loss" in codes and "query_title_gap" in codes:
        return {"actionability": "title_review", "recommended_action": "review_title",
                "review_required": True,
                "rationale": "perda de tráfego somada a gap query/título"}

    # Piora de posição/visibilidade sem gap: investigar causa, não reescrever
    if verdict == "regressed":
        return {"actionability": "review", "recommended_action": "investigate_cause",
                "review_required": True,
                "rationale": "regressão sem causa determinada — não assumir título"}

    if verdict in ("visibility_up", "traffic_up", "engagement_up"):
        return {"actionability": "monitor", "recommended_action": "keep",
                "review_required": False, "rationale": "resultado não-negativo"}
    if verdict == "mixed":
        return {"actionability": "monitor", "recommended_action": "monitor_28d",
                "review_required": False,
                "rationale": "sinais divergentes entre eixos"}
    return {"actionability": "monitor", "recommended_action": "keep",
            "review_required": False, "rationale": "sem movimento relevante"}


def evaluate_result(gsc: dict[str, Any], ga4: dict[str, Any], *,
                    query_aligned: bool | None = None,
                    baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    """Contrato completo: medição + diagnóstico + decisão (SEO-INC-012/013)."""
    verdict, axes = multiaxial_verdict(gsc, ga4)
    diag = diagnosis_codes(gsc, ga4, query_aligned=query_aligned, baseline=baseline)
    dec = recommend(verdict, axes, diag)
    return {"measurement": {"verdict": verdict, "axes": axes},
            "diagnosis": diag, "decision": dec}
