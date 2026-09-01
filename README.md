# Hermes SEO Agent

Autonomous SEO audit module designed to be called from a Hermes Agent pipeline.

## Goals

- Reconcile WordPress published URLs against the static site sitemap and Google Search Console signals.
- Build a persistent queue for URL Inspection API usage.
- Detect broken, redirected, orphaned, non-indexed and low-value URLs.
- Detect SEO opportunities from Search Analytics.
- Apply only low-risk automated fixes; destructive actions require approval.
- Produce machine-readable JSON for Hermes and human-readable Markdown reports.
- **Deterministic-first:** mechanical/repetitive checks are plain code, never LLM (see `DESIGN.md` §8).

## Status

| Fase | Estado |
|---|---|
| Fase 0 — Fundação (venv, config, SQLite, CLI, install.sh) | ✅ implementado |
| Fase 1 — Inventory + auditoria técnica determinística | ✅ implementado |
| Fase 2 — Fila + URL Inspection (GSC) | ✅ implementado (live requer credenciais GSC) |
| Fase 3 — Oportunidades + Performance (PSI/CrUX/GA4) | ✅ implementado (live requer chaves) |
| Fase 4 — Executor seguro (safe_fix idempotente) | ✅ implementado + verificado no WP local |
| Fase 5 — Ferramentas externas + operação | ✅ implementado (Wayback, schema, wse, telemetry, Docker, alertas) |
| Fase 6 — Histórico confiável por página (before/after) | ✅ implementado (snapshot/history/trends) |

Detalhes de arquitetura, modelo de dados e roadmap: [`DESIGN.md`](DESIGN.md).

## Documentação

| Documento | Conteúdo |
|---|---|
| [`SETUP.md`](SETUP.md) | **Passo a passo das credenciais Google** (Service Account GSC, PageSpeed/CrUX API keys, GA4) com links oficiais, verificação e troubleshooting |
| [`USAGE.md`](USAGE.md) | **Guia de uso completo**: comandos, exemplos, ciclo típico, modelo de segurança e operação |
| [`DESIGN.md`](DESIGN.md) | Arquitetura, modelo de dados (SQLite), catálogo de regras, roadmap |
| [`ROADMAP_EDITORIAL.md`](ROADMAP_EDITORIAL.md) | Roadmap separado para pautas, clusters e interlinking consultivos |

## Instalação e atualização

```bash
./install.sh                      # instala OU atualiza (idempotente)
./install.sh --schedule "every 6h"  # ajusta o schedule do cron do Hermes
./install.sh --no-venv --skip-cron  # só skill + monitor
```

O `install.sh` espelha o processo do `unicornio-agent` (`hermes/cron-install.sh`):
re-executar **atualiza em vez de duplicar**:

1. Cria/atualiza o venv e instala o pacote (`pip install -e .[dev]`, com fallback
   para o PyPI público se o index configurado falhar).
2. Copia `hermes/SKILL.md` (+ `hermes/references/`) para `$HERMES_HOME/skills/hermes-seo-agent/`.
3. Instala o monitor (template `@PROJECT_ROOT@` resolvido) em `$HERMES_HOME/scripts/`.
4. Registra o job cron do Hermes **criando/Editando/deduplicando** (fonte de verdade:
   `$HERMES_HOME/cron/jobs.json`; fallback: `hermes cron list`).

## Run modes

```bash
.venv/bin/hermes-seo-agent inventory            # reconciliação WP × sitemap estático
.venv/bin/hermes-seo-agent audit --limit 500    # inventory + checks determinísticos
.venv/bin/hermes-seo-agent report --limit 500   # audit + relatório Markdown + snapshot SQLite
.venv/bin/hermes-seo-agent cycle --limit 500    # entrada recomendada para o Hermes
.venv/bin/hermes-seo-agent diff-sitemap URL_A URL_B   # diff determinístico de sitemaps
.venv/bin/hermes-seo-agent inspect --dry-run    # constrói a fila de URL Inspection (GSC)
.venv/bin/hermes-seo-agent opportunities        # low-CTR/zero-click (GSC) + Core Web Vitals
.venv/bin/hermes-seo-agent apply actions.json   # executa safe_fix (dry-run por default)
.venv/bin/hermes-seo-agent wayback URL          # evidência de arquivo (antes de remoções)
.venv/bin/hermes-seo-agent validate-schema URL  # valida JSON-LD (structured data)
.venv/bin/hermes-seo-agent import-crawl crawl.csv   # importa crawl do Screaming Frog
.venv/bin/hermes-seo-agent wse purge URL|all    # purge CDN Cloudflare via wp wse (dry-run)
.venv/bin/hermes-seo-agent telemetry --notify   # observabilidade do SQLite + alerta webhook
.venv/bin/hermes-seo-agent schedule             # watchdog: fase certa por horário
.venv/bin/hermes-seo-agent snapshot URL         # captura estado da página (histórico)
.venv/bin/hermes-seo-agent history URL          # timeline before/after da página
.venv/bin/hermes-seo-agent trends               # evolução por ciclo (site inteiro)
.venv/bin/hermes-seo-agent title-opportunities --write  # pesquisa queries -> candidatos de título
.venv/bin/hermes-seo-agent impact               # antes × depois (posição/cliques/CTR) no GSC
.venv/bin/hermes-seo-agent set-title SLUG "Novo título"   # ajusta o título SEO de um post
.venv/bin/hermes-seo-agent post-audit --write    # análise consultiva: ContentBrief + sugestões + checklist
.venv/bin/hermes-seo-agent checklist             # ver/gerenciar o checklist (pending/done)
.venv/bin/hermes-seo-agent link-graph --store    # E0: grafo de links, órfãs e hubs
.venv/bin/hermes-seo-agent demand --store        # E1: query×página, intenção, canibalização
.venv/bin/hermes-seo-agent content-brief --store # E2: diagnóstico de lacunas + ação manual
.venv/bin/hermes-seo-agent editorial-backlog --write  # E3: gera pautas editoriais revisáveis
.venv/bin/hermes-seo-agent interlinks --store    # E4: sugestões de links internos (cluster)
.venv/bin/hermes-seo-agent backlog               # E5: workflow (list/approve/reject/publish/measure)
```

## Roadmap editorial (ROADMAP_EDITORIAL.md)

Fluxo de inteligência editorial, separado do ciclo técnico — **sugestão, nunca
execução**: pautas entram em fila humana (`backlog`), evidência é obrigatória
(queries/métricas do GSC), e nada é alterado automaticamente. Fases
implementadas: E0 grafo de links, E1 base de demanda, E2 ContentBrief,
E3 backlog de pautas, E4 interlinking, E5 workflow/medição. E6 (fontes
externas) fica fora por decisão do usuário.

## Histórico confiável (before/after)

Toda página **analisada** (`audit`) e **modificada** (`apply`) tem um histórico
local persistido em `state/seo_agent.db` (tabela `page_snapshots`):

- **Estado por captura**: status, title, meta description, canonical, robots,
  h1, word count, hash do conteúdo (sha256), CWV (`cwv_json`) e sinais GSC.
- **Origem rastreável**: `source` (audit/executor/opportunities/manual) e
  `linked_action` (fingerprint da ação que causou o estado) — dá para provar
  que uma melhoria veio de uma ação do agente.
- **Diff before/after**: `history URL` mostra campo a campo o que mudou entre
  capturas (incluindo CLS/LCP melhorou ou piorou).
- **Tendências**: `trends` agrega achados por ciclo, ações executadas e
  evolução de Core Web Vitals no site inteiro.

## Ciclo de melhoria fechado (research → apply → impacto)

O agente fecha o ciclo completo de SEO mensurável:

1. **`title-opportunities`** — pesquisa as **queries reais** de cada página no
   Search Console (impressões, posição, CTR) e gera candidatos de título
   ancorados nas palavras que as pessoas realmente usam.
2. **`apply`** — aplica o `safe_fix` (dry-run primeiro) e grava o before/after
   com `linked_action` (fingerprint da ação).
3. **`impact`** — compara os dados do GSC **antes × depois** (posição média,
   cliques, impressões, CTR) e calcula quanto cada página melhorou ou piorou.
4. **`trends`** — agrega a evolução de todas as páginas alteradas.

`cycle` é o ponto de entrada recomendado para o pipeline Hermes (skill
`hermes-seo-agent` + monitor de assinatura estável acordam o agente só quando o
estado muda). `apply` executa `safe_fix` de um arquivo JSON de intenção
(`{rule_id, url, fix: {type, ...}}`; tipos: `wp_media_alt`, `wp_post_meta`).

### Análise de conteúdo consultiva

`post-audit` não altera posts. Para cada URL priorizada, ele produz um
**ContentBrief** baseado no HTML publicado e nas queries que já geraram
impressões no Search Console: cobertura da intenção no title/H1/corpo,
perguntas que merecem resposta direta, profundidade do texto principal,
estrutura de subtítulos, links internos e possível sobreposição de query entre
URLs analisadas. As sugestões entram apenas no checklist manual, com a
evidência que as motivou. Projeções de cliques são um envelope por página —
hipóteses sobrepostas não são somadas.

## Operação (Docker / cron)

```bash
docker compose up -d                    # container roda `schedule` (watchdog)
docker compose run --rm seo-agent cycle --limit 500   # uma execução única
```

Sem Docker, use o cron de exemplo (`crontab.example`) — o `schedule` decide a
fase por horário: audit+report sempre; inspect diário na janela
`--inspect-hours`; deep report semanal em `--deep-weekday`.

## Environment variables

Copie `.env.example` para `.env` e configure as credenciais:

| Variável | Uso |
|---|---|
| `WORDPRESS_URL` | `http://wordpress.dvl.to:8080` (Devilbox) ou `https://prod.unicorniohater.com.br` |
| `WORDPRESS_APP_USER` / `WORDPRESS_APP_PASSWORD` | Application Passwords (Basic auth) — mesmo padrão do `unicornio-agent` |
| `STATIC_SITE_URL` | `https://www.unicorniohater.com.br` (ou `http://localhost:8081` local) |
| `SITEMAP_URL` | `https://www.unicorniohater.com.br/sitemap_index.xml` |
| `GSC_SITE_URL` | propriedade no Search Console (default `https://www.unicorniohater.com.br/`) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Service Account JSON com acesso GSC/GA4 (`pip install 'hermes-seo-agent[google]'`) |
| `PAGESPEED_API_KEY` / `CRUX_API_KEY` | chaves de API para PageSpeed/CrUX (Fase 3) |
| `GA4_PROPERTY_ID` | ID da propriedade GA4 (Fase 3) |
| `URL_INSPECTION_DAILY_BUDGET` | orçamento diário da URL Inspection (default 1800) |
| `EDITORIAL_MEASUREMENT_MIN_DAYS` | dias mínimos após a confirmação de publicação antes de medir uma pauta (default 28) |
| `ALERT_WEBHOOK_URL` | webhook genérico (Slack/Telegram/n8n) para alertas do `telemetry --notify` |
| `ALERT_HIGH_THRESHOLD` | dispara alerta quando high+critical ≥ N (default 10) |
| `DRY_RUN` | `true` (default); write mode exige credenciais e executor (Fase 4) |
| `MAX_URLS_PER_RUN` | teto de URLs auditadas por ciclo (default 500) |

## Safety model

O agente tem três níveis de ação (`observe`, `safe_fix`, `approval_required`).
Nunca delete um post automaticamente apenas porque o Google não o indexa —
`approval_required` é uma **fila de revisão humana**, nunca de execução.
Toda mudança é idempotente, auditável e reversível; `--dry-run` é o default.

## Arquitetura

```
WordPress REST API -> Inventory (WP × sitemap estático) -> checks determinísticos
  (HTTP, redirects, canonical, robots, meta) -> Rules engine -> Action plan
  (safe_actions / approval_required) -> relatório JSON (stdout) + Markdown + SQLite
```

## Output contract para Hermes

Cada comando escreve JSON no stdout:

```json
{
  "status": "ok",
  "summary": {},
  "findings": [],
  "safe_actions": [],
  "approval_required": []
}
```

Hermes deve usar `approval_required` como fila de revisão, não como fila de execução.

## Recommended schedule

- Every 6 hours: inventory + HTTP health audit (job cron `Hermes SEO Agent`).
- Daily: Search Analytics + URL Inspection queue (Fase 2).
- Weekly: deep cleanup/cannibalization report (Fase 3).
