#!/usr/bin/env bash
# ============================================================================
# Hermes SEO Agent — install/update script
# ============================================================================
# Padrão espelhado do unicornio-agent (hermes/cron-install.sh): instalação
# IDEMPOTENTE — re-executar ATUALIZA em vez de duplicar:
#   * cria/atualiza o venv e instala o pacote
#   * copia o skill + referências para $HERMES_HOME/skills/hermes-seo-agent/
#   * instala o monitor (template @PROJECT_ROOT@ resolvido) em $HERMES_HOME/scripts/
#   * cria/edita/deduplica o job cron do Hermes (jobs.json é a fonte de verdade)
#
# Usage:
#   ./install.sh [--schedule "every 6h"] [--no-venv] [--skip-cron] [--help]
# ============================================================================

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_BIN="${HERMES_BIN:-hermes}"
SKILL_NAME="hermes-seo-agent"
JOB_NAME="Hermes SEO Agent"
SCHEDULE="${SEO_SCHEDULE:-every 6h}"
SKILL_DIR="$HERMES_HOME/skills/$SKILL_NAME"
SCRIPTS_DIR="$HERMES_HOME/scripts"
MONITOR_SCRIPT="$SCRIPTS_DIR/hermes-seo-agent-monitor.sh"
JOBS_FILE="$HERMES_HOME/cron/jobs.json"

# Prompts padrão do job cron.
PROMPT='Run the SEO audit cycle for the UnicornioHater site and report findings as JSON. Follow the hermes-seo-agent skill. Use only the deterministic CLI (inventory, audit, report, diff-sitemap): never reimplement checks by browsing pages. Never execute or alter anything in approval_required — it is a review queue for humans. Never delete content. Report JSON outcomes with status, summary, findings, safe_actions, approval_required.'

# Options
DO_VENV=true
DO_CRON=true

usage() {
  cat <<'EOF'
Hermes SEO Agent Installer

Options:
  --schedule SCHEDULE  Cron schedule (default: "every 6h")
  --no-venv            Skip Python venv + pip install
  --skip-cron          Skip Hermes cron job setup (skill + monitor still installed)
  -h, --help           Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --schedule) SCHEDULE="$2"; shift 2 ;;
    --no-venv) DO_VENV=false; shift ;;
    --skip-cron) DO_CRON=false; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 1 ;;
  esac
done

# ── helpers ────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log_info()    { echo -e "${CYAN}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn()    { echo -e "${YELLOW}⚠${NC} $1"; }
log_error()   { echo -e "${RED}✗${NC} $1"; }

# ── 1. venv + pacote ───────────────────────────────────────────────────────
pip_install() {
  # Algumas máquinas têm pip config global apontando para um mirror interno
  # sem todos os pacotes (ex.: sem setuptools). Fallback para o PyPI público.
  if ! "$ROOT/.venv/bin/pip" install --quiet -e "$ROOT[dev]" 2>/dev/null; then
    log_warn "pip install falhou com o index configurado — tentando PyPI público..."
    "$ROOT/.venv/bin/pip" install --quiet --index-url https://pypi.org/simple/ -e "$ROOT[dev]"
  fi
}

if [ "$DO_VENV" = true ]; then
  log_info "Setting up Python venv at $ROOT/.venv ..."
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install --quiet --upgrade pip 2>/dev/null || true
  pip_install
  log_success "Package installed: $("$ROOT/.venv/bin/hermes-seo-agent" --help >/dev/null 2>&1 && echo 'hermes-seo-agent OK' || echo 'entrypoint not found (check pip log)')"
else
  log_info "Skipping venv setup (--no-venv)"
fi

# ── 2. .env local ──────────────────────────────────────────────────────────
if [ ! -f "$ROOT/.env" ]; then
  log_info "Creating $ROOT/.env from .env.example (edit it with your credentials)"
  cp "$ROOT/.env.example" "$ROOT/.env"
else
  log_info ".env already exists — keeping it"
fi

# ── 3. skill ───────────────────────────────────────────────────────────────
log_info "Installing skill → $SKILL_DIR"
mkdir -p "$SKILL_DIR"
cp "$ROOT/hermes/SKILL.md" "$SKILL_DIR/SKILL.md"
if [ -d "$ROOT/hermes/references" ]; then
  cp -r "$ROOT/hermes/references" "$SKILL_DIR/"
fi
log_success "Skill installed"

# ── 4. monitor (template @PROJECT_ROOT@ resolvido) ─────────────────────────
log_info "Installing monitor → $MONITOR_SCRIPT"
mkdir -p "$SCRIPTS_DIR"
sed "s|@PROJECT_ROOT@|$ROOT|g" "$ROOT/hermes/monitor.sh" > "$MONITOR_SCRIPT"
chmod +x "$MONITOR_SCRIPT"
log_success "Monitor installed"

# ── 5. cron (idempotente: cria / edita / deduplica) ────────────────────────
if [ "$DO_CRON" = true ]; then
  if ! command -v "$HERMES_BIN" >/dev/null 2>&1; then
    log_warn "Hermes CLI ('$HERMES_BIN') not found — skipping cron setup"
    log_info "  Re-run ./install.sh after installing Hermes to register the cron job."
  else
    MONITOR_BASENAME="$(basename "$MONITOR_SCRIPT")"

    # Descobre os ids dos jobs com JOB_NAME. Fonte 1: jobs.json (fonte de
    # verdade do unicornio-agent). Fonte 2 (fallback quando o gateway não
    # persiste jobs.json, ex.: gateway parado): parse de `hermes cron list`.
    find_cron_ids() {
      local ids=""
      JOBS_JSON=$(cat "$JOBS_FILE" 2>/dev/null || echo '{"jobs":[]}')
      ids="$(OPENAI_JOBS_JSON="$JOBS_JSON" OPENAI_JOB_NAME="$JOB_NAME" python3 - <<'PYEOF'
import json, os
try:
    data = json.loads(os.environ.get("OPENAI_JOBS_JSON", "{}"))
except ValueError:
    data = {}
name = os.environ.get("OPENAI_JOB_NAME", "")
for j in (data.get("jobs") or []):
    if (j.get("name") or "") == name and j.get("id"):
        print(j["id"])
PYEOF
      )"
      if [ -z "$ids" ]; then
        ids="$("$HERMES_BIN" cron list 2>/dev/null | awk -v want="$JOB_NAME" '
          /^[[:space:]]*[0-9a-f]{12}[[:space:]]*\[/ { id=$1 }
          /Name:[[:space:]]/ {
            line=$0; sub(/^.*Name:[[:space:]]*/, "", line);
            if (line == want && id != "") { print id; id="" }
          }')"
      fi
      [ -n "$ids" ] && printf '%s\n' "$ids"
    }

    mapfile -t MATCH_IDS < <(find_cron_ids)

    if [ "${#MATCH_IDS[@]}" -eq 0 ]; then
      log_info "cron: nenhum job \"$JOB_NAME\" — criando ($SCHEDULE)..."
      "$HERMES_BIN" cron create "$SCHEDULE" "$PROMPT" \
        --name "$JOB_NAME" \
        --skill "$SKILL_NAME" \
        --workdir "$ROOT" \
        --monitor-script "$MONITOR_BASENAME"
      log_success "cron: job \"$JOB_NAME\" criado"
    else
      PRIMARY="${MATCH_IDS[0]}"
      if [ "${#MATCH_IDS[@]}" -gt 1 ]; then
        log_warn "cron: ${#MATCH_IDS[@]} jobs duplicados — removendo excedentes e mantendo $PRIMARY..."
        for dup in "${MATCH_IDS[@]:1}"; do
          log_info "cron: removendo duplicado $dup"
          "$HERMES_BIN" cron remove "$dup" || log_warn "cron: falha ao remover $dup (ignore)"
        done
      else
        log_info "cron: job \"$JOB_NAME\" já existe ($PRIMARY) — atualizando..."
      fi
      "$HERMES_BIN" cron edit "$PRIMARY" \
        --schedule "$SCHEDULE" \
        --prompt "$PROMPT" \
        --skill "$SKILL_NAME" \
        --workdir "$ROOT" \
        --monitor-script "$MONITOR_BASENAME"
      log_success "cron: job \"$JOB_NAME\" atualizado ($PRIMARY)"
    fi
  fi
else
  log_info "Skipping cron setup (--skip-cron)"
fi

echo ""
log_success "Install/update complete."
log_info "Next: edit $ROOT/.env (WordPress app password, static site URL) then run:"
log_info "  $ROOT/.venv/bin/hermes-seo-agent inventory"
