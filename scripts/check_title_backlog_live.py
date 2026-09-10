#!/usr/bin/env python3
"""Amostra espalhada: confere o rank_math_title AO VIVO (REST) de N URLs com
finding title_too_long no DB, cobrindo todo o alfabeto do backlog. Read-only.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hermes_seo_agent.checks.meta import _strip_site_name  # noqa: E402
from hermes_seo_agent.config import load_config  # noqa: E402
from hermes_seo_agent.connectors.wordpress import WordPressClient  # noqa: E402
from hermes_seo_agent.storage.db import Storage  # noqa: E402

step = int(sys.argv[sys.argv.index("--step") + 1]) if "--step" in sys.argv else 16

cfg = load_config()
st = Storage(cfg.sqlite_path)
wp = WordPressClient(cfg)

urls = [r[0] for r in st.conn.execute(
    "SELECT DISTINCT url FROM findings WHERE rule_id='title_too_long' ORDER BY url"
).fetchall()]
sample = urls[::step]
print(f"backlog: {len(urls)} URLs | amostra: {len(sample)} (passo {step})")

id_by_slug = {r[0].rstrip('/').split('/')[-1]: r[1] for r in st.conn.execute(
    "SELECT url, post_id FROM wp_post_state").fetchall()}

long_live, ok, err = [], 0, 0
for url in sample:
    slug = url.rstrip('/').split('/')[-1]
    pid = id_by_slug.get(slug)
    if not pid:
        err += 1
        continue
    try:
        post = wp.get_post(int(pid))
    except Exception:  # noqa: BLE001
        err += 1
        continue
    rm = ((post or {}).get('meta') or {}).get('rank_math_title') or ''
    rm = _strip_site_name(rm)
    if len(rm) > 65:
        long_live.append((slug, len(rm), rm[:80]))
    else:
        ok += 1
print(f"rm vivo <=65: {ok} | rm vivo >65: {len(long_live)} | erros/sem post: {err}")
for x in long_live[:25]:
    print("  LONGO", x[1], "|", x[0][:70])
st.close()
