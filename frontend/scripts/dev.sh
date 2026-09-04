#!/usr/bin/env bash
# `npm run dev` — sobe o control plane inteiro (backend tipado + frontend).
#
# Backend :  .venv/bin/hermes-seo-agent serve  (FastAPI tipado, porta $BACKEND_PORT)
# Frontend : next dev                          (porta 3000, API_URL casada com o backend)
#
# A porta do backend pode ser sobrescrita:
#   BACKEND_PORT=8001 npm run dev
# Obs.: use o .venv (tem uvicorn). Sem ele o `serve` cai no servidor stdlib
# legado, que não expõe /account, /users, /roles, /settings.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT_DIR="$(cd "$FRONTEND_DIR/.." && pwd)"

BACKEND_PORT="${BACKEND_PORT:-8000}"
BACKEND_BIN="$ROOT_DIR/.venv/bin/hermes-seo-agent"

if [ ! -x "$BACKEND_BIN" ]; then
  echo "✗ binário do backend não encontrado: $BACKEND_BIN" >&2
  echo "  Crie o ambiente e instale:  python -m venv .venv && .venv/bin/pip install -e ." >&2
  exit 1
fi

cleanup() { kill 0 2>/dev/null || true; }
trap 'exit 130' INT
trap cleanup EXIT

echo "▶ backend  : hermes-seo-agent serve → http://127.0.0.1:$BACKEND_PORT"
(cd "$ROOT_DIR" && "$BACKEND_BIN" serve --host 127.0.0.1 --port "$BACKEND_PORT") &
BACKEND_PID=$!

echo "▶ frontend : next dev → http://localhost:3000 (API_URL=http://127.0.0.1:$BACKEND_PORT)"
cd "$FRONTEND_DIR"
API_URL="http://127.0.0.1:$BACKEND_PORT" npx next dev &
FRONTEND_PID=$!

# Se um dos dois encerrar (ex.: backend não conseguir subir na porta), derruba o outro.
wait -n
kill 0 2>/dev/null || true
