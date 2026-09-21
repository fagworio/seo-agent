"""FASE 1–4 — Query Family Engine, Demand Share, Term/Intent Support, Coverage.

O motor antigo tratava CADA variação de query como uma oportunidade
independente (``gojo idade`` / ``idade do gojo`` / ``quantos anos tem gojo`` =
três concorrentes). Aqui elas convergem para UMA família:

    entity: gojo · intent: idade · family_id: gojo::idade

Determinístico de ponta a ponta (dicionário + normalização lexical + aliases):
nenhuma chamada a modelo, nenhuma API externa. Nada aqui decide sozinho — este
módulo produz a EVIDÊNCIA (família, share observado, suporte, cobertura) que o
``title_engine`` usa para decidir.

Terminologia obrigatória: o GSC devolve as queries PRINCIPAIS, não todas as
buscas. Portanto falamos de **observed_query_share** — nunca de "cobertura
total das buscas". Ausência de dado nunca é lida como zero.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Sequence

from ..tools.intent import normalize_query
from ..tools.title_opportunities import INTENT_GROUPS as _BASE_INTENT_GROUPS

# ---------------------------------------------------------------------------
# FASE 1 — Dicionário de intenção (superset explícito do dicionário do gerador
# estratégico: todos os grupos/labels de title_opportunities.INTENT_GROUPS estão
# representados aqui — garantido por teste, para não haver duas verdades).
#
# Cada entrada: (label, aliases...). O label é o nome canônico da intenção que
# aparece no family_id e nas decisões.
#
# Ordem = prioridade de desempate: quando duas intenções casam com o MESMO peso
# (mesmo comprimento de alias), vence a que vem antes — por isso os grupos mais
# específicos ficam no topo.
# ---------------------------------------------------------------------------

FAMILY_INTENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # — grupos novos (FASE 1) —
    ("localizacao", ("localizacao", "location", "onde encontrar", "onde achar",
                     "onde fica", "onde esta", "mapa", "como chegar")),
    ("comparacao", ("vs", "versus", "melhor que", "diferenca entre", "comparar",
                    "comparacao")),
    ("relacionamento", ("namorada", "namorado", "esposa", "esposo", "marido",
                        "irmao", "irma", "irmaos", "pai", "mae", "filho", "filha",
                        "relacionamento", "se apaixona")),
    ("personagens", ("personagem", "personagens", "protagonista", "quem sao os",
                     "elenco completo")),
    ("dublador", ("dublador", "dubladora", "dublagem", "voz original",
                  "voz brasileira", "quem dubla")),
    ("ator", ("ator", "atriz", "quem interpreta", "quem faz o papel",
              "interpretado por", "quem atua")),
    ("episodios", ("episodio", "episodios", "temporada", "temporadas", "capitulo",
                   "capitulos", "quantos eps")),
    ("duracao", ("duracao", "quanto tempo", "quantas horas", "minutos", "quanto dura")),
    ("requisitos", ("requisitos", "requisito", "configuracao minima",
                    "especificacoes", "roda em", "precisa de")),
    ("data", ("data", "que dia", "quando sai", "quando estreia", "quando lanca")),
    ("lancamento", ("lancamento", "lanca", "lancar", "vai lancar", "chega em",
                    "vai sair")),
    ("streaming", ("streaming", "netflix", "crunchyroll", "prime video", "disney plus",
                   "disney+", "hbo", "globoplay", "star+", "paramount+",
                   "apple tv", "assistir online")),
    ("plataformas", ("plataforma", "plataformas", "quais consoles", "onde tem",
                     "disponivel em")),
    ("cronologia", ("cronologia", "linha do tempo", "em que ano se passa",
                    "ordem dos filmes")),
    # — grupos herdados do gerador estratégico (mesmos labels e aliases) —
    ("final", ("explicado", "o final", "final explicado", "o que acontece no final")),
    ("onde_assistir", ("assistir", "streaming", "plataforma", "onde ver")),
    ("poderes", ("poder", "habilidade", "habilidades", "fraqueza", "skill")),
    ("idade", ("idade", "anos", "velho", "nascimento", "nasceu", "aniversario")),
    ("altura", ("altura", "mede", "metro", "tamanho")),
    ("morte", ("morte", "morreu", "morre", "falecido", "morrido")),
    ("elenco", ("elenco", "ator", "atriz", "dublador", "dubladora", "quem faz")),
    ("ordem", ("ordem", "cronologia", "sequencia")),
    ("preco", ("preco", "custa", "valor", "barato")),
    ("estreia", ("estreia", "lancamento", "quando sai", "data de")),
)

INTENT_LABELS: tuple[str, ...] = tuple(label for label, _a in FAMILY_INTENTS)

# Frase canônica de cada intenção no TÍTULO (redação). Fonte ÚNICA: o
# combinatório e o gerador usam a mesma tabela — nunca duas verdades.
INTENT_TITLE_PHRASES: dict[str, str] = {
    "idade": "idade",
    "altura": "altura",
    "morte": "morte",
    "elenco": "elenco",
    "ator": "ator",
    "dublador": "dublador",
    "ordem": "ordem",
    "cronologia": "cronologia",
    "onde_assistir": "onde assistir",
    "localizacao": "onde encontrar",
    "streaming": "streaming",
    "plataformas": "plataformas",
    "final": "final explicado",
    "poderes": "poderes",
    "preco": "preço",
    "lancamento": "lançamento",
    "data": "data",
    "estreia": "estreia",
    "duracao": "duração",
    "episodios": "episódios",
    "requisitos": "requisitos",
    "personagens": "personagens",
    "relacionamento": "relacionamento",
    "comparacao": "comparação",
}

# Intenção padrão quando nenhum grupo casa: a query tem entidade mas a demanda
# não é de pergunta específica ("gojo").
GENERIC_INTENT = "geral"

# Intenções TRANSACIONAIS: misturar duas delas produz título de loja, não de
# conteúdo ("onde assistir e quanto custa") — gate de combinação.
TRANSACTIONAL_INTENTS = frozenset({
    "onde_assistir", "streaming", "plataformas", "preco", "requisitos",
})
# Intenções que são a MESMA pergunta em vocabulários diferentes: combiná-las é
# duplicação semântica (o título vira keyword stuffing).
SEMANTIC_EQUIVALENTS: tuple[frozenset[str], ...] = (
    frozenset({"estreia", "lancamento", "data"}),
    frozenset({"onde_assistir", "streaming", "plataformas"}),
    frozenset({"elenco", "ator", "dublador"}),
    frozenset({"ordem", "cronologia"}),
)
# Pares explicitamente incompatíveis na MESMA frase de título.
INCOMPATIBLE_PAIRS: tuple[frozenset[str], ...] = (
    frozenset({"morte", "final"}),
    frozenset({"morte", "estreia"}),
    frozenset({"preco", "final"}),
    frozenset({"comparacao", "onde_assistir"}),
)

# Palavras de pergunta/pedido sem valor de entidade.
_QUESTION_WORDS = frozenset({
    "como", "qual", "quais", "quanto", "quantos", "quantas", "quando", "onde",
    "quem", "porque", "por", "que", "sera", "existe", "tem", "ter", "sao", "e",
    "foi", "era", "vai", "ver", "fazer", "significa", "realmente", "afinal",
    "ainda", "bem", "top", "melhor",
})
_ARTICLES_PREPS = frozenset({
    "a", "o", "os", "as", "de", "da", "do", "das", "dos", "e", "em", "no", "na",
    "nos", "nas", "para", "com", "um", "uma", "uns", "umas", "the", "of", "and",
    "in", "to", "la", "le", "los", "las",
})
_STOP_FOR_ENTITY = _QUESTION_WORDS | _ARTICLES_PREPS


# ---------------------------------------------------------------------------
# Normalização lexical (única, usada por todo o motor)
# ---------------------------------------------------------------------------

def fold(text: Any) -> str:
    """Minúsculas, sem acento, espaços colapsados (comparação canônica)."""
    raw = str(text or "").strip().lower()
    raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", raw).strip()


def singular(word: str) -> str:
    """Plural simples -> singular ('episodios' -> 'episodio')."""
    w = fold(word)
    if len(w) > 3 and w.endswith("s"):
        return w[:-1]
    return w


def tokens(text: Any) -> list[str]:
    """Tokens normalizados (sem acento/plural), na ordem original."""
    return [singular(t) for t in re.findall(r"[a-z0-9]+", fold(text))]


def token_set(text: Any) -> set[str]:
    return set(tokens(text))


def variants(word: str) -> set[str]:
    """Variantes de um token para COMPARAÇÃO (plural/singular irregular).

    'poderes' -> {'poderes', 'podere', 'poder'}; 'poder' -> {'poder'};
    'idade' -> {'idade', 'idad'}. A comparação é por INTERSEÇÃO de conjuntos,
    então plural e singular casam nos dois sentidos sem heurística frágil.
    """
    base = fold(word)
    out = {base}
    if not base:
        return out
    if len(base) > 3 and base.endswith("es"):
        out.add(base[:-1])
        out.add(base[:-2])
    elif len(base) > 3 and base.endswith("s"):
        out.add(base[:-1])
    for candidate in list(out):
        if len(candidate) > 3 and candidate.endswith("e"):
            out.add(candidate[:-1])
    return out


def expand_variants(words: Iterable[str]) -> set[str]:
    """União das variantes de uma coleção de tokens."""
    out: set[str] = set()
    for word in words:
        out |= variants(word)
    return out


_STOP_VARIANTS: set[str] = expand_variants(_STOP_FOR_ENTITY)


def _is_stop(token: str) -> bool:
    return bool(variants(token) & _STOP_VARIANTS)


# Terminações de FLEXÃO/DERIVAÇÃO aceitas no casamento por radical. Substitui o
# "prefixo de 5 caracteres" genérico, que casava palavras de assuntos
# diferentes em um site de games ('metro' de altura × 'Metroid').
_DERIVED_SUFFIXES = frozenset({
    "a", "as", "o", "os", "e", "es", "s", "ca", "co", "cas", "cos", "ia", "ias",
    "al", "ais", "ico", "ica", "icos", "icas", "oso", "osa", "osos", "osas",
    "mente",
})
_STEM_MIN = 6  # radical mínimo: 'metro' (5) NUNCA casa 'metroid'


def _token_hit(term: str, target_variants: set[str], *, min_stem: int = _STEM_MIN) -> bool:
    """Termo presente no alvo? (variantes plurais OU radical + flexão conhecida).

    O radical só vale com >= 6 caracteres comuns E a sobra sendo flexão
    ('cronologia'/'cronológica' casa; 'metro'/'Metroid' NÃO).
    """
    mine = variants(term)
    if mine & target_variants:
        return True
    for a in mine:
        for b in target_variants:
            short, longer = (a, b) if len(a) <= len(b) else (b, a)
            if len(short) < min_stem or not longer.startswith(short):
                continue
            remainder = longer[len(short):]
            if len(remainder) <= 4 and remainder in _DERIVED_SUFFIXES:
                return True
    return False


# ---------------------------------------------------------------------------
# FASE 1 — detecção de intenção e de entidade
# ---------------------------------------------------------------------------

def _alias_terms(alias: str) -> list[str]:
    return tokens(alias)


def _alias_in_query(alias: str, q_folded: str, q_tokens: set[str]) -> bool:
    """Alias casa por token normalizado (com plural/singular) ou por frase."""
    terms = _alias_terms(alias)
    if not terms:
        return False
    q_variants = expand_variants(q_tokens)
    if all(_token_hit(t, q_variants) for t in terms):
        return True
    return f" {fold(alias)} " in f" {q_folded} "


def intent_matches(query: str) -> dict[str, str]:
    """{label: alias casado} — TODAS as intenções presentes na query."""
    q_folded = fold(query)
    q_tokens = set(tokens(query))
    out: dict[str, str] = {}
    for label, aliases in FAMILY_INTENTS:
        best = ""
        for alias in aliases:
            if _alias_in_query(alias, q_folded, q_tokens):
                if len(alias) > len(best):
                    best = alias
        if best:
            out.setdefault(label, best)
    return out


def primary_intent(query: str) -> str:
    """Intenção PRIMÁRIA da query (determinística).

    Desempate: alias mais longo vence (mais específico); empate de comprimento
    cai na ordem do dicionário (grupos específicos primeiro).
    """
    matches = intent_matches(query)
    if not matches:
        return GENERIC_INTENT
    order = {label: i for i, label in enumerate(INTENT_LABELS)}
    winner = sorted(matches.items(), key=lambda kv: (-len(kv[1]), order.get(kv[0], 99)))
    return winner[0][0]


def intent_aliases(label: str) -> tuple[str, ...]:
    for lab, aliases in FAMILY_INTENTS:
        if lab == label:
            return aliases
    return ()


def intent_phrases(label: str) -> tuple[str, ...]:
    """Aliases de título (o que pode aparecer no <title>), excluindo perguntas.

    Usado pela cobertura: "quantos anos tem gojo" é respondido por "idade"/"anos"
    no título, não pela frase interrogativa inteira.
    """
    return tuple(a for a in intent_aliases(label)
                 if a not in ("data de", "onde ver", "quem faz", "tem",
                              "assistir online"))


def detect_entity(query: str) -> str:
    """Entidade da query = tokens significativos restantes (chave normalizada).

    Remove palavras de pergunta/artigos/preposições e os termos da INTENÇÃO:
    "quantos anos tem gojo" -> "gojo"; "idade do gojo" -> "gojo";
    "onde assistir jujutsu kaisen" -> "jujutsu kaisen".
    """
    return " ".join(entity_terms(query))


def entity_terms(query: str) -> list[str]:
    """Tokens de entidade preservando a ORDEM (para reconstruir o label)."""
    q_tokens = tokens(query)
    intent_variants: set[str] = set()
    for label in intent_matches(query):
        for alias in intent_aliases(label):
            intent_variants |= expand_variants(_alias_terms(alias))
    keep: list[str] = []
    for token in q_tokens:
        if _is_stop(token) or (variants(token) & intent_variants):
            continue
        if len(token) <= 1:
            continue
        keep.append(token)
    return keep


def entity_label(query: str) -> str:
    """Label de exibição da entidade: termos originais (sem acento) da query."""
    wanted = entity_terms(query)
    if not wanted:
        return ""
    out: list[str] = []
    for raw in re.findall(r"[^\s]+", str(query or "")):
        if singular(raw) in wanted and singular(raw) not in [singular(x) for x in out]:
            out.append(raw.strip("?.,!"))
    return " ".join(out) or " ".join(wanted)


def family_key(entity: str, intent: str) -> str:
    """family_id canônico: ``entity::intent``."""
    return f"{fold(entity) or 'desconhecido'}::{intent or GENERIC_INTENT}"


def _significant_entity_terms(text: str) -> list[str]:
    return [t for t in tokens(text) if len(t) > 2 and not _is_stop(t)]


def compatible_entity(entity: str, hint: str, *, min_overlap: float = 0.6) -> bool:
    """A entidade da query pertence à entidade da PÁGINA? (overlap >= 60%)

    Sem essa resolução a mesma intenção se fragmenta (numa página sobre
    "Melhores arqueiros de anime", as queries "arqueiros de anime" e "melhores
    arqueiros anime" geravam famílias diferentes). Mas exigir APENAS UM token em
    comum criava over-merge: "Dragon Ball" absorvia "Dragon Quest" pelo token
    'dragon'. O piso de 60% (sobre o lado menor) protege franquias com nome
    compartilhado, e quando o corpus tem a entidade canônica o chamador deve
    usá-la (ver CLI: resolve_cluster_entity).
    """
    hint_terms = _significant_entity_terms(hint)
    if not hint_terms:
        return False
    terms = _significant_entity_terms(entity)
    if not terms:
        return True  # query sem entidade chegou NESTA página: pertence a ela
    hint_variants = expand_variants(hint_terms)
    hits = sum(1 for t in terms if _token_hit(t, hint_variants))
    return (hits / min(len(terms), len(hint_terms))) >= float(min_overlap)


# ---------------------------------------------------------------------------
# FASE 1 — consolidação das famílias
# ---------------------------------------------------------------------------

def _weighted_position(rows: Sequence[dict[str, Any]]) -> float | None:
    num = den = 0.0
    for row in rows:
        pos_raw = row.get("position")
        if pos_raw is None:
            continue
        try:
            pos = float(pos_raw)
        except (TypeError, ValueError):
            continue
        imp = max(float(row.get("impressions", 0) or 0), 0.0)
        num += pos * imp
        den += imp
    if den <= 0:
        return None
    return round(num / den, 2)


def build_families(rows: Iterable[dict[str, Any]], *,
                   min_impressions: float = 0.0,
                   entity_hint: str = "") -> list[dict[str, Any]]:
    """Agrupa linhas do GSC (query x página) em FAMÍLIAS de intenção.

    ``rows``: [{keys: [query], impressions, clicks, ctr, position}] — o mesmo
    formato já coletado pelo pipeline (nenhuma coleta nova).

    ``entity_hint``: entidade indexada da PÁGINA (ex.: `entity_of(titulo)`).
    Quando a entidade detectada na query pertence à página, o agrupamento usa a
    entidade da página — sem isso a MESMA intenção se fragmenta em famílias
    diferentes por variação de digitação/ordem das palavras.

    Retorna famílias ordenadas por impressões desc:
      {family_id, entity, entity_label, intent, intents, queries,
       impressions, clicks, weighted_position, ctr, query_count}
    """
    buckets: dict[str, dict[str, Any]] = {}
    hint = fold(entity_hint)
    for row in rows:
        keys = row.get("keys") or []
        query = str((keys[0] if keys else "") or "").strip()
        if not query:
            continue
        impressions = float(row.get("impressions", 0) or 0)
        if impressions < float(min_impressions or 0):
            continue
        clicks = float(row.get("clicks", 0) or 0)
        intent = primary_intent(query)
        entity = detect_entity(query)
        if hint and compatible_entity(entity, hint):
            entity = hint
        key = family_key(entity, intent)
        bucket = buckets.setdefault(key, {
            "family_id": key,
            "entity": entity,
            "entity_label": "",
            "intent": intent,
            "intents": set(),
            "queries": [],
            "rows": [],
            "impressions": 0.0,
            "clicks": 0.0,
        })
        bucket["intents"].update(intent_matches(query).keys())
        bucket["queries"].append(query)
        bucket["rows"].append({**row, "impressions": impressions, "clicks": clicks})
        bucket["impressions"] += impressions
        bucket["clicks"] += clicks
        # label da entidade vem da query de MAIOR impressão da família (estável)
        best = bucket["rows"][0]
        for cand in bucket["rows"]:
            if float(cand.get("impressions", 0)) > float(best.get("impressions", 0)):
                best = cand
        bucket["entity_label"] = entity_label(str((best.get("keys") or [""])[0]))

    hint_label = str(entity_hint or "").strip()
    families: list[dict[str, Any]] = []
    for bucket in buckets.values():
        impressions = bucket["impressions"]
        clicks = bucket["clicks"]
        label = bucket["entity_label"] or bucket["entity"]
        if hint and bucket["entity"] == hint and hint_label:
            label = hint_label
        # Impressões POR QUERY (fonte real do GSC): evita que o consumidor tenha
        # de reconsultar/somar variantes (dupla contagem) ou depender da ordem
        # em que as queries chegaram.
        per_query: dict[str, float] = {}
        for bucket_row in bucket["rows"]:
            query_text = str((bucket_row.get("keys") or [""])[0])
            if not query_text:
                continue
            per_query[query_text] = per_query.get(query_text, 0.0) + float(
                bucket_row.get("impressions", 0) or 0)
        ordered = sorted(per_query.items(), key=lambda item: (-item[1], item[0]))
        families.append({
            "family_id": bucket["family_id"],
            "entity": bucket["entity"],
            "entity_label": label,
            "intent": bucket["intent"],
            "intents": sorted(bucket["intents"]),
            "queries": list(dict.fromkeys(bucket["queries"])),
            # ordem estável por impressões: top_queries[k] = k-ésima query da família
            "top_queries": [query_text for query_text, _imp in ordered],
            "query_impressions": {query_text: round(imp, 2) for query_text, imp in ordered},
            "impressions": round(impressions, 2),
            "clicks": round(clicks, 2),
            "weighted_position": _weighted_position(bucket["rows"]),
            "ctr": round(clicks / impressions, 5) if impressions else None,
            "query_count": len(set(bucket["queries"])),
        })
    families.sort(key=lambda f: (-f["impressions"], f["family_id"]))
    return families


# ---------------------------------------------------------------------------
# FASE 2 — Demand Share (share do universo OBSERVADO)
# ---------------------------------------------------------------------------

def demand_share(families: Sequence[dict[str, Any]], *, url: str = "",
                 window_start: str = "", window_end: str = "",
                 page_impressions: float | None = None) -> dict[str, Any]:
    """Quanto da demanda OBSERVADA da página pertence a cada família.

    ``observed_query_share`` = family_impressions / Σ impressões observadas.
    NUNCA chamar isso de cobertura total das buscas: o GSC devolve as queries
    principais, não o universo inteiro. Sem universo (Σ = 0) os shares são
    ``None`` — ausência de dado não é zero.

    ``page_impressions`` (impressões totais da página, forma ``page`` do GSC)
    permite a segunda métrica, que o share sozinho não dá:

        query_observation_ratio = Σ impressões das queries / impressões da página

    Ex.: "idade = 40% das queries observáveis" pode ser só 8% da página se as
    queries conhecidas explicam 20% das impressões dela. A decisão precisa das
    duas leituras — e a razão entra na confiança.
    """
    total = sum(float(f.get("impressions", 0) or 0) for f in families)
    out: list[dict[str, Any]] = []
    for family in families:
        impressions = float(family.get("impressions", 0) or 0)
        out.append({
            "family": family.get("family_id"),
            "intent": family.get("intent"),
            "entity": family.get("entity"),
            "impressions": impressions,
            "clicks": family.get("clicks"),
            "share": round(impressions / total, 4) if total else None,
            "weighted_position": family.get("weighted_position"),
            "query_count": family.get("query_count"),
            "queries": list(family.get("queries") or []),
        })
    ratio: float | None = None
    try:
        page_imp = float(page_impressions) if page_impressions is not None else 0.0
    except (TypeError, ValueError):
        page_imp = 0.0
    if page_imp > 0:
        ratio = round(min(total / page_imp, 1.0), 4)
    if ratio is None:
        status = "unknown"
    elif ratio >= 0.5:
        status = "well_observed"
    elif ratio >= 0.2:
        status = "partial"
    else:
        status = "thin"
    return {
        "url": url,
        "window_start": window_start,
        "window_end": window_end,
        "observed_impressions": round(total, 2),
        "page_impressions": round(page_imp, 2) if page_imp else None,
        "query_observation_ratio": ratio,
        "observation_status": status,
        "families": out,
        "metric": "observed_query_share",
        "caveat": ("share do universo OBSERVADO no GSC (queries principais); "
                   "não é a cobertura total das buscas — ver "
                   "query_observation_ratio para a fração das impressões da "
                   "página que as queries conhecidas explicam"),
        "has_data": bool(total),
    }


# ---------------------------------------------------------------------------
# FASE 3 — Term Support / Intent Support
# ---------------------------------------------------------------------------

def term_support(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Suporte REAL de cada termo e de cada intenção na demanda observada.

    Fórmula (impressões ponderadas — número de queries NÃO é métrica):

        support(conceito) = Σ impressões das queries que carregam o conceito
                            / Σ impressões observadas
    """
    per_token: dict[str, dict[str, Any]] = {}
    per_intent: dict[str, dict[str, Any]] = {}
    total = 0.0
    for row in rows:
        keys = row.get("keys") or []
        query = str((keys[0] if keys else "") or "").strip()
        if not query:
            continue
        impressions = float(row.get("impressions", 0) or 0)
        total += impressions
        for token in set(tokens(query)):
            if token in _STOP_FOR_ENTITY or len(token) <= 2:
                continue
            slot = per_token.setdefault(token, {"impressions": 0.0, "queries": []})
            slot["impressions"] += impressions
            slot["queries"].append(query)
        for label in intent_matches(query):
            slot = per_intent.setdefault(label, {"impressions": 0.0, "queries": []})
            slot["impressions"] += impressions
            slot["queries"].append(query)

    def _pack(source: dict[str, dict[str, Any]], key_name: str) -> list[dict[str, Any]]:
        out = []
        for name, slot in source.items():
            out.append({
                key_name: name,
                "impressions": round(slot["impressions"], 2),
                "share": round(slot["impressions"] / total, 4) if total else None,
                "query_count": len(set(slot["queries"])),
                "queries": list(dict.fromkeys(slot["queries"]))[:20],
            })
        out.sort(key=lambda item: (-item["impressions"], str(item[key_name])))
        return out

    return {
        "observed_impressions": round(total, 2),
        "token_support": _pack(per_token, "token"),
        "intent_support": _pack(per_intent, "intent"),
        "metric": "observed_query_share",
        "has_data": bool(total),
    }


# ---------------------------------------------------------------------------
# FASE 4 — Current Title Coverage
# ---------------------------------------------------------------------------

def _intent_covered(label: str, title: str, title_variants: set[str]) -> bool:
    """A intenção aparece no título? (sinônimos, plural/singular, acento)."""
    if label == GENERIC_INTENT:
        return False  # "geral" é coberto pela ENTIDADE (ver title_coverage)
    for alias in intent_phrases(label):
        terms = _alias_terms(alias)
        if not terms:
            continue
        if all(_token_hit(t, title_variants) for t in terms):
            return True
        if f" {fold(alias)} " in f" {fold(title)} ":
            return True
    return False


def significant_tokens(text: Any) -> list[str]:
    """Tokens de CONTEÚDO (sem stopwords/intenção genérica).

    Base para medir cobertura de texto: "quantos anos tem gojo" -> ["gojo"]
    (+ "anos" no vocabulário de intenção), sem as palavras de ligação.
    """
    return [t for t in tokens(text) if not _is_stop(t)]


def query_title_alignment(query: str, doc_title: str) -> float | None:
    """Alinhamento determinístico ENTRE a query e o título de um documento.

    Substitui o antigo ``0.9 if best.get("title") else 0.0`` — que media apenas
    "o documento tem título", algo praticamente sempre verdadeiro e sem relação
    com a query. Reaproveita o mesmo contrato da FASE 4 (entidade + intenção +
    tokens), para não criar uma terceira definição de alinhamento:

        entidade 40%  ·  intenção 40%  ·  tokens significativos 20%

    Componente não medível sai do cálculo (renormalizado). Sem query ou sem
    título o resultado é ``None`` = DESCONHECIDO (nunca 0).
    """
    query_text = str(query or "").strip()
    title_text = str(doc_title or "").strip()
    if not query_text or not title_text:
        return None
    title_variants = expand_variants(tokens(title_text))
    entity = detect_entity(query_text)
    entity_ok: float | None = (1.0 if entity_covered(entity, title_text, title_variants)
                               else 0.0) if entity else None
    intents = intent_matches(query_text)
    if intents:
        hits = sum(1 for label in intents
                   if _intent_covered(label, title_text, title_variants))
        intent_ok: float | None = hits / len(intents)
    else:
        intent_ok = None
    tokens_present = [t for t in tokens(query_text) if not _is_stop(t)]
    if tokens_present:
        hits = sum(1 for t in tokens_present if _token_hit(t, title_variants))
        token_ok: float | None = hits / len(tokens_present)
    else:
        token_ok = None
    parts = [(0.4, entity_ok), (0.4, intent_ok), (0.2, token_ok)]
    known = [(weight, value) for weight, value in parts if value is not None]
    if not known:
        return None
    total = sum(weight for weight, _value in known)
    return round(sum(weight * float(value) for weight, value in known) / total, 4)


def entity_covered(entity: str, title: str, title_variants: set[str]) -> bool:
    """A entidade aparece no título? (qualquer token significativo basta).

    A entidade é o "assunto" da família; um título que carrega "Satoru Gojo"
    cobre a entidade "gojo".
    """
    terms = [t for t in tokens(entity) if len(t) > 2 and not _is_stop(t)]
    if not terms:
        return True
    return any(_token_hit(t, title_variants) for t in terms)


def title_coverage(title: str, families: Sequence[dict[str, Any]], *,
                   shares: dict[str, float] | None = None) -> dict[str, Any]:
    """Quanto da demanda OBSERVADA o título atual já representa (FASE 4).

    Não é overlap lexical bruto: usa o dicionário de intenção (sinônimos),
    aliases de entidade, plural/singular e acentuação. Uma família está coberta
    quando a INTENÇÃO dela está no título (a entidade sozinha não responde
    "quantos anos tem gojo"). Famílias sem intenção específica (`geral`) são
    cobertas quando a ENTIDADE está no título.
    """
    title_clean = re.sub(r"\s+", " ", str(title or "").strip())
    title_variants = expand_variants(tokens(title_clean))
    share_map = shares or {}
    known_shares = any(f.get("share") is not None for f in families)

    covered: list[str] = []
    uncovered: list[str] = []
    detail: list[dict[str, Any]] = []
    coverage = 0.0
    total_known = 0.0
    generic_share = 0.0
    for family in families:
        fid = str(family.get("family_id") or family.get("family") or "")
        share_raw = share_map.get(fid, family.get("share"))
        try:
            share_value = float(share_raw or 0.0)
        except (TypeError, ValueError):
            share_value = 0.0
        entity_ok = entity_covered(str(family.get("entity") or ""), title_clean,
                                   title_variants)
        intent = str(family.get("intent") or GENERIC_INTENT)
        # Família SEM intenção específica (query de entidade: "gojo") não é gap
        # de intenção: quem garante a entidade é o gate `entity_preserved`. Ela
        # fica FORA da cobertura (mas é reportada em `generic_share` — nunca
        # escondida), senão o título "Gojo: poderes" já apareceria cobrindo
        # 50% da demanda só por carregar a entidade.
        if intent == GENERIC_INTENT:
            generic_share += share_value
            detail.append({"family": fid, "intent": intent, "share": round(share_value, 4),
                           "intent_covered": None, "entity_covered": entity_ok,
                           "counted": False})
            continue
        total_known += share_value
        intent_ok = _intent_covered(intent, title_clean, title_variants)
        if intent_ok:
            covered.append(fid)
            coverage += share_value
        else:
            uncovered.append(fid)
        detail.append({
            "family": fid,
            "intent": intent,
            "share": round(share_value, 4),
            "intent_covered": intent_ok,
            "entity_covered": entity_ok,
            "counted": True,
        })
    return {
        "title": title_clean,
        "covered_families": covered,
        "uncovered_families": uncovered,
        "observed_demand_coverage": (round(coverage, 4)
                                    if (known_shares or shares is not None)
                                    else None),
        "observed_share_universe": round(total_known, 4),
        "generic_share": round(generic_share, 4),
        "families": detail,
        "entity_covered": entity_covered(
            _dominant_entity(families), title_clean, title_variants),
        "lens": "intent_dictionary + entity aliases (não overlap lexical bruto)",
    }


def _dominant_entity(families: Sequence[dict[str, Any]]) -> str:
    """Entidade dominante da página (a da família de maior impressão)."""
    if not families:
        return ""
    best = max(families, key=lambda f: float(f.get("impressions", 0) or 0))
    return str(best.get("entity") or "")
