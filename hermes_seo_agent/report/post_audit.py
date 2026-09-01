"""Post improvement analysis — deterministic suggestions + gains (Phase 6).

Given a post's GSC metrics and content signals (word count, age, traffic
loss), generate a prioritized CHECKLIST of manual improvements, each with a
reason, an action, and an estimated click gain. Pure rules + the CTR
benchmark — no AI. The human (or the agent later) executes the items.
"""

from __future__ import annotations

from typing import Any

from .expectations import expected_ctr

# Thresholds (deterministic)
MIN_IMPRESSIONS_CTR = 300      # páginas com este volume e CTR baixo = oportunidade
MIN_IMPRESSIONS_ZERO = 100     # impressões sem clique = intenção desalinhada
MIN_IMPRESSIONS_RANK = 100
THIN_WORDS = 300               # abaixo disso = conteúdo fino
STALE_DAYS = 120               # acima disso = candidato a atualização
LOST_TRAFFIC_RATIO = 1.5       # impressões caíram 50%+ vs período anterior


def priority_score(metrics: dict[str, Any], content: dict[str, Any]) -> float:
    """Weighted opportunity score used to sort which posts to improve first."""
    impressions = metrics.get("impressions") or 0
    clicks = metrics.get("clicks") or 0
    ctr = metrics.get("ctr") or 0
    position = metrics.get("position")
    word_count = content.get("word_count")
    age_days = content.get("age_days")
    lost = content.get("lost_traffic", False)

    score = min(impressions, 5000) / 5000 * 3
    if impressions >= MIN_IMPRESSIONS_CTR and ctr <= 0.02:
        score += 2
    if impressions >= MIN_IMPRESSIONS_ZERO and clicks == 0:
        score += 1.5
    if lost:
        score += 2
    if word_count is not None and word_count < THIN_WORDS:
        score += 1
    if age_days is not None and age_days > STALE_DAYS:
        score += 0.5
    if position is not None and position >= 8:
        score += 1
    return round(score, 2)


def content_checklist(metrics: dict[str, Any], content: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic improvement checklist for one post.

    metrics:  GSC data + expectation (build_expectation output).
    content:  {word_count, age_days, lost_traffic}
    """
    impressions = metrics.get("impressions") or 0
    clicks = metrics.get("clicks") or 0
    ctr = metrics.get("ctr") or 0
    position = metrics.get("position")
    expected = metrics.get("expected_clicks") or 0
    word_count = content.get("word_count")
    age_days = content.get("age_days")
    lost = content.get("lost_traffic", False)

    items: list[dict[str, Any]] = []

    if impressions >= MIN_IMPRESSIONS_CTR and ctr <= 0.02:
        gain = round(max(expected * 0.5 - clicks, 0), 1)
        items.append({
            "item": "title_meta",
            "reason": f"CTR {ctr*100:.1f}% para {impressions:.0f} impressões (abaixo do benchmark)",
            "action": "Reescrever título (set-title) + meta description casando com as queries reais",
            "gain_clicks": gain,
        })
    if impressions >= MIN_IMPRESSIONS_ZERO and clicks == 0:
        items.append({
            "item": "intent",
            "reason": f"{impressions:.0f} impressões e 0 cliques",
            "action": "Verificar se o conteúdo responde à intenção de busca (título/snippet)",
            "gain_clicks": round(expected * 0.25, 1),
        })
    if word_count is not None and word_count < THIN_WORDS:
        items.append({
            "item": "thin_content",
            "reason": f"conteúdo fino ({word_count} palavras)",
            "action": "Expandir o conteúdo (profundidade, contexto, exemplos)",
            "gain_clicks": None,
        })
    if age_days is not None and age_days > STALE_DAYS:
        items.append({
            "item": "stale",
            "reason": f"post com {age_days} dias sem atualização",
            "action": "Atualizar informações e reciclar o conteúdo (frescor)",
            "gain_clicks": None,
        })
    if lost:
        items.append({
            "item": "lost_traffic",
            "reason": "perdeu impressões vs período anterior",
            "action": "Atualizar o conteúdo para recuperar o tráfego perdido",
            "gain_clicks": None,
        })
    if position is not None and position >= 8 and impressions >= MIN_IMPRESSIONS_RANK:
        gain = round(impressions * (expected_ctr(3) - expected_ctr(position)) * 0.5, 1)
        items.append({
            "item": "rank",
            "reason": f"posição {position:.0f} (fora do top 5)",
            "action": "Otimizar título/relevância para subir de posição",
            "gain_clicks": max(gain, 0),
        })
    return items


def total_gain(items: list[dict[str, Any]]) -> float:
    """One page has one opportunity envelope; never sum overlapping hypotheses.

    Title, intent and ranking recommendations often address the same demand.
    Showing their sum would overstate the forecast.  The largest quantified
    intervention is therefore the page-level estimated incremental gain.
    """
    return round(max((float(i.get("gain_clicks") or 0) for i in items), default=0), 1)
