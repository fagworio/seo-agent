---
name: hermes-seo-agent
description: Run deterministic SEO audits (inventory, audit, report) for UnicornioHater; never execute approval_required actions.
version: 0.1.0
metadata:
  hermes:
    tags: [seo, wordpress, static-site, safety, deterministic]
---

# Hermes SEO Agent

Audit the UnicornioHater site (WordPress → static site → sitemap → GSC) using
the **deterministic CLI** — never reimplement checks by browsing pages with a
browser tool. The CLI does the mechanics; you interpret and report.

## Non-negotiable safety

- **`approval_required` is a review queue for humans.** Never execute, approve
  or "just fix" anything in it. Report it as-is.
- **Never delete content.** The executor rejects deletes by construction; you
  must never ask a tool to delete a post/page/URL.
- The CLI runs in `--dry-run` posture by default; writes only exist when
  `DRY_RUN=false` in `.env` (Phase 4 executor) — you do not flip that.
- Never log credentials, tokens, or full Authorization headers.

## Deterministic-first (token economy)

- **Mechanics = CLI, never LLM.** HTTP status, redirects, canonical, robots,
  title/meta length, sitemap diffs are pure code (`inventory`, `audit`,
  `report`, `diff-sitemap`). Do NOT fetch pages manually to "verify" a check —
  the CLI already did it.
- **AI is only for judgment** (Phase 3+): thin-content interpretation,
  cannibalization grouping, title/meta rewrite suggestions. Until then, run
  the deterministic cycle and report findings.

## Fluxo (economia de tokens)

1. `hermes-seo-agent inventory --json` — one call; reconciliation
   WP × static sitemap (summary: missing_from_sitemap, orphan_in_sitemap,
   wp_static_mismatch, …).
2. `hermes-seo-agent audit --json --limit N` — deterministic checks on a
   bounded sample; findings carry `rule_id`/`severity`/`detail`.
3. `hermes-seo-agent report` — persists a cycle snapshot (SQLite) and prints a
   Markdown report.
4. `hermes-seo-agent inspect --dry-run` — builds the URL Inspection queue
   (GSC tiers; real execution needs `GOOGLE_APPLICATION_CREDENTIALS` +
   `DRY_RUN=false` and consumes the daily budget).
5. `hermes-seo-agent opportunities` — low-CTR/zero-click (GSC) + Core Web
   Vitals (CrUX). Needs API keys; without them it emits warnings, not findings.
6. `hermes-seo-agent apply actions.json` — executes `safe_fix` from an intent
   file (fix types: `wp_media_alt`, `wp_post_meta`). Dry-run by default;
   NEVER write unless the pipeline approved AND `DRY_RUN=false` is explicit.
7. `hermes-seo-agent diff-sitemap URL_A URL_B` — when a sitemap changed,
   compare URL sets deterministically.
8. Before any removal/approval decision, check archive evidence:
   `hermes-seo-agent wayback URL` (never propose removing something with
   archived history without saying so).
9. `hermes-seo-agent validate-schema URL` — structured data validity
   (deterministic); `import-crawl crawl.csv` — optional deeper crawl input.
10. `hermes-seo-agent telemetry [--notify]` — observability; fires the webhook
    alert only when high+critical findings cross `ALERT_HIGH_THRESHOLD`.
11. `hermes-seo-agent post-audit [--write]` — improvement analysis: for each
    post it lists reasons + suggested manual actions + projected click gain
    (deterministic, no AI). The checklist is persisted.
12. `hermes-seo-agent checklist` — pending improvements; `checklist done <id>`
    marks an item completed (manual flow). Re-runs never duplicate items.
13. `hermes-seo-agent impact` — after improvements + Google reindexation,
    compares GSC before × after (position/clicks/CTR) per page.
14. Report **JSON outcomes** to the pipeline (status, summary, findings,
    safe_actions, approval_required). Keep `approval_required` untouched.

## Fluxo de melhorias (manual-first, verificado depois)

1. `post-audit --limit 20` → lista de posts com estimativas de ganho.
2. `checklist` → itens pendentes; execute manualmente (ex.: `set-title`,
   conteúdo) e marque `checklist done <id>`.
3. Depois que o Google reindexar (`reindex-status` mostra `last_crawl_time`),
   rode `impact` para confirmar o ganho (posição/cliques/CTR antes × depois).

## Output contract

```json
{ "status": "ok", "summary": {}, "findings": [], "safe_actions": [], "approval_required": [] }
```

## Operational pitfalls

- CLI lê env direto: `set -a && . ./.env && set +a && .venv/bin/hermes-seo-agent …`
  (install.sh + monitor já fazem isso).
- URLs: WordPress host (ex.: wordpress.dvl.to:8080) ≠ static host
  (www.unicorniohater.com.br). O `inventory` normaliza por path — não confie
  no host cru ao comparar.
- `report` grava em `SQLITE_PATH` (default `state/seo_agent.db`); se falhar,
  o audit continua (aviso em `warnings`).
- Sitemap bloqueado no robots.txt é regra `sitemap_blocked` (high) — reporte,
  não edite robots.txt sozinho.
