#!/usr/bin/env bash
# Monitor do cron SEO (hermes-seo-agent).
#
# Saída consumida pelo `--monitor-script` do Hermes cron: o Hermes hasheia a
# saída exata; enquanto ela não muda, o agente LLM NÃO é acordado (idle custa
# zero tokens).
#
# O monitor devolve exclusivamente a assinatura ESTÁVEL do estado: hash do
# summary do inventory. O Hermes acorda o agente quando essa assinatura muda
# (post novo, URL nova, divergência nova). Nunca inclua hora/tick aqui: isso
# acordaria o LLM a cada polling mesmo sem progresso. Sem trabalho ou com
# erro, a saída é "0"/"ERROR" — estáveis, sem spam.
#
# Este arquivo é um TEMPLATE: o install.sh substitui @PROJECT_ROOT@ pelo
# caminho real do projeto ao copiar para $HERMES_HOME/scripts/.
set -euo pipefail
ROOT="@PROJECT_ROOT@"
cd "$ROOT"
set -a
# shellcheck disable=SC1091
source ./.env 2>/dev/null || true
set +a

out="$("$ROOT/.venv/bin/python" -m hermes_seo_agent.cli inventory --json 2>/dev/null)" || out="ERROR"
if [ "$out" = "ERROR" ]; then
  printf '%s\n' "ERROR"
  exit 0
fi
sig="$(printf '%s' "$out" | "$ROOT/.venv/bin/python" -c 'import sys,json,hashlib; d=json.load(sys.stdin); s=d.get("summary",{}); print(hashlib.sha256(json.dumps(s,sort_keys=True).encode()).hexdigest()[:24])' 2>/dev/null)" || sig="ERROR"
printf '%s\n' "${sig:-0}"
