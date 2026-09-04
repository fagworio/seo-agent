#!/usr/bin/env bash
# `npm run dev:api` — sobe apenas o backend tipado (FastAPI) na porta $BACKEND_PORT.
# Use o .venv (tem uvicorn); sem ele o `serve` cai no servidor stdlib legado.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
BACKEND_BIN="$ROOT_DIR/.venv/bin/hermes-seo-agent"

if [ ! -x "$BACKEND_BIN" ]; then
  echo "✗ binário do backend não encontrado: $BACKEND_BIN" >&2
  echo "  Crie o ambiente e instale:  python -m venv .venv && .venv/bin/pip install -e ." >&2
  exit 1
fi

echo "▶ backend  : hermes-seo-agent serve → http://127.0.0.1:$BACKEND_PORT"
cd "$ROOT_DIR"
"$BACKEND_BIN" serve --host 127.0.0.1 --port "$BACKEND_PORT"
