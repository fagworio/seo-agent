"""Editorial E4 — contextual, advisory internal-link suggestions."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from ..tools.link_graph import is_editorial_target

_STOP = {"o", "a", "os", "as", "de", "da", "do", "das", "dos", "e", "em", "no", "na", "para", "com", "um", "uma", "que", "por", "sobre", "como", "qual", "quais", "quanto", "quando", "onde", "quem", "chega", "chegar", "estreia", "novo", "nova", "hoje", "tudo", "momento", "unicorniohater", "redação", "leitura"}


def _tokens(value: str) -> set[str]:
    words = re.findall(r"[a-zà-ú]{3,}", (value or "").lower())
    return {word for word in words if word not in _STOP}


def _context_tokens(url: str, context: dict[str, Any]) -> set[str]:
    fallback = urlparse(url).path.strip("/").replace("-", " ")
    return _tokens(" ".join([context.get("title", ""), context.get("h1", ""), *context.get("h2s", []), fallback]))


def _excerpt(text: str, terms: set[str]) -> str:
    for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
        if len(_tokens(sentence) & terms) >= min(2, len(terms)):
            return sentence.strip()[:240]
    return ""


def _anchor(context: dict[str, Any], terms: set[str]) -> str:
    title = context.get("title", "") or context.get("h1", "")
    if title:
        title = re.sub(r"\s+[—|-]\s+UnicornioHater$", "", title, flags=re.I).strip()
        if ":" in title:
            prefix, rest = title.split(":", 1)
            return f"{prefix.strip()}: {' '.join(rest.split()[:2])}".strip()
        return " ".join(title.split()[:6])
    return " ".join(sorted(terms)[:5])


def explain_interlink(*, source_url: str, target_url: str,
                      source_context: dict[str, Any], target_context: dict[str, Any],
                      stored_anchor: str = "") -> dict[str, Any]:
    """Explain an interlink with corpus evidence, without inventing traffic uplift."""
    source_terms = _context_tokens(source_url, source_context)
    target_terms = _context_tokens(target_url, target_context)
    shared = sorted(source_terms & target_terms)
    excerpt = _excerpt(source_context.get("body_text", ""), set(shared)) if shared else ""
    anchor = stored_anchor.strip() or _anchor(target_context, set(shared))
    if len(shared) >= 3 and excerpt:
        relevance, confidence = "strong", "high"
    elif len(shared) >= 2:
        relevance, confidence = "moderate", "medium"
    else:
        relevance, confidence = "weak", "low"
    if relevance == "weak":
        insertion = "Não inserir automaticamente: o corpus atual não confirmou um trecho tematicamente compatível. Reanalise ou rejeite a sugestão."
    elif excerpt:
        insertion = f"Inserir no trecho identificado, vinculando a menção mais natural a “{anchor}”."
    elif shared:
        insertion = f"Localizar na página de origem um parágrafo que trate de {', '.join(shared[:3])}; inserir apenas se o destino aprofundar esse ponto."
    else:
        insertion = "Não inserir automaticamente: o corpus atual não confirmou um trecho tematicamente compatível. Reanalise ou rejeite a sugestão."
    return {
        "source_title": source_context.get("title", "") or source_context.get("h1", ""),
        "target_title": target_context.get("title", "") or target_context.get("h1", ""),
        "shared_terms": shared[:8],
        "source_excerpt": excerpt,
        "suggested_anchor": anchor,
        "anchor_origin": "stored" if stored_anchor.strip() else "generated_from_target",
        "relevance": relevance,
        "confidence": confidence,
        "insertion_instruction": insertion,
        "google_benefits": [
            "cria um caminho rastreável entre conteúdos relacionados",
            "reforça a relação temática e o contexto da página de destino",
            "distribui autoridade interna para o destino",
        ],
        "site_benefits": [
            "oferece aprofundamento sem interromper a leitura",
            "facilita a descoberta de conteúdo relacionado",
            "pode aumentar navegação e engajamento; o efeito deve ser medido",
        ],
        "verification_steps": [
            "confirmar no recrawl que o link origem → destino existe",
            "validar que a âncora descreve corretamente o destino",
            "acompanhar cliques, impressões e engajamento do destino após a janela de medição",
        ],
    }


def suggest_interlinks(*, sources: list[str], targets: list[str], existing_out: dict[str, set[str]],
                       contexts: dict[str, dict[str, Any]] | None = None,
                       limit_per_source: int = 3, max_total: int = 100) -> list[dict[str, Any]]:
    """Suggest links only when page context establishes a thematic relation."""
    contexts = contexts or {}
    suggestions: list[dict[str, Any]] = []
    in_links = _in_link_counts(existing_out)
    target_tokens = {target: _context_tokens(target, contexts.get(target, {})) for target in targets}
    for source in sources:
        source_context = contexts.get(source, {})
        if source_context.get("is_noindex") or source_context.get("status_code", 200) >= 400:
            continue
        source_tokens = _context_tokens(source, source_context)
        if not source_tokens:
            continue
        candidates: list[tuple[int, int, str, set[str]]] = []
        for target in targets:
            target_context = contexts.get(target, {})
            if target == source or target in existing_out.get(source, set()) or not is_editorial_target(target):
                continue
            if target_context.get("is_noindex") or target_context.get("status_code", 200) >= 400:
                continue
            canonical = target_context.get("canonical", "")
            if canonical and canonical.rstrip("/") != target.rstrip("/"):
                continue
            shared = source_tokens & target_tokens[target]
            if len(shared) >= 2:
                candidates.append((len(shared), in_links.get(target, 0), target, shared))
        candidates.sort(key=lambda candidate: (-candidate[0], candidate[1], candidate[2]))
        for shared_count, target_in_links, target, shared in candidates[:limit_per_source]:
            excerpt = _excerpt(source_context.get("body_text", ""), shared)
            suggestions.append({"source_url": source, "target_url": target,
                                "reason": f"relação temática por {shared_count} termos: {', '.join(sorted(shared)[:4])}; destino com {target_in_links} links de entrada",
                                "anchor": _anchor(contexts.get(target, {}), shared),
                                "context_excerpt": excerpt,
                                "editorial_note": "inserir apenas se o trecho realmente se beneficiar do aprofundamento"})
        if len(suggestions) >= max_total:
            break
    return suggestions


def _in_link_counts(existing_out: dict[str, set[str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for targets in existing_out.values():
        for target in targets:
            counts[target] = counts.get(target, 0) + 1
    return counts
