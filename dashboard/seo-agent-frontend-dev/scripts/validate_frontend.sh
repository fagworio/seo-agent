#!/usr/bin/env bash
set -eu

root="${1:-.}"
if [ ! -f "$root/package.json" ]; then
  echo "No package.json found at: $root" >&2
  exit 2
fi

cd "$root"

if [ -f pnpm-lock.yaml ] && command -v pnpm >/dev/null 2>&1; then
  pm="pnpm"
elif [ -f yarn.lock ] && command -v yarn >/dev/null 2>&1; then
  pm="yarn"
elif command -v npm >/dev/null 2>&1; then
  pm="npm"
else
  echo "No supported package manager available" >&2
  exit 2
fi

has_script() {
  node -e 'const p=require("./package.json"); process.exit(p.scripts && p.scripts[process.argv[1]] ? 0 : 1)' "$1"
}

run_script() {
  name="$1"
  if has_script "$name"; then
    echo "==> $name"
    if [ "$pm" = "npm" ]; then npm run "$name"; else "$pm" "$name"; fi
  else
    echo "==> skip $name (script not defined)"
  fi
}

run_script lint
run_script typecheck
run_script test
run_script build
