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

exec "$ROOT/.venv/bin/python" "$ROOT/hermes/monitor_sqlite.py"
