"""Gera (e opcionalmente aplica) o ROLLBACK do titulo de uma URL que PIOROU.

Uso:
  .venv/bin/python scripts/rollback_title.py <url|post_id>            # dry-run
  .venv/bin/python scripts/rollback_title.py <url|post_id> --apply    # aplica
"""
import json
import sqlite3
import subprocess
import sys
from urllib.parse import urlparse

DB = "/www/wwwroot/hermes/seo-agent/state/seo_agent.db"
OUT = "/www/wwwroot/hermes/seo-agent/rollback-fixes.json"


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "uso: rollback_title.py <url|post_id> [--apply]"}))
        return 2
    alvo = sys.argv[1]
    aplicar = "--apply" in sys.argv
    path_alvo = urlparse(alvo).path.rstrip("/") if alvo.startswith("http") else ""
    db = sqlite3.connect(DB)
    if path_alvo:
        row = db.execute(
            "SELECT fingerprint, rule_id, url, rollback_json FROM actions "
            "WHERE status = 'executed' AND url LIKE ? AND rollback_json IS NOT NULL "
            "ORDER BY id DESC LIMIT 1", (f"%{path_alvo}%",)).fetchone()
    else:
        row = db.execute(
            "SELECT fingerprint, rule_id, url, rollback_json FROM actions "
            "WHERE status = 'executed' AND rollback_json LIKE ? "
            "ORDER BY id DESC LIMIT 1", (f'%"post_id": {alvo}%',)).fetchone()
    if not row:
        print(json.dumps({"status": "error", "error": "nenhuma acao executada com rollback para " + alvo}))
        return 1
    fp, rule, url, rb = row
    fix = json.loads(rb)
    actions = [{"rule_id": "title_rollback", "url": url,
                "detail": f"rollback de {rule} ({fp[:12]})",
                "fix": fix}]
    open(OUT, "w").write(json.dumps(actions, ensure_ascii=False, indent=2))
    print(json.dumps({"status": "ok", "url": url, "rule_revertida": rule,
                      "meta_anterior": fix.get("meta"), "arquivo": OUT},
                     ensure_ascii=False, indent=2))
    if not aplicar:
        print("DRY-RUN — rode com --apply para reverter")
        return 0
    r = subprocess.run(["/www/wwwroot/hermes/seo-agent/.venv/bin/hermes-seo-agent",
                        "apply", OUT, "--json"], capture_output=True, text=True)
    print(r.stdout[-1500:] or r.stderr[-800:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
