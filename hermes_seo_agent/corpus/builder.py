"""M2 — Memória editorial determinística do acervo (corpus).

Constrói um índice por documento/seção/entidade com FTS5/BM25 a partir do
sitemap + HTML renderizado. O agente consulta o acervo ANTES de propor
conteúdo novo — e identifica qual SEÇÃO já cobre uma intenção, não só "temos
um artigo sobre X".
"""

from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from typing import Any

# Franquias/obras conhecidas do território do site (determinístico).
KNOWN_FRANCHISES = {
    "one piece", "naruto", "dragon ball", "jujutsu kaisen", "attack on titan",
    "shingeki no kyojin", "demon slayer", "kimetsu no yaiba", "my hero academia",
    "boku no hero", "chainsaw man", "spy x family", "mob psycho", "hunter x hunter",
    "fullmetal alchemist", "death note", "tokyo ghoul", "berserk", "evangelion",
    "neon genesis evangelion", "cowboy bebop", "steins gate", "re zero", "overlord",
    "sword art online", "re zero", "konosuba", "made in abyss", "vinland saga",
    "mob psycho 100", "the boys", "invincible", "rick and morty", "star wars",
    "masters of the universe", "he-man", "she-ra", "thundercats", "wolverine",
    "x-men", "spider-man", "batman", "superman", "avatar", "the last airbender",
    "gravity falls", "regular show", "adventure time", "steven universe",
    "pokemon", "digimon", "yu-gi-oh", "sailor moon", "cardcaptor sakura",
    "detective conan", "case closed", "bleach", "fairy tail", "black clover",
    "gintama", "haikyuu", "kuroko", "slam dunk", "captain tsubasa", "initial d",
}

# Termos de plataforma/jogos comuns (para entity_type game/platform).
KNOWN_GAMES = {
    "zelda", "mario", "sonic", "pokemon", "final fantasy", "resident evil",
    "god of war", "elden ring", "dark souls", "the witcher", "cyberpunk",
    "mortal kombat", "street fighter", "call of duty", "minecraft", "fortnite",
    "gta", "grand theft auto", "red dead", "super mario", "splatoon",
    "xbox", "playstation", "nintendo", "pc", "steam", "switch",
}


class _SectionParser(HTMLParser):
    """Captura seções (h2/h3) com heading, nível, posição e texto até o
    próximo heading — para busca por SEÇÃO, não só por documento."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._in_heading = False
        self._ignore = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "template", "nav", "footer",
                   "aside", "header"}:
            self._ignore += 1
        if self._ignore:
            return
        if tag in {"h2", "h3"}:
            self._finish()
            self._current = {"heading": "", "level": int(tag[1]),
                             "position": len(self.sections), "text": ""}
            self._in_heading = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "template", "nav", "footer",
                   "aside", "header"} and self._ignore:
            self._ignore -= 1
        if self._ignore:
            return
        if tag in {"h2", "h3"}:
            self._finish()
            self._in_heading = False

    def handle_data(self, data: str) -> None:
        if self._ignore:
            return
        if self._current is not None and self._in_heading:
            self._current["heading"] += data
        elif self.sections:
            self.sections[-1]["text"] += data

    def _finish(self) -> None:
        if self._current is not None:
            self.sections.append(self._current)
            self._current = None


def extract_sections(html: str, url: str) -> list[dict[str, Any]]:
    """Seções do HTML com heading, nível, posição e texto (hash por seção)."""
    parser = _SectionParser()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        pass
    sections = []
    for sec in parser.sections:
        heading = re.sub(r"\s+", " ", (sec.get("heading") or "")).strip()
        text = re.sub(r"\s+", " ", (sec.get("text") or "")).strip()
        if not heading and not text:
            continue
        sections.append({
            "url": url,
            "heading": heading,
            "heading_level": sec.get("level", 2),
            "position": sec.get("position", 0),
            "text": text[:4000],
            "hash": hashlib.sha256(f"{heading}|{text}".encode("utf-8")).hexdigest()[:16],
        })
    return sections


def _normalize(text: str) -> str:
    import unicodedata
    s = (text or "").lower().strip()
    s = "".join(c for c in unicodedata.normalize("NFKD", s)
                if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", s)


def extract_entities(title: str, h1: str, body: str) -> list[dict[str, str]]:
    """Entidades normalizadas (determinísticas): franquias/games conhecidas +
    termos capitalizados repetidos no título/corpo. Sem IA."""
    haystack = _normalize(f"{title} {h1} {body[:6000]}")
    found: dict[tuple[str, str], int] = {}
    for franchise in KNOWN_FRANCHISES:
        n = _normalize(franchise)
        if n in haystack:
            found[(franchise, "franchise")] = found.get((franchise, "franchise"), 0) + 1
    for game in KNOWN_GAMES:
        n = _normalize(game)
        if n in haystack:
            found[(game, "game")] = found.get((game, "game"), 0) + 1
    # Termos capitalizados (candidatos a nomes próprios) presentes no título
    # e no corpo — apenas heurística leve, sem NLP.
    for m in re.finditer(r"\b([A-ZÀ-Ú][a-zà-ú]{2,})\b", f"{title} {h1}"):
        term = m.group(1)
        n = _normalize(term)
        if len(n) < 3 or n in {"the", "de", "da", "do", "em", "um", "uma", "com", "para"}:
            continue
        if haystack.count(n) >= 2:
            found.setdefault((term, "term"), 0)
            found[(term, "term")] += 1
    return [
        {"entity": entity, "entity_type": etype, "count": count}
        for (entity, etype), count in sorted(found.items(), key=lambda kv: -kv[1])
    ][:30]


def build_corpus(storage: Any, pages: list[Any], *, built_at: str) -> dict[str, int]:
    """Persiste documento + seções + entidades + FTS para as páginas fornecidas."""
    docs = sections = entities = 0
    for page in pages:
        url = page.url
        body = getattr(page, "body_text", "") or ""
        content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        storage.save_corpus_document(
            url=url, title=getattr(page, "title", "") or "",
            h1=" ".join(getattr(page, "h1", []) or []),
            body_text=body, canonical=getattr(page, "canonical", "") or "",
            is_noindex=int("noindex" in (getattr(page, "meta_robots", "") or "").lower()),
            status_code=getattr(page, "status_code", 0),
            content_hash=content_hash, built_at=built_at,
        )
        docs += 1
        secs = extract_sections(getattr(page, "html", "") or "", url)
        storage.replace_corpus_sections(url, secs)
        sections += len(secs)
        ents = extract_entities(getattr(page, "title", "") or "",
                                " ".join(getattr(page, "h1", []) or []), body)
        storage.replace_corpus_entities(url, ents)
        entities += len(ents)
        # FTS por documento (title + h1 + body).
        storage.index_corpus_document(url, getattr(page, "title", "") or "",
                                      " ".join(getattr(page, "h1", []) or []), body)
    return {"documents": docs, "sections": sections, "entities": entities}
