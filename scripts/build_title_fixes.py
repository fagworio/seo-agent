"""Gera title-shortener-fixes.json para os findings title_too_long.

Deterministico, sem LLM. Para cada URL com finding `title_too_long`:
  1. resolve o post_id via wp_post_state (sem REST);
  2. le o rank_math_title AO VIVO via REST (fonte da verdade);
  3. se o rm vivo <= 65 chars, PULA (o finding e ghost: ja corrigido);
  4. senao encurta o rm vivo com shorten_title (mantem entidade, remove
     marca, corte em fronteira de palavra) e monta a acao no formato do
     executor (wp_post_meta / rank_math_title).

Por que a leitura ao vivo: a tabela `findings` e cumulativa e o
corpus_documents.title pode estar stale -> gerar a partir deles produzia
churn (o executor pulava 10 acoes/run como "already executed" e a janela
nunca avancava). O rm vivo elimina ghost e mantem a janela util.

O executor re-verifica por REST apos o write (unverified = falha).

Roda: .venv/bin/python scripts/build_title_fixes.py [--limit N]
(--limit = numero maximo de leituras REST / acoes por run; default 100,
 --limit 0 = sem teto. Sem teto o script consulta o backlog INTEIRO via REST.)
"""
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hermes_seo_agent.config import load_config  # noqa: E402
from hermes_seo_agent.connectors.wordpress import WordPressClient  # noqa: E402
from hermes_seo_agent.storage.db import Storage  # noqa: E402
from hermes_seo_agent.tools.title_opportunities import shorten_title  # noqa: E402

DEFAULT_LIMIT = 100
if "--limit" in sys.argv:
    limit = int(sys.argv[sys.argv.index("--limit") + 1])
else:
    # Sem --limit: teto default (evita consultar o backlog inteiro via REST).
    limit = DEFAULT_LIMIT


def _rest_status(exc: BaseException) -> int | None:
    """Extract an HTTP status from httpx or the connector's wrapped error."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status is not None:
        try:
            return int(status)
        except (TypeError, ValueError):
            pass
    match = re.search(r"\b(?:HTTP|status)[ =:]?(\d{3})\b", str(exc), re.I)
    return int(match.group(1)) if match else None


def _rest_error_category(exc: BaseException) -> str:
    status = _rest_status(exc)
    if status in {408, 425, 429, 500, 502, 503, 504}:
        return "transient_http"
    if status in {401, 403}:
        return "auth_or_permission"
    if status == 404:
        return "not_found"
    if status is not None and 400 <= status < 500:
        return "client_http"
    message = str(exc).lower()
    if any(token in message for token in ("timeout", "timed out", "connect", "dns")):
        return "transport_timeout"
    return "transport_or_connector"


def _get_post_with_retry(wp, post_id: int, *, retries: int = 2):
    """Retry only errors that may clear without changing credentials/data."""
    attempts = 0
    while True:
        attempts += 1
        try:
            return wp.get_post(post_id), attempts
        except Exception as exc:  # noqa: BLE001 - categorized for the report
            category = _rest_error_category(exc)
            if category not in {"transient_http", "transport_timeout",
                                "transport_or_connector"} or attempts > retries:
                raise
            time.sleep(min(0.25 * attempts, 1.0))

cfg = load_config()
storage = Storage(cfg.sqlite_path)
rows = storage.conn.execute(
    "SELECT url, MAX(created_at) mx FROM findings WHERE rule_id = 'title_too_long' "
    "GROUP BY url ORDER BY mx DESC"
).fetchall()
urls = [r[0] for r in rows]
print(f"{len(urls)} URLs title_too_long no DB (cumulativo)")

id_by_slug = {u.rstrip("/").split("/")[-1]: pid for u, pid in storage.conn.execute(
    "SELECT url, post_id FROM wp_post_state").fetchall()}

wp = WordPressClient(cfg)
fixes = []
checked = 0
ghost = 0
no_post = 0
rest_err = 0
diagnostics = {
    "transient_http": 0,
    "transport_timeout": 0,
    "transport_or_connector": 0,
    "auth_or_permission": 0,
    "not_found": 0,
    "client_http": 0,
    "missing_rank_math_title": 0,
}
rest_attempts = 0
for url in urls:
    if limit and checked >= limit:
        break
    slug = url.rstrip("/").split("/")[-1]
    post_id = id_by_slug.get(slug)
    if not post_id:
        no_post += 1
        continue
    checked += 1
    try:
        post, attempts = _get_post_with_retry(wp, int(post_id))
        rest_attempts += attempts
    except Exception as exc:  # noqa: BLE001
        rest_err += 1
        # Re-run categorization locally so failures remain useful even when the
        # connector wraps the original HTTP exception.
        category = _rest_error_category(exc)
        diagnostics[category] = diagnostics.get(category, 0) + 1
        continue
    live = (((post or {}).get("meta") or {}).get("rank_math_title") or "").strip()
    if not live:
        diagnostics["missing_rank_math_title"] += 1
        continue
    if len(live) <= 65:
        ghost += 1
        continue
    shortened = shorten_title(live)
    if not shortened or shortened == live:
        ghost += 1
        continue
    fixes.append({
        "rule_id": "title_too_long",
        "url": url,
        "detail": f"titulo com {len(live)} chars (>65) -> {len(shortened)}",
        "fix": {"type": "wp_post_meta", "post_id": int(post_id),
                "meta": {"rank_math_title": shortened}},
    })

out = ROOT / "title-shortener-fixes.json"
out.write_text(json.dumps(fixes, ensure_ascii=False, indent=2))
print(f"URLs verificadas via REST: {checked} | fixes gerados: {len(fixes)} -> {out}")
diagnostic_out = ROOT / "title-shortener-diagnostics.json"
diagnostic_out.write_text(json.dumps({
    "checked": checked,
    "rest_attempts": rest_attempts,
    "fixes": len(fixes),
    "ghosts": ghost,
    "no_post": no_post,
    "rest_errors": rest_err,
    "categories": diagnostics,
}, ensure_ascii=False, indent=2))
print(f"ghosts (rm vivo <=65 / nao encurtavel): {ghost} | sem post WP: {no_post} | "
      f"erro REST: {rest_err} | diagnostico: {diagnostic_out}")
storage.close()
