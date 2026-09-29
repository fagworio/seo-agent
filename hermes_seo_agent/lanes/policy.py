"""Sprint 2 — lanes independentes, claim/lease e retry classificado.

A regra central que este pacote existe para garantir:

    NENHUMA lane espera outra terminar.
    NENHUM item ruim segura o lote.
    NENHUM worker possui uma tarefa para sempre.
    NENHUMA escrita é repetida após crash.

Como isso é obtido, concretamente:

* **Lanes separadas** (`LANE_*`): cada tipo de trabalho tem a sua fila, o seu
  teto por ciclo e o seu próprio lote. Uma lane travada ou lenta não consome o
  orçamento nem o cursor das outras (o lote é o resultado de um `claim`, não de
  um iterador compartilhado).
* **Identidade estável** (`work_item_key`): determinística, não autoincrement.
  Enfileirar o mesmo trabalho duas vezes é no-op e uma retomada pós-crash não
  duplica trabalho.
* **Claim atômico + lease** (`LaneQueue.claim`): um worker marca e leva os itens;
  o lease tem validade e volta para a fila se o worker morrer.
* **Fencing token** (`lease_version`): só quem possui a versão ATUAL conclui ou
  escreve. Um worker que voltou de um crash não sobrescreve o sucessor.
* **Retry classificado** (`classify_error` + `backoff_seconds`): cada falha vira
  `retryable | terminal | stale | manual_review`, com backoff exponencial e
  jitter determinístico — nunca "falhou, tenta de novo imediatamente".
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

# -- lanes -------------------------------------------------------------------

LANE_AUDIT = "audit"
LANE_TITLE_DECISION = "title_decision"
LANE_TITLE_EXECUTION = "title_execution"
LANE_MEASUREMENT = "measurement"
LANE_DEAD_URL = "dead_url"
LANE_TECHNICAL = "technical"

ALL_LANES: tuple[str, ...] = (
    LANE_AUDIT, LANE_TITLE_DECISION, LANE_TITLE_EXECUTION,
    LANE_MEASUREMENT, LANE_DEAD_URL, LANE_TECHNICAL,
)

# Backpressure inicial (Sprint 2). Cada limite é independente: nenhum teto global
# amarra uma lane à outra. `0` = ilimitado (mesma convenção de PUBLISH_LIMIT).
DEFAULT_LANE_LIMITS: dict[str, int] = {
    LANE_AUDIT: 200,
    LANE_TITLE_DECISION: 50,
    LANE_TITLE_EXECUTION: 10,
    LANE_MEASUREMENT: 200,
    LANE_DEAD_URL: 50,
    LANE_TECHNICAL: 50,
}

# -- estados -----------------------------------------------------------------

ST_PENDING = "pending"           # na fila, elegível agora
ST_CLAIMED = "claimed"           # com worker (lease ativo)
ST_EXECUTING = "executing"       # worker começou a agir (lease ativo)
ST_RETRY = "retry"               # falhou com erro retryable, aguardando backoff
ST_DONE = "done"                 # concluído
ST_STALE = "stale"               # já aplicado (fingerprint executed): NÃO reexecutar
ST_TERMINAL = "terminal"         # falha definitiva
ST_MANUAL_REVIEW = "manual_review"   # precisa de decisão humana

# Estados que o claim pode pegar.
CLAIMABLE: tuple[str, ...] = (ST_PENDING, ST_RETRY)
# Estados com lease ativo (candidatos a recuperação se o lease expirar).
LEASED: tuple[str, ...] = (ST_CLAIMED, ST_EXECUTING)
# Estados finais: nunca voltam para a fila.
FINAL: tuple[str, ...] = (ST_DONE, ST_STALE, ST_TERMINAL, ST_MANUAL_REVIEW)

# -- classificação de erro ---------------------------------------------------

ERR_RETRYABLE = "retryable"
ERR_TERMINAL = "terminal"
ERR_STALE = "stale"
ERR_MANUAL_REVIEW = "manual_review"

ALL_ERROR_CLASSES: tuple[str, ...] = (
    ERR_RETRYABLE, ERR_TERMINAL, ERR_STALE, ERR_MANUAL_REVIEW,
)

_RETRYABLE_HINTS = (
    "timeout", "timed out", "connection", "temporar", "rate limit", "ratelimit",
    "429", "500", "502", "503", "504", "unavailable", "incompleteread",
    "remote end closed", "reset by peer",
)
_MANUAL_HINTS = (
    "unauthorized", "forbidden", "401", "403", "not found", "404", "410",
    "invalid", "validation", "schema", "no such column", "unsupported",
)
_STALE_HINTS = ("staleaction", "stale", "already executed", "precondition")


def classify_error(exc: BaseException | str, *, kind: str | None = None) -> str:
    """Classifica a falha em `retryable | terminal | stale | manual_review`.

    A classificação decide o destino do item, então ela é explícita:

    * `stale` — a ação já foi aplicada (fingerprint executado) ou a precondição
      mudou. NÃO reexecutar: repetir aqui é justamente a escrita duplicada.
    * `retryable` — transitório (rede, timeout, rate-limit, 5xx). Volta com
      backoff; depois de `max_attempts` vira `manual_review` (nunca loop infinito).
    * `terminal` — definitivo e conhecido; sai da fila para sempre.
    * `manual_review` — precisa de decisão humana (auth/permissão, payload
      inválido, 404/410 em URL que deveria existir).

    Conservador por desenho: o que é desconhecido é `retryable` (limitado por
    `max_attempts`), porque descartar trabalho por um erro mal classificado é pior
    do que tentar de novo poucas vezes.
    """
    if kind in ALL_ERROR_CLASSES:
        return str(kind)
    name = type(exc).__name__ if isinstance(exc, BaseException) else ""
    text = f"{name} {exc}".lower()
    if any(h in text for h in _STALE_HINTS):
        return ERR_STALE
    if any(h in text for h in _RETRYABLE_HINTS):
        return ERR_RETRYABLE
    if any(h in text for h in _MANUAL_HINTS):
        return ERR_MANUAL_REVIEW
    return ERR_RETRYABLE


RETRY_BASE_SECONDS = 30
RETRY_MAX_SECONDS = 3600


def backoff_seconds(attempt: int, *, base: int = RETRY_BASE_SECONDS,
                    cap: int = RETRY_MAX_SECONDS, seed: str = "") -> int:
    """Backoff exponencial com jitter DETERMINÍSTICO.

    Exponencial porque insistir no mesmo erro agrava (rate-limit de Bing/Google,
    GA4 fora do ar). O jitter impede que N workers acordem no mesmo instante — e
    vem do hash do item, não de `random`: o mesmo item tem sempre o mesmo atraso,
    o que mantém o comportamento reproduzível em teste.
    """
    n = max(1, int(attempt))
    delay = min(int(cap), int(base) * (2 ** (n - 1)))
    if seed:
        digest = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16)
        spread = max(1, delay // 4)
        delay += digest % spread
    return int(min(int(cap), delay))


def work_item_key(lane: str, *parts: Any) -> str:
    """Identidade ESTÁVEL e determinística do work item.

    Determinismo é o ponto: o mesmo trabalho produz o mesmo id em qualquer
    processo, então enfileirar duas vezes é no-op (`UNIQUE(lane, work_item_id)`) e
    uma retomada pós-crash não duplica trabalho. Partes muito longas (payloads)
    viram digest para o id continuar legível e curto.
    """
    raw = "|".join(str(p) for p in parts if p is not None and p != "")
    if len(raw) > 120:
        raw = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"{lane}:{raw}"


def normalize_limit(limit: int | None) -> int | None:
    """Semântica ÚNICA de teto no projeto: `0` (ou negativo/None) = ILIMITADO.

    Existe porque `LIMIT 0` no SQLite significa "zero linhas", não "sem limite" —
    passar o zero direto para o SQL inverte o significado e transforma um teto
    "desligado" em "não faça nada". Aqui o zero vira `None` (ausência de LIMIT),
    que é o que o chamador quis dizer. Mesma convenção de `PUBLISH_LIMIT=0`.
    """
    if limit is None:
        return None
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def lane_limit(lane: str, config: Any = None, default: int | None = None) -> int:
    """Teto de itens por ciclo da lane (backpressure independente).

    Precedência: `config.lane_limits[lane]` > `config.lane_limit_<lane>` > default
    do mapa. É config, não constante: cada lane tem o seu teto e ajustar uma não
    mexe nas outras. Semântica: `0` = ILIMITADO (ver `normalize_limit`); nunca
    passe esse zero cru para um `LIMIT`.
    """
    if config is not None:
        limits = getattr(config, "lane_limits", None)
        value: Any = None
        if isinstance(limits, dict) and lane in limits:
            value = limits[lane]
        else:
            value = getattr(config, f"lane_limit_{lane}", None)
        if value is not None:
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                pass
    if default is not None:
        return default
    return DEFAULT_LANE_LIMITS.get(lane, 50)


# -- tempo (ISO-8601 UTC, comparável como string) -----------------------------

def utc_now() -> str:
    """Agora em ISO-8601 UTC com offset explícito (`+00:00`).

    Sempre o mesmo formato: os leases são comparados como string no SQLite, então
    misturar `Z` com `+00:00` quebraria a comparação de expiração.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def plus_seconds(ts: str, seconds: int) -> str:
    base = parse_ts(ts)
    return (base + timedelta(seconds=int(seconds))).replace(
        microsecond=0).isoformat()


def parse_ts(ts: str) -> datetime:
    """Parse tolerante: aceita `Z`, offset ausente e fração de segundo."""
    text = str(ts).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def age_seconds(ts: str | None, now: str | None = None) -> int | None:
    """Idade em segundos (int) — base do `oldest_pending_age`."""
    if not ts:
        return None
    delta = parse_ts(now or utc_now()) - parse_ts(ts)
    return int(max(0, delta.total_seconds()))


# -- serialização de payload --------------------------------------------------

def dumps_payload(payload: Any) -> str | None:
    if payload is None:
        return None
    try:
        return json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return json.dumps({"_unserializable": str(payload)}, ensure_ascii=False)


def loads_payload(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None
