"""M6-V2 — composição do Opportunity V2 (cruzamento de sinais).

Ponto único que reúne corpus + GSC + GA4 + link graph + semântica e calcula o
pacote V2: Topic Authority, Query Rankability, Headroom, Confidence e o
OpportunityScore ponderado com gates. Usado por ``decide``, ``/experiments`` e
CLI. Determinístico, zero API externa.
"""
from __future__ import annotations

from typing import Any

from .rankability_signals import (build_cluster_signals, build_query_signals,
                                  resolve_cluster_entity)
from .rankability_v2 import (confidence_v2, headroom, opportunity_engine,
                             query_distribution, query_rankability,
                             topic_authority)


def compute_opportunity_v2(storage: Any, keyword: str, *,
                           window_start: str | None = None,
                           as_percent: bool = False) -> dict[str, Any]:
    """Calcula o pacote V2 completo para uma keyword/intenção."""
    keyword = (keyword or "").strip()
    if not keyword:
        return {"error": "keyword vazia"}
    entity = resolve_cluster_entity(storage, keyword)
    signals, cov = build_cluster_signals(storage, entity, window_start=window_start)
    dist = query_distribution(signals["positions"])
    topic = topic_authority(signals, as_percent=as_percent)

    qs = build_query_signals(storage, signals, keyword)
    top10 = dist.get("shares", {}).get("top10", 0.0)
    qs["related_top10_share"] = top10
    qs["topic_authority"] = topic["score"]
    qr = query_rankability(qs, signals, dist, as_percent=as_percent)

    impressions = float(qs.get("impressions", 0) or 0)
    clicks = float(qs.get("clicks", 0) or 0)
    ctr = (clicks / impressions) if impressions else None
    room, _ = headroom(qs.get("position"), ctr, 0.06)
    sig_momentum = signals.get("momentum_delta_pct")
    momentum = (min(sig_momentum / 50, 1.0) if isinstance(sig_momentum, (int, float))
                else 0.5)

    conf = confidence_v2({
        "gsc_sample": 0.9 if impressions else 0.2,
        "windows": 0.9 if sig_momentum is not None else 0.4,
        "ga4_available": 0.5 if signals.get("ga4_engagement_rate") else 0.0,
        "corpus_available": 1.0 if signals.get("posts") else 0.0,
        "semantic_evidence": 0.8 if qs.get("semantic", {}).get("body_fit") else 0.2,
        "query_stability": 0.6,
        "technical_known": 0.7,
    })

    opp = opportunity_engine({
        "query_rankability": qr["score"],
        "demand": min(impressions / 20000, 1.0) if impressions else 0.0,
        "headroom": room,
        "momentum": momentum,
        "strategic_fit": 1.0 if signals.get("entities") else 0.5,
        "confidence": conf,
    }, as_percent=as_percent)

    return {
        "keyword": keyword,
        "topic_authority": topic,
        "query_rankability": qr,
        "headroom": {"score": room},
        "confidence": conf,
        "opportunity": opp,
        "signals": {
            "posts": signals.get("posts", 0),
            "entities": signals.get("entities", 0),
            "sections": signals.get("sections", 0),
            "questions": signals.get("questions", 0),
            "positions": signals.get("positions", []),
            "impressions": impressions,
            "clicks": clicks,
            "ctr": ctr,
            "position": qs.get("position"),
            "momentum_delta_pct": sig_momentum,
            "distribution": dist,
            "cluster_urls": signals.get("urls", []),
        },
    }
