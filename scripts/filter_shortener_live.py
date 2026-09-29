#!/usr/bin/env python3
"""Filtra title-shortener-fixes.json para acoes realmente pendentes.

Deterministico e READ-ONLY no WP:
  1. Marca como 'done' acoes cujo fingerprint (mesmo do executor) ja esta
     executado na tabela actions (idempotente).
  2. Para as nao executadas, confere o rank_math_title AO VIVO via REST;
     mantem apenas as que ainda tem titulo vivo > 65 chars (genuinamente
     longas) e cujo valor proposto difere do vivo.
  3. Escreve title-shortener-fixes.live.json com as pendentes reais (na
     ordem original), limitando a N REST calls (padrao 40).

Roda: .venv/bin/python scripts/filter_shortener_live.py [--max-calls N]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hermes_seo_agent.config import load_config
from hermes_seo_agent.storage.db import Storage
from hermes_seo_agent.connectors.wordpress import WordPressClient
from hermes_seo_agent.executor.executor import _fingerprint

max_calls = 40
if "--max-calls" in sys.argv:
    max_calls = int(sys.argv[sys.argv.index("--max-calls") + 1])

cfg = load_config()
storage = Storage(cfg.sqlite_path)
wp = WordPressClient(cfg)

fixes = json.loads((ROOT / "title-shortener-fixes.json").read_text())
print(f"total fixes: {len(fixes)}")

done, pending = [], []
for a in fixes:
    fp = _fingerprint(a.get("rule_id", ""), a.get("url", ""),
                      a.get("detail", ""), a.get("fix") or {})
    if storage.action_executed(fp):
        done.append(a)
    else:
        pending.append(a)
print(f"ja executadas: {len(done)} | nao executadas: {len(pending)}")

live_long, skipped = [], []
calls = 0
for a in pending:
    if calls >= max_calls:
        skipped.append({**a, "reason": "nao verificado (limite de REST calls)"})
        continue
    calls += 1
    post_id = (a.get("fix") or {}).get("post_id")
    if not post_id:
        skipped.append({**a, "reason": "sem post_id"})
        continue
    try:
        post = wp.get_post(int(post_id))
    except Exception as exc:  # rede/404: nao arrisca write cego
        skipped.append({**a, "reason": f"REST falhou: {exc}"})
        continue
    meta = (post or {}).get("meta") or {}
    live_rm = meta.get("rank_math_title") or ""
    if not live_rm:
        skipped.append({**a, "reason": "sem rank_math_title vivo"})
        continue
    if len(live_rm) <= 65:
        skipped.append({**a, "reason": f"rm vivo ja ok ({len(live_rm)} chars)"})
        continue
    proposal = (a.get("fix") or {}).get("meta", {}).get("rank_math_title", "")
    if proposal == live_rm:
        skipped.append({**a, "reason": "rm vivo ja igual ao proposto"})
        continue
    live_long.append(a)

print(f"pendentes reais (rm vivo > 65): {len(live_long)}")
print(f"skipped: {len(skipped)}")
for s in skipped[:8]:
    print("   skip:", s.get("url", "").rsplit("/", 2)[-2], "|", s.get("reason"))

out = ROOT / "title-shortener-fixes.live.json"
out.write_text(json.dumps(live_long, ensure_ascii=False, indent=2))
print(f"escrito: {out} ({len(live_long)} acoes)")
storage.close()
