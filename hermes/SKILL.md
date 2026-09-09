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
14. `hermes-seo-agent ga4 status` — GA4 data contract (A0): property, window,
    rows returned, canonical/unmatched URLs, quota. No GA4_PROPERTY_ID →
    clear error, never fake zeros.
15. `hermes-seo-agent ga4 collect --store` — weekly closed-window (28d ending
    yesterday) organic landing collection (A1/A2); persists empty/partial runs
    and warns on coverage drop. `schedule` runs it weekly when configured.
16. `hermes-seo-agent ga4 report` — calibration GSC × GA4 per URL (clicks vs
    sessions). Correlated signals, NOT 1:1 — report divergence as expected.
17. `hermes-seo-agent content-brief` — adds GA4 blocks (organic_landing,
    engagement, trend, data_quality) + post-click suggestions when data exists;
    GA4 adjusts confidence with an explanation (A4).
18. `hermes-seo-agent opportunity-feed [--source X]` — unified read model (P1):
    checklist + content_briefs + backlog + interlinks + GSC + GA4 as DTOs.
19. `hermes-seo-agent checklist measure <id>` — integrated measurement (A5):
    acquisition (GSC) + engagement (GA4) + combined verdict; no causality.
20. Report **JSON outcomes** to the pipeline (status, summary, findings,
    safe_actions, approval_required). Keep `approval_required` untouched.

## Fluxo de melhorias (manual-first, verificado depois)

1. `post-audit --limit 20` → lista de posts com estimativas de ganho.
2. `checklist` → itens pendentes; execute manualmente (ex.: `set-title`,
   conteúdo) e marque `checklist done <id>`.
3. Depois que o Google reindexar (`reindex-status` mostra `last_crawl_time`),
   rode `impact` para confirmar o ganho (posição/cliques/CTR antes × depois).

## GA4 como sinal editorial (A0–A5)

- GA4 complementa GSC (comportamento pós-clique), nunca o substitui.
- Regras determinísticas (A3): organic_low_engagement, engagement_declining,
  search_click_engagement_gap — cada finding com evidência, janela, amostra,
  limiar, status do dado e limitações.
- Nunca sugira ação a partir de amostra pequena ou métrica indisponível
  (measurement_status != available ⇒ sem finding).
- low_value_page / remoção / noindex / redirect continuam decisão humana —
  nunca gatilho automático.
- Divergência GSC clicks × GA4 sessions é esperada; reporte como sinal
  correlacionado, não como bug.

## Opportunity Agent (M0–M8)

- `integration-status [--live]` — saúde de TODAS as fontes com data_status
  canônico (available|partial|missing|invalid). Uma fonte ausente NUNCA vira
  métrica zero.
- `corpus rebuild/search/coverage/stats` — memória editorial (M2): corpus
  FTS5 por documento/seção/entidade. Rebuild é incremental com checkpoint e
  expõe coverage/failures/staleness (staleness = conteúdo que MUDOU;
  unverifiable = inventory desatualizado). ANTES de decidir "new content",
  confira `corpus coverage <termo>` — "não encontrei conteúdo" só vale para
  o que foi indexado.
- Busca SEMÂNTICA leve (M7): `decide`/`brief`/`register` usam a mesma
  cobertura híbrida (FTS + expansão de consulta com aliases/sinônimos/
  perguntas + entidade + seções) — uma intenção com vocabulário diferente
  do corpo ainda encontra a seção que a cobre. Nunca invente match.
- `topics graph|coverage <tema>` — clusters por entidade (M3): posts,
  indexáveis, links, impressões, Top3/Top10, frescor, GA4.
- `market status|candidate <keyword>` — inteligência externa opcional (M4):
  Google Trends via scrape do frontend público (default, sem credencial —
  autocomplete de sugestões) ou via API alpha (`TRENDS_MODE=api`, exige
  allowlist). Candidato externo SEMPRE passa por checagem contra o corpus e
  gera sugestão de pesquisa, NUNCA pauta automática. Volume/tendência só
  quando a API alpha estiver autorizada; scrape degrada com nota explícita —
  reporte, não invente volume.
- `rankability <tema>` — perfil de autoridade por cluster (M5): score
  calibrável (não "probabilidade"), cada fator explicado.
- `decide <keyword>` — árvore de decisão editorial (M6): demanda →
  relevância → cobertura → new_content/expand/refresh/interlink/
  cannibalization_review/monitorar/descartar. CandidateScore (5 fatores) e
  ActionScore (impacto×confiança×facilidade) são SEPARADOS.
- `brief <keyword>` — brief de pesquisa estruturado (M7): URL recomendada ou
  justificativa, diferenciação, subtópicos (GSC + seções internas + tópicos
  EXTERNOS do Trends como sinal), risco de duplicação, links internos,
  critérios de aceite. Revisão humana obrigatória; LLM só para síntese.
- `outcomes register|list|measure --id N --days 28|56|90|recalibrate` — M8:
  register grava decisão+scores+baseline automático; measure exige a janela
  completa e deriva verdict de GSC+GA4; recalibrate só SUGERE ajustes (pesos
  ficam fixos até haver volume suficiente).

## Produtores da Caixa (decisões humanas) — verificado 2026-09-04

A Caixa (/work no painel) só mostra itens se os produtores rodarem. Audit
isolado NÃO alimenta a Caixa (grava só findings/JSON). Ordem verificada (tudo
somente-leitura no site; escrita só no SQLite local):

1. `refresh-data` — coleta R3 (wordpress/sitemap/gsc/ga4/crux/corpus) + R5
   reconcile; grava wp_post_state; valida GSC/GA4 (se 401 → service account
   sem acesso à propriedade).
2. `demand --store` — persiste query_pages (base de url_demand; filtro
   --min-impressions, default 10).
3. `title-opportunities --persist` — B4: candidatos de título viram actions
   pending + improvement_checklist (TAB Melhorias SEO). SEM `--persist` só
   grava title-opportunities-fixes.json e a Caixa fica vazia (gargalo real
   visto 2026-09-04: 437 opportunities/run presas).
4. `content-brief --store --limit N` — itens intent/question_gap/
   query_title_alignment/title_meta no improvement_checklist.
5. `editorial-backlog` — gera pautas (editorial_backlog, status proposed) →
   TAB Editorial da Caixa (idempotente por evidência).
6. `content_briefs` (tab "Planos de conteúdo") NÃO tem produtor ligado:
   storage.save_content_brief não tem callers — gap conhecido.

Pitfall: `title-opportunities` sem `--persist` = decisões invisíveis. Rodar
como www com cwd no repo (`.env` local). Dedupe por fingerprint/hypothesis_key:
rejeitado não volta; pendente é atualizado.

Automação (desde 2026-09-04; consolidada em `producers-cycle` no pull de
2026-09-09): cron Hermes `SEO Caixa produtores diarios` (no_agent, 06:20,
telegram) roda o corpo em `<repo>/scripts/seo-caixa-producers.sh`, que executa
`producers-cycle --json` — refresh-data (R3 completo) → demand --store →
title-opportunities --persist → content-brief --store --limit 20 →
editorial-backlog, num único processo (RunContext com cache HTTP condicional;
watchdog: stdout vazio = tick silencioso, log em `state/caixa-producers.log`).
Cron exige script em `~/.hermes/scripts/`, mas `/root` é 700 — por isso lá
mora só um wrapper que re-executa o corpo via
`exec sudo -u www bash <repo>/scripts/...`.

## Output contract

```json
{ "status": "ok", "summary": {}, "findings": [], "safe_actions": [], "approval_required": [] }
```

## Operational pitfalls

- **title_too_long conta o sufixo da marca** (desde o template estático
  dab9569, 2026-09-01): `<title>` = rank_math_title + " — UnicornioHater"
  (17–18 chars). O audit mede o `<title>` completo → QUALQUER página com rm
  > ~47 chars vira finding `title_too_long`, mesmo com rm curto. Ciclos de
  audit mostram ~420+ findings low "title_too_long" que são em grande parte
  GHOSTS. Conferir sempre o rm real (REST) antes de gerar/aplicar fix. O
  gerador estratégico e interlinks.py já fazem strip do sufixo; a checagem
  (checks/meta.py) não — candidato a fix de 1 linha (strip antes do len).
- **build_title_fixes.py usa corpus_documents.title (post_title do WP)**, que
  pode estar STALE vs rank_math_title atual → propõe o mesmo encurtamento já
  aplicado (churn) → apply pula como idempotente. Antes de aplicar em massa:
  filtrar fingerprints já executados E conferir o rm ao vivo (REST); se todos
  os pendentes já têm rm ≤65 no WP, o backlog de títulos está CONVERGIDO e o
  trabalho real vira propagação (touch) dos aplicados sem touch.
- **Campanha de títulos (improvement_campaigns) pode executar sem aprovação**
  (campaign-1 em 2026-09-05: status queued, approved_by None, gerador antigo
  pré-3ea2cea escreveu títulos-fragmento de query: 'Gojo', 'Highie' — 9 posts
  regredidos). Sempre conferir `approved_by`/`before_json` da actions table e
  o estado atual do rm ao vivo. Rollback = apply com arquivo wp_post_meta
  usando o before_json (registra e verifica via REST) + TOUCH depois (o POST
  do rollback re-renderiza com o payload velho = título ruim; ver pitfall na
  skill unicorniohater-static-site).
- Livro-caixa de títulos tem 3 camadas com status que dessincronizam:
  work_item_lifecycle é a fonte das decisões (implemented/rejected); actions
  fica stale como `pending` e improvement_campaigns.pending_items não reflete
  itens descartados (zumbi: queued/85 pendentes sem itens reais — dashboard
  mostra fila fantasma). Limpeza segura (2026-09-09): backup do DB, depois
  ImprovementCampaignService._recount(cid) + cancel(cid, actor=...) p/ campanhas
  mortas, e UPDATE actions SET status='executed'|'rejected' conforme o lifecycle
  (implemented→executed; rejected→rejected). Só rodar apply/executor sobre
  status='pending' — nunca executar proposta com lifecycle rejected. O
  `scripts/validate-production.sh` (check #5) conta duplicação de fingerprint
  apenas entre campanhas EXECUTÁVEIS (status != cancelled): itens de campanhas
  canceladas são histórico inerte (guardam before/after_json de auditoria) e
  não devem ser deletados.
- Após `git pull` no repo, o processo da API NÃO recarrega sozinho: rotas novas
  devolvem 404 até `systemctl restart seo-agent-api` (visto 2026-09-09 com
  `/dashboard/title-impact`; sintoma no journal: 404 no endpoint novo enquanto
  `/dashboard/today` segue 200). Frontend: rebuild + restart do next-server.
- CLI lê env direto: `set -a && . ./.env && set +a && .venv/bin/hermes-seo-agent …`
  (install.sh + monitor já fazem isso).
- URLs: WordPress host (ex.: wordpress.dvl.to:8080) ≠ static host
  (www.unicorniohater.com.br). O `inventory` normaliza por path — não confie
  no host cru ao comparar.
- `apply` verifies via REST re-read (unverified = failure) but does NOT
  propagate to the static www: WP REST writes meta AFTER save_post fires, so
  the WSE webhook payload carries the OLD title. After every successful
  apply, touch each affected post (no-op REST POST with the same
  rank_math_title) so the static site quick-renders the new title, then
  verify `<title>` in `_site/<slug>/index.html` (see skill
  unicorniohater-static-site; batch recipe verified 2026-09-02 for 26 posts).
- `report` grava em `SQLITE_PATH` (default `state/seo_agent.db`); se falhar,
  o audit continua (aviso em `warnings`).
- Sitemap bloqueado no robots.txt é regra `sitemap_blocked` (high) — reporte,
  não edite robots.txt sozinho.
