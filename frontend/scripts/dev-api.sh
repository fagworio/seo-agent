#!/usr/bin/env bash
# `npm run dev:api` — sobe apenas o backend tipado (FastAPI).
# Porta: usa $BACKEND_PORT se definida; senão escolhe a primeira LIVRE em 8000..8010.
# Use o .venv (tem uvicorn); sem ele o `serve` cai no servidor stdlib legado.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_BIN="$ROOT_DIR/.venv/bin/hermes-seo-agent"

port_free() {
  if (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; then
    exec 3>&- 3<&- 2>/dev/null
    return 1   # ocupada
  fi
  return 0     # livre
}

if [ ! -x "$BACKEND_BIN" ]; then
  echo "✗ binário do backend não encontrado: $BACKEND_BIN" >&2
  echo "  Crie o ambiente e instale:  python -m venv .venv && .venv/bin/pip install -e ." >&2
  exit 1
fi

if [ -n "${BACKEND_PORT:-}" ]; then
  :   # usa a porta informada pelo usuário
else
  BACKEND_PORT=""
  for p in 8000 8001 8002 8003 8004 8005 8006 8007 8008 8009 8010; do
    if port_free "$p"; then BACKEND_PORT="$p"; break; fi
  done
  if [ -z "$BACKEND_PORT" ]; then
    echo "✗ nenhuma porta livre em 8000-8010. Libere uma porta ou use BACKEND_PORT=<porta>." >&2
    exit 1
  fi
fi

echo "▶ backend  : hermes-seo-agent serve → http://127.0.0.1:$BACKEND_PORT"
cd "$ROOT_DIR"
"$BACKEND_BIN" serve --host 127.0.0.1 --port "$BACKEND_PORT"
