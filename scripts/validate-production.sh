#!/usr/bin/env bash
# Valida a PERSISTÊNCIA (critérios de aceite do runbook) — read-only e rápido.
# Checagens SQL diretas (sem load pesado). As ANÁLISES (V2/calibração) são
# verificadas pelos testes (pytest/e2e) e pelo CLI `rankability-v2`/`calibrate`.
# Saída: 0 (OK) ou 1 (FALHA).
set -uo pipefail

cd "$(dirname "$0")/.."
DB="${SQLITE_PATH:-./state/seo_agent.db}"
PY="${PYTHON_BIN:-.venv/bin/python}"

if [ ! -f "$DB" ]; then
  echo "✗ banco não encontrado: $DB (configure SQLITE_PATH)" >&2
  exit 1
fi

"$PY" - "$DB" <<'PYEOF'
import sys, sqlite3
db = sys.argv[1]
try:
    conn = sqlite3.connect(db)
except Exception as e:
    print(f"✗ não conseguiu abrir o banco: {e}"); sys.exit(1)

ok = True
def check(name, got, want=0):
    global ok
    ok = ok and (got == want)
    print(f"{'✓' if got == want else '✗'} {name}: {got} (esperado {want})")

q = lambda sql: conn.execute(sql).fetchone()[0]

# 1) ações executadas sem outcome em Melhorias (perda de visibilidade) -> 0
exe_urls = [r[0] for r in conn.execute(
    "SELECT DISTINCT url FROM actions WHERE level='safe_fix' AND status='executed' AND url IS NOT NULL")]
orphans = sum(1 for u in exe_urls if not conn.execute(
    "SELECT 1 FROM opportunity_outcomes WHERE url=? AND human_decision='approved' LIMIT 1",
    (u,)).fetchone())
check("ações executadas órfãs (sem outcome)", orphans)

# 2) campanha items com work_item_id sem lifecycle -> 0
check("campanha-items sem lifecycle", q(
    "SELECT COUNT(*) FROM improvement_campaign_items ci WHERE ci.work_item_id IS NOT NULL "
    "AND NOT EXISTS (SELECT 1 FROM work_item_lifecycle l WHERE l.work_item_id=ci.work_item_id)"))

# 3) outcomes com work_item_id sem lifecycle -> 0
check("outcomes sem lifecycle", q(
    "SELECT COUNT(*) FROM opportunity_outcomes o WHERE o.work_item_id IS NOT NULL "
    "AND NOT EXISTS (SELECT 1 FROM work_item_lifecycle l WHERE l.work_item_id=o.work_item_id)"))

# 4) lifecycle implementado/medido mas ação ainda 'pending' (inconsistência) -> 0
check("lifecycle implementado/medido com ação pendente", q(
    "SELECT COUNT(*) FROM work_item_lifecycle l "
    "WHERE l.canonical_status IN ('implemented','measured') AND l.action_fingerprint IS NOT NULL "
    "AND EXISTS (SELECT 1 FROM actions a WHERE a.fingerprint=l.action_fingerprint AND a.status='pending')"))

# 5) mesmo fingerprint em mais de 1 campanha (duplicação) -> 0
check("fingerprint repetido em campanhas", q(
    "SELECT COUNT(*) FROM (SELECT action_fingerprint FROM improvement_campaign_items "
    "GROUP BY action_fingerprint HAVING COUNT(*)>1)"))

# 6) tabelas essenciais acessíveis (health leve)
for t in ("improvement_checklist","opportunity_outcomes","work_item_lifecycle","corpus_documents"):
    try:
        conn.execute(f"SELECT 1 FROM {t} LIMIT 1")
    except Exception:
        check(f"tabela acessível: {t}", 1)

conn.close()
print("RESULTADO:", "OK" if ok else "FALHA")
sys.exit(0 if ok else 1)
PYEOF
