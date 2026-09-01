"""Editorial E2 — ContentBrief: deterministic content-gap diagnosis.

Given a post's queries, title/H1/H2, word count and internal-link context,
identify WHICH gap exists and where (deterministic rules) and produce a
manual action brief with evidence. Never generates or edits content.
"""

from __future__ import annotations

import re
from typing import Any

from .post_audit import STALE_DAYS, THIN_WORDS, priority_score


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zà-ú]{3,}", (text or "").lower())}


def detect_gaps(
    *,
    title: str,
    h2s: list[str],
    word_count: int | None,
    age_days: int | None,
    ctr: float | None,
    impressions: float,
    in_links: int | None,
    queries: list[str],
    h1: str = "",
    body_text: str = "",
) -> list[dict[str, Any]]:
    """Return gap findings: {gap, where, evidence, action}."""
    gaps: list[dict[str, Any]] = []
    title_words = _words(f"{title} {h1}")
    h2_text = " ".join(h2s)
    h2_words = _words(h2_text)

    # 1) Question query without an answering H2/section.
    for query in queries:
        q = (query or "").strip()
        if not q or not any(w in q for w in ("como", "o que", "qual", "quanto",
                                             "quando", "onde", "por que", "quem", "quais")):
            continue
        q_words = {w for w in re.findall(r"[a-zà-ú]{3,}", q.lower())} - {"como", "que", "qual", "quanto", "quando", "onde", "por", "quem", "quais", "para"}
        body_words = _words(body_text)
        covered_in_section = q_words.intersection(h2_words)
        # A title can signal relevance, but it is not itself an answer.
        answered_in_body = len(q_words.intersection(body_words)) >= max(1, len(q_words) - 1)
        if q_words and not covered_in_section and not answered_in_body:
            gaps.append({
                "gap": "question_unanswered",
                "where": "conteúdo (nenhuma seção responde)",
                "evidence": f"query '{q}' não coberta por title/H2",
                "action": "adicionar seção que responda diretamente à pergunta",
            })
            break  # uma por query de pergunta já é suficiente

    # 2) Conteúdo fino.
    if word_count is not None and word_count < THIN_WORDS:
        gaps.append({
            "gap": "low_depth",
            "where": "corpo do texto",
            "evidence": f"{word_count} palavras (abaixo de {THIN_WORDS})",
            "action": "expandir com contexto, exemplos e subseções",
        })

    # 3) Antigo / sem atualização.
    if age_days is not None and age_days > STALE_DAYS:
        gaps.append({
            "gap": "stale",
            "where": "datas e informações",
            "evidence": f"{age_days} dias sem atualização",
            "action": "atualizar informações e reciclar o conteúdo",
        })

    # 4) CTR baixo com volume = título/snippet não casam.
    if impressions >= 300 and ctr is not None and ctr <= 0.02:
        gaps.append({
            "gap": "ctr",
            "where": "title/snippet",
            "evidence": f"CTR {ctr*100:.1f}% para {impressions:.0f} impressões",
            "action": "reescrever título + meta description casando com as queries",
        })

    # 5) Página sem links internos de entrada (órfã) ou sem saída para o cluster.
    if in_links == 0:
        gaps.append({
            "gap": "orphan",
            "where": "grafo de links",
            "evidence": "nenhuma URL aponta para esta página",
            "action": "adicionar links de entrada a partir de páginas do mesmo cluster",
        })

    return gaps


def build_brief(
    *,
    url: str,
    title: str,
    h2s: list[str],
    word_count: int | None,
    age_days: int | None,
    ctr: float | None,
    impressions: float,
    in_links: int | None,
    queries: list[str],
    intent: str = "",
    h1: str = "",
    body_text: str = "",
) -> dict[str, Any]:
    """Full brief: evidence, gaps, manual action, priority."""
    gaps = detect_gaps(title=title, h2s=h2s, word_count=word_count, age_days=age_days,
                       ctr=ctr, impressions=impressions, in_links=in_links, queries=queries,
                       h1=h1, body_text=body_text)
    score = priority_score(
        {"impressions": impressions, "clicks": (impressions * (ctr or 0)),
         "ctr": ctr or 0, "position": None},
        {"word_count": word_count, "age_days": age_days, "lost_traffic": False},
    ) + (len(gaps) * 0.5)
    return {
        "url": url,
        "title": title,
        "intent": intent,
        "queries": queries,
        "gaps": gaps,
        "action": gaps[0]["action"] if gaps else "nenhuma melhoria clara detectada",
        "priority": round(score, 2),
    }
