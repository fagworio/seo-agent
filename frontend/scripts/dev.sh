#!/usr/bin/env bash
# `npm run dev` — sobe o control plane inteiro (backend tipado + frontend).
#
# Backend :  .venv/bin/hermes-seo-agent serve  (FastAPI tipado)
# Frontend : next dev                          (API_URL casada com a porta do backend)
#
# Porta: usa $BACKEND_PORT se definida; senão escolhe a primeira LIVRE em
# 8000..8010. Isso evita conflito com um backend legado antigo em :8000.
# Obs.: use o .venv (tem uvicorn). Sem ele o `serve` cai no servidor stdlib
# legado, que não expõe /account, /users, /roles, /settings.
# SESSION_COOKIE_SECURE=false: dev roda em HTTP; cookie __Host- (Secure) não
# trafega por HTTP e quebraria o login. Com false, o cookie vira `seo_session`.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT_DIR="$(cd "$FRONTEND_DIR/.." && pwd)"
BACKEND_BIN="$ROOT_DIR/.venv/bin/hermes-seo-agent"
export SESSION_COOKIE_SECURE="${SESSION_COOKIE_SECURE:-false}"

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

# Se um dos dois encerrar (ex.: backend não conseguir subir), derruba o outro.
wait -n
kill 0 2>/dev/null || true
