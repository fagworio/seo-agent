"""Diagnóstico read-only: separa o bucket "erro REST" do build_title_fixes.py
em (a) rank_math_title vazio (dívida editorial, não encurtável) e
(b) exceção real de REST. Espelha a mesma ordem/limite do gerador.
Não escreve nada (nem o JSON de fixes).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hermes_seo_agent.config import load_config  # noqa: E402
from hermes_seo_agent.connectors.wordpress import WordPressClient  # noqa: E402
from hermes_seo_agent.storage.db import Storage  # noqa: E402

limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 200

cfg = load_config()
storage = Storage(cfg.sqlite_path)
rows = storage.conn.execute(
    "SELECT url, MAX(created_at) mx FROM findings WHERE rule_id = 'title_too_long' "
    "GROUP BY url ORDER BY mx DESC"
).fetchall()
urls = [r[0] for r in rows]
id_by_slug = {u.rstrip("/").split("/")[-1]: pid for u, pid in storage.conn.execute(
    "SELECT url, post_id FROM wp_post_state").fetchall()}

wp = WordPressClient(cfg)
checked = 0
empty = []
errors = []
ghosts = []
fixable = []
for url in urls:
    if checked >= limit:
        break
    slug = url.rstrip("/").split("/")[-1]
    post_id = id_by_slug.get(slug)
    if not post_id:
        continue
    checked += 1
    try:
        post = wp.get_post(int(post_id))
    except Exception as exc:  # noqa: BLE001
        errors.append({"slug": slug, "post_id": int(post_id), "err": f"{type(exc).__name__}: {exc}"[:160]})
        continue
    live = (((post or {}).get("meta") or {}).get("rank_math_title") or "").strip()
    if not live:
        title = ((post or {}).get("title") or {}).get("rendered", "")
        empty.append({"slug": slug, "post_id": int(post_id), "post_title_len": len(title)})
        continue
    if len(live) <= 65:
        ghosts.append({"slug": slug, "post_id": int(post_id), "rm_len": len(live)})
        continue
    fixable.append({"slug": slug, "post_id": int(post_id), "rm_len": len(live)})

print(json.dumps({
    "checked": checked, "total_urls": len(urls),
    "empty_rank_math_title": len(empty), "rest_exceptions": len(errors),
    "ghosts_le65": len(ghosts), "fixable_gt65": len(fixable),
    "empty_detail": empty, "exception_detail": errors,
}, ensure_ascii=False, indent=1))
storage.close()
