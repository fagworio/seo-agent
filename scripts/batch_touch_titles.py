"""Batch touch: dispara save_post nos posts corrigidos p/ o WSE re-renderizar.

O apply do seo-agent grava rank_math_title via REST, mas o WP REST atualiza
meta DEPOIS de wp_update_post -> o webhook do WSE recebe payload com o titulo
VELHO. O touch (POST no-op com o mesmo meta) dispara save_post de novo com o
meta novo ja no DB -> o <title> do www estatico propaga. ~1s entre posts
(janela de dedupe do WSE por post = 8s, posts diferentes nao colidem).
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hermes_seo_agent.config import load_config  # noqa: E402
from hermes_seo_agent.connectors.wordpress import WordPressClient  # noqa: E402

fixes_file = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "title-shortener-fixes.json"
fixes = json.loads(fixes_file.read_text())
print(f"{len(fixes)} posts para touch")

cfg = load_config()
wp = WordPressClient(cfg)
ok = fail = 0
for i, f in enumerate(fixes):
    pid = f["fix"]["post_id"]
    meta = f["fix"]["meta"]
    try:
        # No-op POST com o MESMO meta -> save_post dispara com o DB ja novo.
        wp.update_post_meta(pid, dict(meta))
        ok += 1
    except Exception as exc:  # noqa: BLE001
        fail += 1
        print(f"FALHA {pid}: {str(exc)[:100]}")
    if (i + 1) % 50 == 0:
        print(f"... {i + 1}/{len(fixes)} (ok={ok} fail={fail})")
    time.sleep(1.0)  # espaco entre writes (WSE/rate-limit)

print(f"DONE: ok={ok} fail={fail} de {len(fixes)}")
