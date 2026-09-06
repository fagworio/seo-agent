"""Gera title-shortener-fixes.json para os findings title_too_long.

Deterministico, sem LLM: le as URLs com title_too_long do state DB, pega o
titulo atual (seo_title do corpus / title do snapshot), encurta com
shorten_title (mantem entidade, remove marca, corte em fronteira de palavra)
e monta o arquivo de acoes no formato do executor (wp_post_meta
rank_math_title com post_id resolvido via WP). O executor re-verifica por
REST apos o write (unverified = falha).

Roda: .venv/bin/python scripts/build_title_fixes.py [--limit N]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hermes_seo_agent.storage.db import Storage  # noqa: E402
from hermes_seo_agent.config import load_config  # noqa: E402
from hermes_seo_agent.connectors.wordpress import WordPressClient  # noqa: E402
from hermes_seo_agent.tools.title_opportunities import shorten_title  # noqa: E402

limit = None
if "--limit" in sys.argv:
    limit = int(sys.argv[sys.argv.index("--limit") + 1])

cfg = load_config()
storage = Storage(cfg.sqlite_path)
rows = storage.conn.execute(
    "SELECT DISTINCT url FROM findings WHERE rule_id = 'title_too_long' "
    "ORDER BY url"
).fetchall()
urls = [r[0] for r in rows]
if limit:
    urls = urls[:limit]
print(f"{len(urls)} URLs title_too_long no DB")

fixes = []
no_title = 0
skipped = 0
no_post = 0
wp = WordPressClient(cfg)
for url in urls:
    row = storage.conn.execute(
        "SELECT seo_title, title FROM corpus_documents WHERE url = ?", (url,)
    ).fetchone()
    if not row:
        row = storage.conn.execute(
            "SELECT title FROM page_snapshots WHERE url = ? "
            "ORDER BY captured_at DESC LIMIT 1", (url,)
        ).fetchone()
        current = row[0] if row else ""
    else:
        current = (row[0] or row[1] or "")
    if not current:
        no_title += 1
        continue
    shortened = shorten_title(current)
    if not shortened or shortened == current:
        skipped += 1
        continue
    post = wp.get_post_by_slug(url.rstrip("/").split("/")[-1])
    if not post:
        no_post += 1
        continue
    fixes.append({
        "rule_id": "title_too_long",
        "url": url,
        "detail": f"titulo com {len(current)} chars (>65) -> {len(shortened)}",
        "fix": {"type": "wp_post_meta", "post_id": post["id"],
                "meta": {"rank_math_title": shortened}},
    })

out = ROOT / "title-shortener-fixes.json"
out.write_text(json.dumps(fixes, ensure_ascii=False, indent=2))
print(f"fixes gerados: {len(fixes)} -> {out}")
print(f"sem titulo: {no_title} | skip: {skipped} | sem post WP: {no_post}")
storage.close()
