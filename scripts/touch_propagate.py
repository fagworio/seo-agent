"""Touch de propagacao pos-apply (batch janela 10): POST no-op com o mesmo
rank_math_title para o WSE quick-render o titulo ja encurtado no WP.

Verifica: mtime + <title> em _site/<slug>/index.html apos o POST.
Uso (como www, com .env carregado): .venv/bin/python scripts/touch_propagate.py
"""
import json, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hermes_seo_agent.config import load_config
from hermes_seo_agent.connectors.wordpress import WordPressClient

SITE_ROOT = Path("/www/wwwroot/unicorniohater.com.br/_site")
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 10

cands = json.load(open("/tmp/touch_candidates.json"))
# piores primeiro: <title> estatico mais longo (maior dano visivel)
cands.sort(key=lambda c: -len(c.get("st", "")))
cands = cands[:LIMIT]
print(f"touch em {len(cands)} posts (janela {LIMIT})")

cfg = load_config()
wp = WordPressClient(cfg)

def slug_of(url: str) -> str:
    return url.rstrip("/").split("/")[-1]

def local_title(url: str):
    idx = SITE_ROOT / slug_of(url) / "index.html"
    if not idx.exists():
        return None, None
    txt = idx.read_text(errors="ignore")
    m = re.search(r"<title>(.*?)</title>", txt, re.S)
    return idx, (m.group(1).strip() if m else "")

results = []
for c in cands:
    pid, url, rm = c["post_id"], c["url"], c["rm"]
    st_before = c.get("st", "")
    idx, _ = local_title(url)
    mtime_before = idx.stat().st_mtime if idx and idx.exists() else None
    # TOUCH: POST com o MESMO valor (no-op de conteudo, save_post dispara)
    try:
        wp.update_post_meta(pid, {"rank_math_title": rm})
    except Exception as e:
        results.append({"url": url, "post_id": pid, "touch": f"ERRO {e}"})
        print(f"ERRO touch {pid}: {e}")
        continue
    # espera quick-render (~6s) + folga p/ dedupe WSE
    time.sleep(9)
    idx, st_after = local_title(url)
    mtime_after = idx.stat().st_mtime if idx and idx.exists() else None
    changed = (mtime_after != mtime_before) and st_after != st_before
    results.append({
        "url": url, "post_id": pid, "rm": rm,
        "st_before": st_before, "st_after": st_after,
        "mtime_changed": mtime_after != mtime_before,
        "ok": changed,
    })
    print(f"id={pid} ok={changed} | {st_before[:50]} -> {st_after[:50]}")

json.dump(results, open("/tmp/touch_results.json", "w"), ensure_ascii=False, indent=1)
print("\nexecutados:", sum(1 for r in results if r.get("ok")),
      "| sem mudanca:", sum(1 for r in results if not r.get("ok")))
