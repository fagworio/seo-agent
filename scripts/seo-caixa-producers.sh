#!/usr/bin/env bash
# Produtores diários da Caixa de trabalho (decisões humanas) — zero tokens.
# Roda, em ordem: refresh-data (R3+R5) -> E1 demand -> B4 title-opportunities
# --persist -> E2 content-brief -> E3 editorial-backlog.
# Determinístico e idempotente (dedupe por fingerprint/hypothesis_key).
# Padrão watchdog: stdout vazio quando nada mudou (tick silencioso);
# mensagem só quando há itens novos ou erro de etapa.
set -uo pipefail

# Garante ownership www (sqlite + logs) re-executando como www
if [ "$(id -un)" != "www" ]; then
  exec sudo -u www bash "$0" "$@"
fi

REPO=/www/wwwroot/hermes/seo-agent
BIN="$REPO/.venv/bin/hermes-seo-agent"
LOG="$REPO/state/caixa-producers.log"
cd "$REPO" || exit 1

# evita sobreposição caso o tick atrase
exec 9>"$REPO/state/caixa-producers.lock"
flock -n 9 || exit 0

stamp() { date '+%Y-%m-%d %H:%M:%S'; }

counts() {
  "$REPO/.venv/bin/python" - "$1" <<'PY'
import sqlite3, sys
con = sqlite3.connect('/www/wwwroot/hermes/seo-agent/state/seo_agent.db')
q = {
  'checklist': "SELECT COUNT(*) FROM improvement_checklist WHERE status='pending'",
  'backlog':   "SELECT COUNT(*) FROM editorial_backlog WHERE status='proposed'",
  'briefs':    "SELECT COUNT(*) FROM content_briefs WHERE status='proposed'",
}
try:
    print(con.execute(q[sys.argv[1]]).fetchone()[0])
except Exception:
    print(0)
PY
}

run_stage() { # run_stage NOME cmd [args...]
  local name=$1; shift
  if "$@" >>"$LOG" 2>&1; then
    echo "[$(stamp)] ok: $name" >>"$LOG"
  else
    local rc=$?
    echo "[$(stamp)] ERRO em $name (exit $rc)" >>"$LOG"
    echo "ERRO no produtor '$name' — detalhes em $LOG"
  fi
}

before_check=$(counts checklist); before_backlog=$(counts backlog); before_briefs=$(counts briefs)
echo "[$(stamp)] inicio (checklist=$before_check backlog=$before_backlog briefs=$before_briefs)" >>"$LOG"

run_stage refresh-data "$BIN" refresh-data --json >/dev/null
run_stage demand "$BIN" demand --store --json >/dev/null
run_stage reconcile-work-items "$BIN" reconcile-work-items --apply --json >/dev/null
run_stage title-opportunities "$BIN" title-opportunities --persist --json >/dev/null
run_stage content-brief "$BIN" content-brief --store --limit 20 --json >/dev/null
run_stage editorial-backlog "$BIN" editorial-backlog --json >/dev/null

after_check=$(counts checklist); after_backlog=$(counts backlog); after_briefs=$(counts briefs)
echo "[$(stamp)] fim (checklist=$after_check backlog=$after_backlog briefs=$after_briefs)" >>"$LOG"

dc=$((after_check - before_check)); db=$((after_backlog - before_backlog)); df=$((after_briefs - before_briefs))
if [ "$dc" -gt 0 ] || [ "$db" -gt 0 ] || [ "$df" -gt 0 ]; then
  echo "Caixa atualizada (produtores diários): +$dc melhorias SEO (checklist), +$db pautas editoriais, +$df planos de conteúdo."
fi
# deltas 0 e sem erros => stdout vazio => tick silencioso
