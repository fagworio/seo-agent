"""Sprint 2, item 6 — isolamento de dead URLs (`audit -> dead_url`).

O problema operacional: ~1.900 URLs `/post-N/` devolvem 404, entram no trilho
expresso (`dirty_reason='previous_failure'`) TODO ciclo e consomem o orcamento
normal de auditoria, atrasando a fila de URLs saudaveis. Medido em producao:
`failure_count=4` em todas as 1.900 (acima do `max_attempts=3`) e mesmo assim elas
continuam voltando — o 404 nao e "falha a retentar", e um ESTADO.

Separacao em duas partes, de proposito:

- `classify()`: funcao PURA, sem banco e sem rede. Recebe so' evidencia e devolve
  categoria + motivo. E' o que permite testar a decisao sem infraestrutura e
  reconstruir o motivo depois ("por que esta URL saiu do ciclo?").
- `plan()`: junta a evidencia do banco (existencia no WP, sitemap, historico) e
  chama `classify()`. Nao escreve nada.

A classificacao e' DETERMINISTICA e derivada dos dados reais, nunca de heuristica
de LLM. Ordem das regras (a primeira que casa vence):

1. status que NAO e' 404/410 (5xx, timeout, None) -> `transient`: o servidor pode
   voltar, entao volta para `audit` com backoff.
2. a URL existe no WordPress atual -> `redirect_candidate`: o slug mudou. Procurar
   destino e' valido; REDIRECIONAR AUTOMATICAMENTE NAO E' — sem evidencia de que o
   destino e' o mesmo conteudo vira troca de conteudo em silencio.
3. 404 estavel, nunca teve sucesso e veio do sitemap -> `sitemap_cleanup`: sair da
   fonte (idempotente) e nunca mais consumir `audit`.
4. 404 estavel, nunca teve sucesso e fora do sitemap -> `gone`: sai do ciclo normal.
5. teve 200 em algum momento e agora e' 404 -> `investigate` -> `manual_review`.
   Existiu e sumiu e' decisao humana; o agente nao apaga historico sozinho.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from hermes_seo_agent.lanes import policy as P

__all__ = [
    "CATEGORIES",
    "DEAD_STATUSES",
    "OUT_OF_CYCLE",
    "BACK_TO_AUDIT",
    "Decision",
    "classify",
    "plan",
    "dead_url_work_item_id",
    "backoff_seconds",
    "enqueue_dead_urls",
]

# Categorias (as cinco do item 6). Nao adicionar sem mudar os testes de aceite.
CATEGORIES = ("transient", "redirect_candidate", "gone", "sitemap_cleanup",
              "investigate")

# O que significa "a URL esta morta" (404/410). Qualquer outro status e' instavel
# e merece outra chance: confundir 500 com 404 mata pagina que so' estava fora.
DEAD_STATUSES = (404, 410)

# Categorias que SAEM do ciclo normal de auditoria. `transient` nao esta aqui de
# proposito: e' a unica que volta para `audit`. `redirect_candidate` sai junto
# porque redirecionar sem evidencia de destino seria trocar conteudo em silencio —
# o candidato e' registrado, mas a URL para de consumir audit ate' haver prova.
OUT_OF_CYCLE = ("gone", "sitemap_cleanup", "investigate", "redirect_candidate")

# Categorias que voltam para o audit (com backoff).
BACK_TO_AUDIT = ("transient",)

# Backoff do transient, em segundos, por numero de falhas. Deterministico e
# limitado: 1h, 6h, 24h, 72h (teto) — nunca exponencial infinito.
_BACKOFF = (3600, 6 * 3600, 24 * 3600, 72 * 3600)


def backoff_seconds(failure_count: int) -> int:
    """Backoff deterministico para uma URL instavel (teto de 72h)."""
    idx = max(0, int(failure_count) - 1)
    return _BACKOFF[min(idx, len(_BACKOFF) - 1)]


@dataclass
class Decision:
    """Resultado da classificacao: a categoria, o porque e a prova."""

    url: str
    category: str
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)
    redirect_target: str | None = None

    @property
    def out_of_cycle(self) -> bool:
        return self.category in OUT_OF_CYCLE

    @property
    def back_to_audit(self) -> bool:
        return self.category in BACK_TO_AUDIT

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url, "category": self.category, "reason": self.reason,
            "evidence": self.evidence, "redirect_target": self.redirect_target,
            "out_of_cycle": self.out_of_cycle, "back_to_audit": self.back_to_audit,
        }


def classify(*, url: str, status_code: int | None, failure_count: int = 0,
             in_sitemap: bool = False, exists_in_wp: bool = False,
             had_success: bool = False,
             canonical_url: str | None = None,
             max_attempts: int = 3) -> Decision:
    """Classifica UMA url morta a partir de evidencia. Puro, sem banco e sem rede.

    `canonical_url` so' e' usado como destino CANDIDATO em `redirect_candidate`, e
    mesmo la' nao autoriza escrita: quem redireciona precisa de evidencia de que o
    conteudo e' o mesmo.
    """
    ev: dict[str, Any] = {
        "status_code": status_code, "failure_count": int(failure_count),
        "in_sitemap": bool(in_sitemap), "exists_in_wp": bool(exists_in_wp),
        "had_success": bool(had_success), "max_attempts": int(max_attempts),
    }

    # 1. Nao e' 404/410: servidor instavel, timeout, 5xx. Pode voltar.
    if status_code not in DEAD_STATUSES:
        return Decision(
            url=url, category="transient",
            reason=(f"status {status_code!r} nao e' 404/410: instabilidade, "
                    f"nao remocao definitiva"),
            evidence=ev)

    # 2. Existe no WordPress atual: o slug mudou (ou foi renomeado).
    if exists_in_wp:
        return Decision(
            url=url, category="redirect_candidate",
            reason="url morta mas o conteudo existe no WP atual: slug alterado",
            evidence=ev, redirect_target=canonical_url)

    # 3. Nunca existiu no WP atual e veio do sitemap: limpar a fonte.
    if not had_success and in_sitemap:
        return Decision(
            url=url, category="sitemap_cleanup",
            reason=("404 estavel, nunca auditada com sucesso e presente em fonte "
                    "sitemap: remover da fonte e nao consumir audit de novo"),
            evidence=ev)

    # 4. Nunca existiu: morta mesmo, sai do ciclo.
    if not had_success:
        return Decision(
            url=url, category="gone",
            reason="404 estavel e nenhum sucesso registrado: url inexistente",
            evidence=ev)

    # 5. Existiu e agora e' 404: decisao humana, nunca automatica.
    return Decision(
        url=url, category="investigate",
        reason=(f"ja respondeu 200 e hoje e' 404 com {failure_count} falhas "
                f"(max_attempts={max_attempts}): revisao humana"),
        evidence=ev)


def dead_url_work_item_id(url: str) -> str:
    """Identidade DETERMINISTICA do item de dead_url.

    Mesma URL => mesmo id, entao enfileirar duas vezes e' no-op no `lane_queue`
    (aceite: "mesma URL nao gera trabalho duplicado").
    """
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    return f"dead:{digest}"


def _host_key(url: str) -> str:
    """Chave de comparacao de host: ignora subdominio e esquema.

    Medido em producao: `url_audit_state` guarda `www.unicorniohater.com.br` e
    `wp_post_state` guarda `prod.unicorniohater.com.br` para o MESMO site. Comparar
    host literal daria "nao existe no WP" para toda url do portal.
    """
    from urllib.parse import urlsplit

    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _path_key(url: str) -> str:
    """Caminho normalizado para comparar slugs (percent-encoding resolvido).

    `urllib.parse.unquote` resolve `%e2%80%8b` (zero-width space) e emoji, que em
    producao aparecem em slugs legitimos. Sem normalizar, a comparacao falha por
    encoding e o agente classifica pagina viva como morta.
    """
    from urllib.parse import unquote, urlsplit

    path = urlsplit(url).path
    return unquote(path).strip("/").lower()


def plan(store: Any, url: str, *, audit_row: dict[str, Any] | None = None,
         max_attempts: int = 3) -> Decision:
    """Junta a evidencia do banco para `url` e classifica. NAO escreve nada.

    Fontes (todas ja' existentes, nenhuma abstracao nova):
    - `url_audit_state`: status, contagem de falhas, `sitemap_lastmod`, sucesso.
    - `wp_post_state`: o que existe no portal HOJE (comparado por caminho unico).
    """
    from urllib.parse import urlsplit

    row = audit_row or {}
    if not row:
        achados = store.dead_url_candidates(limit=1, url=url)
        row = achados[0] if achados else {}
    status = row.get("last_status_code")
    status = int(status) if status is not None else None
    failure_count = int(row.get("failure_count") or 0)
    in_sitemap = bool(str(row.get("sitemap_lastmod") or "").strip())
    had_success = bool(str(row.get("last_success_at") or "").strip())

    path = _path_key(url)
    canonical = store.wp_post_state_url_by_path(path) if path else None
    exists = canonical is not None

    return classify(url=url, status_code=status, failure_count=failure_count,
                    in_sitemap=in_sitemap, exists_in_wp=exists,
                    had_success=had_success, canonical_url=canonical,
                    max_attempts=max_attempts)


def candidates(store: Any, *, limit: int = 200,
               url: str | None = None) -> list[dict[str, Any]]:
    """URLs mortas que devem entrar na lane `dead_url` (com a decisao pronta).

    Restrito a `DEAD_STATUSES` e `dirty=1`: url sem 404 confirmado nao entra (nao
    inventar trabalho) e url ja' limpa nao entra de novo.
    """
    rows = store.dead_url_candidates(limit=limit, url=url)

    out: list[dict[str, Any]] = []
    for row in rows:
        url = str(row.get("url") or "")
        if not url:
            continue
        dec = plan(store, url, audit_row=row)
        out.append({"url": url,
                    "work_item_id": dead_url_work_item_id(url),
                    "payload": {"url": url, "decision": dec.as_dict()}})
    return out


def enqueue_dead_urls(store: Any, *, limit: int = 200,
                      url: str | None = None) -> dict[str, Any]:
    """Produtor: classifica os 404 e enfileira na lane `dead_url`.

    So' enfileira — quem aplica o efeito e' o worker (`handlers.handler_dead_url`),
    pelo mesmo motivo dos outros itens: um erro aqui nao pode parar o `audit`.

    Devolve a contagem por categoria para a evidencia do ciclo.
    """
    from hermes_seo_agent.lanes.queue import LaneQueue

    itens = candidates(store, limit=limit, url=url)
    q = LaneQueue(store)
    por_categoria: dict[str, int] = {}
    criados = 0
    for it in itens:
        cat = str((it["payload"].get("decision") or {}).get("category") or "?")
        por_categoria[cat] = por_categoria.get(cat, 0) + 1
        res = q.enqueue("dead_url", it["work_item_id"], url=it["url"],
                        payload=it["payload"], priority=100)
        if res:
            criados += 1
    return {"classificados": len(itens), "enfileirados": criados,
            "por_categoria": por_categoria, "json_aceito": json.dumps(
                por_categoria, ensure_ascii=False)}


# Reexport para o painel/CLI sem duplicar a lista de categorias.
LANE = "dead_url"
DEFAULT_LIMIT = P.lane_limit("dead_url")
