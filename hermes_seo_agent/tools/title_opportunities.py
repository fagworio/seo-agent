"""Title opportunity research — strategic, GSC + Google Trends grounded.

The old generator turned the raw top GSC query into a title-cased fragment
("gojo" -> "Gojo", "highie" -> "Highie") — often WORSE than the current
title. The strategic generator makes a data-driven decision:

1. It keeps the page's ENTITY (the work/subject already in the title — the
   indexed identity that must not be lost).
2. It scores the page's real GSC queries by statistical value: position,
   impressions (log), CTR, and — when Trends answers — market interest and
   momentum (rising/falling) in the last 90 days.
3. It only proposes a title when a high-value query is NOT already covered
   by the current title (no candidate = current title already optimal).
4. The candidate is built by injecting the missing keyword into the current
   title, never by replacing it with a bare fragment.

This is the "crossing of SEO data with Google connections" (Search Console +
Trends) for the title decision — the keyword choice is a statistic, not an
opinion.
"""

from __future__ import annotations

import math
import re
from typing import Any

# Prepositions/articles that stay lowercase in a title-case candidate.
_SMALL = {"a", "o", "os", "as", "de", "da", "do", "das", "dos", "e", "em",
          "no", "na", "nos", "nas", "para", "com", "um", "uma", "uns", "umas",
          "que", "por", "até", "the", "of", "and", "in", "to"}
# Words that carry no keyword value (skip when checking coverage).
_STOP = _SMALL | {"como", "qual", "quais", "quanto", "quantos", "quando",
                  "onde", "porque", "serie", "sao", "foi", "era", "tem", "ter"}

# SEO-INC-018: grupos de INTENCAO. Cobrir a ENTIDADE nao cobre a INTENCAO:
# "quantos anos tem gojo" exige idade/anos no titulo — "Gojo: poderes e
# historia" nao responde a pergunta. Antes isso passava na regra lexical de 50%
# e o pipeline concluia "query ja coberta" (deixando de achar o gap real).
INTENT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("idade", ("idade", "anos", "velho", "nascimento", "nasceu", "aniversario")),
    ("altura", ("altura", "mede", "metro", "tamanho")),
    ("morte", ("morte", "morreu", "morre", "falecido", "morrido")),
    ("elenco", ("elenco", "ator", "atriz", "dublador", "dubladora", "quem faz")),
    ("ordem", ("ordem", "cronologia", "sequencia")),
    ("onde_assistir", ("assistir", "streaming", "plataforma", "onde ver")),
    ("final", ("explicado", "o final")),
    ("poderes", ("poder", "habilidade", "habilidades", "fraqueza", "skill")),
    ("preco", ("preco", "custa", "valor", "barato")),
    ("estreia", ("estreia", "lancamento", "quando sai", "data de")),
)


def intent_terms(query: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Grupos de INTENCAO presentes na query (SEO-INC-018).

    Cada grupo devolvido precisa estar representado no titulo (por qualquer
    variante) para a query ser considerada coberta — a entidade sozinha nao
    responde a intencao.
    """
    q_tokens = _tokens(query)
    frase = " " + " ".join(re.findall(r"[a-zà-ú0-9]+", (query or "").lower())) + " "
    out: list[tuple[str, tuple[str, ...]]] = []
    for label, variantes in INTENT_GROUPS:
        if any(_norm_word(v) in q_tokens or v in frase for v in variantes):
            out.append((label, variantes))
    return tuple(out)


def pick_top_query(rows: list[dict[str, Any]]) -> str:
    """Legacy: highest-value raw query (kept for backward compatibility)."""
    if not rows:
        return ""
    meaningful = [r for r in rows if float(r.get("impressions", 0)) >= 2]
    pool = meaningful or rows
    pool = sorted(
        pool,
        key=lambda r: (float(r.get("position", 100)), -float(r.get("impressions", 0))),
    )
    return (pool[0].get("keys") or [""])[0]


def candidate_title(query: str, *, max_len: int = 60) -> str:
    """Legacy: title-case of a raw query (kept for backward compatibility)."""
    query = re.sub(r"\s+", " ", (query or "").strip())
    if not query:
        return ""
    words = query.split()
    out: list[str] = []
    for index, word in enumerate(words):
        lower = word.lower()
        if index == 0 or lower not in _SMALL:
            out.append(word.capitalize())
        else:
            out.append(lower)
    title = " ".join(out)
    if len(title) > max_len:
        title = title[:max_len].rstrip()
    return title


# --------------------------------------------------------------------------
# Strategic generator (GSC x Trends)
# --------------------------------------------------------------------------

def discover_momentum(
    daily_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Site-wide Google Discover signal from daily rows.

    Returns {impressions, clicks, active_days, momentum} where momentum is
    +1 (Discover accelerating: second half > first half +15%), -1 (losing
    reach) or 0 (stable). Discover is site-wide only (the API forbids
    page/query dimensions under the type filter) — this signal tells the
    agent WHEN discovery-style titles/content are worth prioritizing.
    """
    impressions = sum(float(r.get("impressions", 0)) for r in daily_rows)
    clicks = sum(float(r.get("clicks", 0)) for r in daily_rows)
    active = sum(1 for r in daily_rows if float(r.get("impressions", 0)) > 0)
    n = len(daily_rows)
    if n >= 6:
        half = max(n // 2, 1)
        recent = sum(float(r.get("impressions", 0)) for r in daily_rows[-half:])
        previous = sum(float(r.get("impressions", 0)) for r in daily_rows[: n - half])
        if previous <= 0:
            momentum = 1 if recent > 0 else 0
        else:
            delta = (recent - previous) / previous
            momentum = 1 if delta > 0.15 else (-1 if delta < -0.15 else 0)
    else:
        momentum = 0
    return {
        "impressions": round(impressions),
        "clicks": round(clicks),
        "active_days": active,
        "momentum": momentum,
    }


def shorten_title(
    current_title: str,
    *,
    max_len: int = 60,
    brand: str = "UnicornioHater",
) -> str | None:
    """Deterministic title shortening (title_too_long safe_fix).

    Conservative rules, in order:
    1. Strip the trailing brand (" — UnicornioHater"): the brand has zero
       search value and is the usual cause of >65 chars.
    2. If still too long, keep the ENTITY (text before ':') and trim the
       description at a word boundary so the whole fits max_len.
    3. Never drop the entity, never cut mid-word, never return a title that
       is not shorter than the input.

    Returns None when the title cannot be safely shortened (rare).
    """
    title = re.sub(r"\s+", " ", (current_title or "").strip())
    if not title:
        return None
    if len(title) <= max_len:
        return None  # nothing to fix

    # 1) drop brand suffix "— UnicornioHater" / "- UnicornioHater"
    candidate = re.sub(
        r"\s*[—–-]\s*" + re.escape(brand) + r"\s*$", "", title).strip()
    if not candidate:
        return None
    if len(candidate) <= max_len:
        return candidate if candidate != title else None

    # 2) keep entity + trimmed description at a word boundary (work on the
    # brand-stripped candidate — the brand has zero search value).
    base = candidate
    entity = base
    rest = ""
    if ":" in base:
        entity, rest = base.split(":", 1)
        entity = entity.strip()
        rest = rest.strip()
    if not entity:
        return None
    if not rest:
        # No "entity:" split (news/question headlines): keep the leading
        # words — the main information comes first — cut at a word boundary.
        words = re.findall(r"\S+", base)
        out: list[str] = []
        for word in words:
            if len(" ".join(out + [word])) <= max_len - 1:
                out.append(word)
            else:
                break
        if not out or " ".join(out) == base:
            return None
        return " ".join(out).rstrip("…,;:") + "…"
    budget = max_len - len(entity) - 2  # ": " prefix
    if budget < 10:
        if len(entity) <= max_len - 1 and len(entity) + 2 >= len(base):
            # Entity alone nearly IS the title (tiny description): dropping
            # the description loses almost nothing.
            return entity if entity != base else None
        # Entity too long for a comfortable ": desc" split: truncate the
        # WHOLE headline at a word boundary (keeps entity + start of desc).
        words = re.findall(r"\S+", base)
        out: list[str] = []
        for word in words:
            if len(" ".join(out + [word])) <= max_len - 1:
                out.append(word)
            else:
                break
        if not out or " ".join(out) == base:
            return None
        return " ".join(out).rstrip("…,;:") + "…"
    words = re.findall(r"\S+", rest)
    trimmed: list[str] = []
    for word in words:
        if len(" ".join(trimmed + [word])) <= budget:
            trimmed.append(word)
        else:
            break
    if not trimmed:
        return entity if len(entity) <= max_len and entity != base else None
    candidate = f"{entity}: {' '.join(trimmed)}".strip()
    if len(candidate) > max_len:
        candidate = candidate[: max_len - 1].rstrip() + "…"
    if candidate == base or len(candidate) >= len(base):
        return None
    return candidate


def _norm_word(word: str) -> str:
    """Normaliza p/ comparacao: sem acento, singular simples (s final).

    Evita propor titulo para query ja coberta por plural/acento diferente
    ('reinos' vs 'reino', 'aneis' vs 'Anéis').
    """
    import unicodedata

    w = unicodedata.normalize("NFKD", word).encode("ascii", "ignore").decode().lower()
    if len(w) > 3 and w.endswith("s"):
        w = w[:-1]
    return w


def _tokens(text: str) -> set[str]:
    """Significant lowercase tokens (no stopwords, no punctuation)."""
    words = re.findall(r"[a-zà-ú0-9]+", (text or "").lower())
    return {_norm_word(w) for w in words if len(w) > 2 and w not in _STOP}


def entity_of(current_title: str) -> str:
    """The indexed identity of the page: text before ':' or the first ' — '.

    "Hughie Campbell: poderes e tudo sobre The Boys — UnicornioHater"
    -> "Hughie Campbell". Keeps entity first in any candidate.
    """
    title = re.sub(r"\s+", " ", (current_title or "").strip())
    title = re.split(r"\s+[—–-]\s+", title)[0].strip()
    if ":" in title:
        title = title.split(":", 1)[0].strip()
    return title or title.strip()


def _query_value(row: dict[str, Any], trends: dict[str, Any] | None,
                 ga4: dict[str, Any] | None = None) -> float:
    """Statistical value of a GSC query row, enriched by Trends and GA4.

    GSC part: log10(impressions) * position_factor * (1 + ctr).
    Trends part (optional): interest 0..100 normalized + momentum bonus.
    GA4 part (optional): engagement factor -- quem clica e fica vale mais.
    """
    impressions = max(float(row.get("impressions", 0)), 1.0)
    position = max(float(row.get("position", 10)), 1.0)
    ctr = max(float(row.get("ctr", 0)), 0.0)
    position_factor = 1.0 / math.sqrt(position)  # pos 1 = 1.0, pos 10 = 0.32
    gsc = math.log10(impressions + 1) * position_factor * (1.0 + ctr * 5)
    if trends:
        interest = trends.get("interest")
        if isinstance(interest, (int, float)):
            gsc *= 1.0 + min(float(interest) / 100.0, 1.0) * 0.6
        momentum = trends.get("momentum", 0)
        gsc *= 1.0 + float(momentum) * 0.25
    gsc *= _engagement_factor(ga4)
    return gsc


def _engagement_factor(ga4: dict[str, Any] | None) -> float:
    """Fator de engajamento (GA4) para o score do candidato.

    Uma pagina que RETEÉM quem clica (engagement_rate alto) merece mais
    investimento de titulo: mais cliques tendem a virar leitura. Pagina que
    nao retém (bounce) nao deve ganhar prioridade. Amostra pequena = neutro.
    """
    if not ga4:
        return 1.0
    try:
        sessions = float(ga4.get("sessions") or 0)
    except (TypeError, ValueError):
        return 1.0
    if sessions < 5:
        return 1.0
    er = ga4.get("engagement_rate")
    if not isinstance(er, (int, float)):
        return 1.0
    # 0.5 = neutro; 1.0 -> 1.20; 0.0 -> 0.80 (limitado a [0.7, 1.3])
    return max(0.7, min(1.3, 1.0 + (float(er) - 0.5) * 0.4))


def _covered(query: str, current_title: str) -> bool:
    """True when the current title already covers the query keywords AND intent.

    Coverage = fraction of significant query tokens present in the title.
    Tokens of <=3 chars (acronyms like "mha", "ps5") are ambiguous and never
    count as missing. A query is covered at >=50%: "eri mha idade" vs
    "Quantos anos tem Eri em My Hero Academia?" -> eri present, idade absent,
    mha ignored => 1/2 = 50% => covered (the intent is already answered).

    SEO-INC-018: além dos 50% lexicais, TODOS os grupos de intenção presentes
    na query precisam aparecer no título. "Gojo: poderes e história" não cobre
    "quantos anos tem gojo" (falta idade/anos), ainda que cubra a entidade.
    """
    q_tokens = _tokens(query)
    if not q_tokens:
        return True
    title_tokens = _tokens(current_title)
    hits = sum(1 for t in q_tokens if t in title_tokens)
    # Missing tokens of <=3 chars (acronyms "mha"/"ps5") never count as a
    # gap; missing longer tokens do. Covered at >=50% of the required set.
    missing_long = [t for t in q_tokens if t not in title_tokens and len(t) > 3]
    required = hits + len(missing_long)
    if required == 0:
        return True
    if hits < required * 0.5:
        return False
    # Intenção (SEO-INC-018): entidade coberta não basta.
    title_low = (current_title or "").lower()
    for _label, variantes in intent_terms(query):
        coberto = False
        for v in variantes:
            if _norm_word(v) in title_tokens or v in title_low:
                coberto = True
                break
        if not coberto:
            return False
    return True


def empirical_title_case(
    *,
    impressions: float,
    ctr: float,
    position: float | None,
    baseline_verdict: dict[str, Any] | None,
    query: str,
    query_impressions: float,
    title: str,
    ga4: dict[str, Any] | None = None,
    trends: dict[str, Any] | None = None,
    min_impressions: float = 100.0,
    min_query_impressions: float = 10.0,
    max_position: float = 30.0,
) -> dict[str, Any]:
    """Cadeia de EVIDENCIA para decidir alterar um titulo (SEO-INC-019).

    Substitui o gatilho heuristico "CTR <= 2%". Exige, simultaneamente:

      1. demanda real        — impressoes da pagina E da query de valor
      2. anomalia real       — CTR abaixo do P10 do PROPRIO segmento (baseline)
      3. intencao            — query de valor identificada no GSC
      4. gap                 — intencao nao representada no titulo atual
      5. posicao acionavel   — a pagina ja e competitiva o suficiente
      6. pos-clique saudavel — GA4 nao mostra experiencia claramente ruim

    GA4 e Trends **priorizam**, nunca criam a necessidade. Sem qualquer elo
    critico, a acao degrada para `investigate`/`monitor`/`gather_more_data`.
    O retorno carrega a evidencia citavel (auditavel), nao so a decisao.
    """
    checks: dict[str, bool] = {
        "impressions_sufficient": float(impressions or 0) >= min_impressions,
        "query_demand": float(query_impressions or 0) >= min_query_impressions,
        # Alta confiança: a anomalia precisa ser de SEVERIDADE (abaixo do P10 do
        # segmento ou `below_comparable`). O veredicto `low` (entre P10 e P25) é
        # sinal mais FRACO: fica registrado em `ctr_low` e, no máximo, leva a
        # `investigate_cause` — nunca a reescrever título.
        "ctr_below_baseline": str((baseline_verdict or {}).get("verdict")
                                  or "") in {"below_p10", "below_comparable"},
        "query_title_gap": bool(query) and not _covered(query, title),
        # Sem posição NÃO é "acionável": cadeia completa exige o dado (antes
        # position=None passava como True e a proposta saía sem esse alicerce).
        "position_actionable": position is not None and float(position) <= max_position,
    }
    checks["ctr_low"] = str((baseline_verdict or {}).get("verdict") or "") == "low"
    engagement_note = ""
    ga4_known = False
    ga4_data: dict[str, Any] = ga4 or {}
    if ga4_data:
        try:
            ga4_known = float(ga4_data.get("sessions") or 0) >= 5
        except (TypeError, ValueError):
            ga4_known = False
    if ga4_known:
        er = ga4_data.get("engagement_rate")
        try:
            if er is not None and float(er) < 0.30:
                checks["post_click_healthy"] = False
                engagement_note = "engajamento pós-clique baixo (GA4 < 30%)"
        except (TypeError, ValueError):
            ga4_known = False
    checks.setdefault("post_click_healthy", True)

    criticos = ("impressions_sufficient", "query_demand", "ctr_below_baseline",
                "query_title_gap", "position_actionable", "post_click_healthy")
    faltando = [k for k in criticos if not checks.get(k)]

    if not faltando:
        action = "review_title"
        # GA4 ausente é AUSÊNCIA DE EVIDÊNCIA: não bloqueia (a decisão não é
        # sobre pós-clique), mas rebaixa a confiança — nunca `high` sem dado.
        confidence = "high" if ga4_known else "medium"
    elif not checks["impressions_sufficient"] or not checks["query_demand"]:
        action, confidence = "gather_more_data", "low"
    elif "query_title_gap" in faltando:
        action, confidence = "no_title_change", "medium"
    else:
        action, confidence = "investigate_cause", "medium"

    razoes = []
    if checks["ctr_below_baseline"]:
        b = baseline_verdict or {}
        razoes.append(f"CTR abaixo do P10 do próprio segmento "
                      f"({b.get('context') or 'n/d'}; n={b.get('sample_size') or 0})")
    if checks["query_demand"]:
        razoes.append(f"query '{query}' com demanda comprovada "
                      f"({int(query_impressions)} impressões)")
    if checks["query_title_gap"]:
        razoes.append("intenção não coberta pelo título atual")
    if checks["position_actionable"] and position is not None:
        razoes.append(f"posição já competitiva ({float(position):.1f})")
    if checks["post_click_healthy"] and ga4:
        razoes.append("engajamento pós-clique saudável")
    if engagement_note:
        razoes.append(engagement_note)
    if trends and float(trends.get("interest") or 0) >= 50:
        razoes.append(f"interesse de busca em alta (Trends {int(float(trends['interest']))})")

    return {
        "action": action,
        "confidence": confidence,
        "checks": checks,
        "missing": faltando,
        "reason": razoes,
        # Evidencia auditavel — quem le a Caixa consegue reproduzir a decisao.
        "evidence": {
            "gsc": {"impressions": impressions, "ctr": ctr, "position": position,
                    "query": query, "query_impressions": query_impressions},
            "baseline": baseline_verdict or {},
            "alignment": {"query": query, "title": title,
                          "intent_covered": not checks["query_title_gap"]},
            "ga4": ga4 or {},
            "trends": trends or {},
            # O GSC devolve principalmente as linhas principais (por design do
            # Google): "sem gap" significa "entre as queries OBSERVAVEIS a
            # intencao esta coberta", nunca "conhecemos todas as buscas".
            "query_evidence": {"source": "gsc_query_page",
                               "coverage": "partial"},
        },
    }


def strategic_title(
    current_title: str,
    queries: list[dict[str, Any]],
    trends: dict[str, dict[str, Any]] | None = None,
    *,
    max_len: int = 60,
    ga4: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Data-driven title decision for one page.

    ``queries``: GSC query rows [{keys:[q], impressions, position, ctr}].
    ``trends``: {query: {interest, momentum}} de batch_trends (provider Trends
    cacheado; pode ser parcial — queries ausentes recebem tendência neutra).
    ``ga4``: métricas de engajamento da página (sessions, engagement_rate,
    engagement_time) — a página que retém quem clica pesa mais na decisão.

    Returns None when the current title already covers the best uncovered
    high-value query, or when no query beats the threshold (current title is
    optimal). Otherwise a dict:
      {title, keyword, rationale, score, trends}
    """
    title_clean = re.sub(r"\s+", " ", (current_title or "").strip())
    if not queries or not title_clean:
        return None
    trends = trends or {}
    entity = entity_of(title_clean)

    scored: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for row in queries:
        query = (row.get("keys") or [""])[0]
        if not query:
            continue
        tr = trends.get(query, {"interest": None, "momentum": 0})
        value = _query_value(row, tr, ga4)
        scored.append((value, row, tr))
    scored.sort(key=lambda x: x[0], reverse=True)

    # Best query that is NOT already covered by the current title.
    for value, row, tr in scored:
        query = (row.get("keys") or [""])[0]
        if _covered(query, title_clean):
            continue
        impressions = float(row.get("impressions", 0))
        position = float(row.get("position", 0))
        ctr = float(row.get("ctr", 0))
        # Statistical threshold: meaningful demand worth a title change.
        if impressions < 5 or position > 30:
            continue
        q_tokens = _tokens(query)
        # Fragments of a single word ("gojo", "highie", "eri") are usually
        # typos or bare entities already covered — never propose them.
        if len(q_tokens) < 2:
            continue
        keyword = candidate_title(query, max_len=40)
        keyword = re.sub(r"\s*—.*$", "", keyword).strip()
        if not keyword:
            continue
        # Build: ENTITY: description + keyword. A keyword entra INTEIRA (frase)
        # — remover tokens no meio gera fragmentos sem sentido (defeito real:
        # "…: Reinos de dos Aneis"). Se TODOS os tokens significativos da query
        # ja estao no titulo (normalizado: sem acento/plural), nao ha o que
        # propor (evita churn e regressao).
        description = title_clean
        if ":" in title_clean:
            description = title_clean.split(":", 1)[1].strip()
        description = re.sub(r"\s+[—–-]\s+.*$", "", description).strip()
        sig_kw = [w for w in keyword.split() if w.lower() not in _STOP]
        if not sig_kw:
            continue
        full_tokens = _tokens(title_clean) | _tokens(f"{entity} {description}")
        if all(_norm_word(w) in full_tokens for w in sig_kw):
            continue
        # Remove tokens JA presentes apenas nas BORDAS da keyword (preserva a
        # frase interna — remover no meio gera fragmentos). Evita duplicar a
        # entidade ("The Boys: Onda Choque Boys").
        _preps_kw = {"de", "da", "do", "das", "dos", "em", "no", "na", "e",
                     "para", "com", "que", "a", "o", "the"}
        kw = list(sig_kw)
        while kw and (_norm_word(kw[0]) in full_tokens or kw[0].lower() in _preps_kw):
            kw.pop(0)
        while kw and (_norm_word(kw[-1]) in full_tokens or kw[-1].lower() in _preps_kw):
            kw.pop()
        if not kw:
            continue
        kw_extra = " ".join(kw)
        candidate = f"{entity}: {description} {kw_extra}".strip()
        if len(candidate) > max_len:
            # Shorter: ENTITY: keyword (entity is the indexed identity).
            candidate = f"{entity}: {kw_extra}".strip()
        if len(candidate) > max_len:
            candidate = candidate[: max_len - 1].rstrip() + "…"
        # Guard de sanidade: nunca publicar titulo com preposicao duplicada
        # ("de dos") nem terminando em preposicao solta.
        _preps = {"de", "da", "do", "das", "dos", "em", "no", "na",
                  "e", "para", "com", "que", "a", "o"}
        palavras = candidate.lower().split()
        if any(palavras[i] in _preps and palavras[i + 1] in _preps
               for i in range(len(palavras) - 1)):
            continue
        # Guard: nao repetir a mesma palavra significativa (ex.: "Shadowfax:
        # Senhor Cavalos Senhor Aneis" — a keyword recolocou um token que o
        # titulo ja carregava). Titulo robotico/regressivo: nao propor.
        from collections import Counter as _Counter

        _sig = [_norm_word(w) for w in palavras if _norm_word(w) not in _STOP]
        if _sig and _Counter(_sig).most_common(1)[0][1] > 1:
            continue
        while palavras and palavras[-1].strip("…") in _preps:
            candidate = " ".join(candidate.split()[:-1]).strip()
            palavras = candidate.lower().split()
        if not candidate or candidate.lower() == title_clean.lower():
            return None
        momentum_txt = {1: "em alta", 0: "estavel", -1: "em queda"}.get(
            int(tr.get("momentum", 0)), "estavel"
        )
        interest_txt = (
            f"{tr['interest']:.0f}/100 no Google Trends"
            if isinstance(tr.get("interest"), (int, float))
            else "sem dado de Trends"
        )
        ga4_txt = ""
        if ga4 and isinstance(ga4.get("sessions"), (int, float)) and float(ga4.get("sessions") or 0) > 0:
            _er = ga4.get("engagement_rate")
            _et = ga4.get("engagement_time")
            ga4_txt = (
                f"; GA4: {float(ga4['sessions']):.0f} sessoes"
                + (f", {float(_er)*100:.0f}% engajamento" if isinstance(_er, (int, float)) else "")
                + (f", {float(_et):.0f}s de tempo" if isinstance(_et, (int, float)) and float(_et) > 0 else "")
            )
        rationale = (
            f"query '{query}': {impressions:.0f} impressoes, posicao "
            f"{position:.1f}, CTR {ctr*100:.1f}%; {interest_txt} "
            f"({momentum_txt} 90d){ga4_txt}"
        )
        return {
            "title": candidate,
            "keyword": query,
            "rationale": rationale,
            "score": round(value, 3),
            "trends": tr,
            "ga4": ga4 or {},
            "gsc": {"impressions": impressions, "position": position,
                    "ctr": ctr},
        }
    return None
