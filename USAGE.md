# USAGE — Como usar o Hermes SEO Agent

Guia prático de operação: instalação, comandos, workflows e modelo de
segurança. Configuração de credenciais Google em [`SETUP.md`](SETUP.md).

---

## 1. Instalação e atualização

```bash
./install.sh                          # instala OU atualiza (idempotente)
./install.sh --schedule "every 6h"    # ajusta o cron do Hermes
./install.sh --no-venv --skip-cron    # só skill + monitor, sem cron
```

O `install.sh` (padrão `unicornio-agent`):
1. cria/atualiza o venv e instala o pacote;
2. copia o skill para `$HERMES_HOME/skills/hermes-seo-agent/`;
3. instala o monitor (`$HERMES_HOME/scripts/hermes-seo-agent-monitor.sh`);
4. cria/edita/deduplica o job cron do Hermes.

Depois: `cp .env.example .env` e preencha as credenciais
(WordPress + Google — ver `SETUP.md`).

---

## 2. Comandos

Todos emitem **JSON no stdout** com o contrato:

```json
{ "status": "ok", "summary": {}, "findings": [], "safe_actions": [], "approval_required": [] }
```

| Comando | O que faz | Precisa de Google? |
|---|---|---|
| `inventory` | Reconcilia WordPress × sitemap estático (3 vias, por path) | não |
| `audit --limit N` | Inventory + checks determinísticos (HTTP, redirects, canonical, robots, meta) | não |
| `report` | Audit + relatório Markdown + snapshot SQLite | não |
| `cycle` | inventory + audit + report (entrada do Hermes) | não |
| `inspect` | Constrói/drena a fila de URL Inspection (6 tiers de prioridade) | **sim** (GSC) |
| `opportunities` | Low-CTR/zero-click (GSC) + Core Web Vitals (CrUX/PSI) | **sim** (GSC/CrUX) |
| `apply <file.json>` | Executa `safe_fix` de um arquivo de intenção | não (escreve no WP) |
| `wayback URL` | Evidência de arquivo (snapshots) antes de remoções | não |
| `validate-schema URL` | Valida JSON-LD (structured data) | não |
| `import-crawl crawl.csv` | Importa crawl do Screaming Frog | não |
| `wse purge/rebuild/status` | Aciona `wp wse` (CDN purge, rebuild) via wp-cli | não |
| `telemetry [--notify]` | Observabilidade do SQLite + alerta webhook | não |
| `schedule` | Watchdog: fase certa por horário | não |
| `snapshot URL` / `history URL` / `trends` | Histórico por página + evolução por ciclo | não |
| `title-opportunities [--write]` | Pesquisa queries reais (GSC) → candidatos de título | **sim** (GSC) |
| `impact [--days N]` | Antes × depois (posição/cliques/CTR) no GSC | **sim** (GSC) |
| `post-audit [--write]` | Análise de melhorias: sugestões + ganhos + checklist | **sim** (GSC) |
| `checklist [done ID]` | Ver/gerenciar o checklist de melhorias (manual) | não |
| `diff-sitemap URL_A URL_B` | Diff determinístico entre dois sitemaps | não |

### Exemplos

```bash
# Reconciliação: posts publicados fora do sitemap estático
.venv/bin/hermes-seo-agent inventory | jq '.summary'

# Auditoria de 200 URLs
.venv/bin/hermes-seo-agent audit --limit 200

# Relatório Markdown (persiste ciclo no SQLite)
.venv/bin/hermes-seo-agent report --limit 200

# Diff entre sitemap local e de produção
.venv/bin/hermes-seo-agent diff-sitemap \
  http://localhost:8081/sitemap_index.xml \
  https://www.unicorniohater.com.br/sitemap_index.xml

# Evidência de arquivo antes de pensar em remover uma URL
.venv/bin/hermes-seo-agent wayback "https://www.unicorniohater.com.br/alguma-url/"

# Validar structured data de uma página
.venv/bin/hermes-seo-agent validate-schema "https://www.unicorniohater.com.br/post/"

# Fila de URL Inspection (dry-run = sem consumir orçamento)
.venv/bin/hermes-seo-agent inspect --dry-run

# Consumir orçamento de verdade (máx. 1.800/dia)
DRY_RUN=false .venv/bin/hermes-seo-agent inspect --budget 100

# Oportunidades (CTR baixo + CWV)
.venv/bin/hermes-seo-agent opportunities

# Telemetria + alerta webhook se threshold passar
.venv/bin/hermes-seo-agent telemetry --notify
```

---

## 3. Ciclo completo típico

```bash
# 1. Estado do mundo
.venv/bin/hermes-seo-agent inventory
# 2. Problemas técnicos determinísticos
.venv/bin/hermes-seo-agent audit --limit 500
# 3. Persistir + relatório legível
.venv/bin/hermes-seo-agent report --limit 500
# 4. (com GSC) quais URLs o Google não indexa / oportunidades
.venv/bin/hermes-seo-agent inspect --budget 500
.venv/bin/hermes-seo-agent opportunities
# 5. Telemetria para o operador
.venv/bin/hermes-seo-agent telemetry
```

No pipeline Hermes, `cycle` (ou `schedule`) faz isso por você e o monitor só
acorda o LLM quando o estado muda.

---

## 4. Modelo de segurança (leia antes de escrever)

Níveis de ação por regra:

| Nível | O que acontece | Exemplos |
|---|---|---|
| `observe` | Apenas reportado | `cwv_lcp_poor`, `low_ctr_opportunity` |
| `safe_fix` | Executável pelo `apply` | `image_no_alt` (com fix spec) |
| `approval_required` | **Fila de revisão humana — nunca auto-executa** | `redirect_loop`, `title_too_long`, `canonical_conflict` |

Invariantes de código:
- **Delete é bloqueado por construção** — não existe fix type de delete.
- **Dry-run é o default**: `DRY_RUN=true` → `apply` só faz preview.
- **Idempotência**: mesma ação não re-executa (fingerprint no SQLite).
- **Audit trail + rollback**: toda execução grava before/after/rollback.
- **Blast radius**: máx. `MAX_SAFE_FIX_PER_CYCLE` (10) ações por ciclo.

### Executando um `safe_fix` (ex.: alt de imagem)

O executor **nunca adivinha** — a intenção vem de um arquivo JSON:

```json
[
  {
    "rule_id": "image_no_alt",
    "url": "https://www.unicorniohater.com.br/wp-content/uploads/.../img.webp",
    "detail": "media sem alt",
    "fix": { "type": "wp_media_alt", "media_id": 97788, "alt_text": "Descrição da imagem" }
  }
]
```

```bash
.venv/bin/hermes-seo-agent apply fix.json          # dry-run: preview
DRY_RUN=false .venv/bin/hermes-seo-agent apply fix.json   # executa de verdade
```

Tipos de fix suportados: `wp_media_alt` e `wp_post_meta` (meta Rank Math).
`approval_required` **nunca** é executado pelo agente — é a sua fila de revisão.

> ⚠️ **Pré-requisito para `wp_post_meta` (Rank Math)**: o WordPress **não expõe
> os campos `rank_math_*` à REST API** por padrão — a escrita seria descartada
> silenciosamente. Instale o mu-plugin [`wp/mu-plugins/hermes-seo-agent-rankmath-rest.php`](wp/mu-plugins/hermes-seo-agent-rankmath-rest.php)
> em `wp-content/mu-plugins/` (uma vez só). Sem isso, o `apply` de título/meta
> "executa" mas não persiste.

---

## 5. Histórico confiável por página (before/after)

O agente mantém **histórico local por URL** em `state/seo_agent.db`
(tabela `page_snapshots`). Toda página analisada (`audit`), modificada
(`apply`) ou com CWV coletado (`opportunities`) ganha uma captura com o
estado SEO completo + hash do conteúdo + origem rastreável.

```bash
# Captura manual do estado atual de uma página
.venv/bin/hermes-seo-agent snapshot "https://www.unicorniohater.com.br/post/"

# Timeline com diffs before→after (campo a campo, CWV, GSC)
.venv/bin/hermes-seo-agent history "https://www.unicorniohater.com.br/post/"

# Evolução do site inteiro por ciclo (achados, ações, CWV melhorou/piorou)
.venv/bin/hermes-seo-agent trends
```

**Como provar que uma melhoria veio do agente**: o `apply` grava a ação
(fingerprint + before/after/rollback) e **re-captura a página pós-fix** com
`source=executor` e `linked_action=<fingerprint>`. O `history` mostra então a
mudança (ex.: CLS 0.31 → 0.15) vinculada àquela ação específica. É o ciclo
"fiz → capturei → acompanho → verifico" para evoluções futuras de SEO.

---

## 6. Fluxo manual de melhorias (post-audit + checklist)

O `post-audit` gera automaticamente (sem IA) uma análise por post baseada em
**métricas reais** (GSC: posição, impressões, cliques, CTR, tráfego perdido) e
**sinais de conteúdo** (word count, idade, thin content), com sugestões e o
**ganho projetado** de cada melhoria:

```bash
# Gera a análise + salva o checklist + escreve reports/content-improvements.md
.venv/bin/hermes-seo-agent post-audit --limit 20 --write

# Ver o que falta fazer (manual primeiro)
.venv/bin/hermes-seo-agent checklist

# Ao concluir uma melhoria, marque como feita
.venv/bin/hermes-seo-agent checklist done <id>
```

Cada item do checklist tem: **motivo** (dado), **ação** (sugestão manual),
**ganho estimado em cliques/mês** (benchmark CTR × impressões) e **score
explicável** (impacto × confiança × facilidade). O **score é persistido** na
fila — `checklist` lista os pendentes **ordenados por score desc**, e
re-executar `content-brief`/`post-audit` **atualiza** o score/evidência dos
itens pendentes (sem duplicar). Para itens históricos sem score:

```bash
# Backfill determinístico (usa demand + inventário persistidos; sem re-crawl)
.venv/bin/hermes-seo-agent checklist rescore
# Refresca também os que já têm score:
.venv/bin/hermes-seo-agent checklist rescore --all
```

Exemplo real:

```
☐ [title_meta] CTR 0.0% para 5.290 impressões → Reescrever título + meta (ganho +106)
   score 0.8 = impacto 1.0 × confiança 0.8 × facilidade 1.0
```

### Workflow fechado (estados + supressão por rejeição)

```bash
# Estados novos: snoozed / superseded / expired + responsável/prazo/motivo
.venv/bin/hermes-seo-agent checklist snooze <id> --deadline 2026-12-31 --responsible editor
.venv/bin/hermes-seo-agent checklist reject <id> --reason "fora de escopo"
.venv/bin/hermes-seo-agent backlog expire           # propostas com prazo vencido → expired
.venv/bin/hermes-seo-agent backlog reject <id> --reason "..."
```

**Rejeitado não volta**: pauta/checklist/interlink rejeitados são suprimidos em
re-gerações sem nova evidência material.

### Medição por tipo de intervenção

```bash
# Ao concluir: captura baseline GSC + implemented_at (base da janela de medição)
.venv/bin/hermes-seo-agent checklist done <id> --intervention-type title_meta
# Mede o antes × depois SOMENTE após a janela mínima (config editorial_measurement_min_days)
.venv/bin/hermes-seo-agent checklist measure <id> [--min-days 7]
```

**Reabertura de sugestões rejeitadas**: cada item/pauta/link guarda uma chave de
hipótese estável (`hypothesis_key`) e um `evidence_fingerprint` da evidência.
Rejeitado **reabre apenas quando a evidência material muda** (fingerprint
diferente) — variação de métricas = reabertura; mesma evidência = bloqueio.

### Workflow de interlinks (CLI)

```bash
.venv/bin/hermes-seo-agent interlinks list --status proposed   # ver sugestões
.venv/bin/hermes-seo-agent interlinks approve <id>             # aprovar
.venv/bin/hermes-seo-agent interlinks reject <id> --reason "..."  # rejeitar (supressão)
.venv/bin/hermes-seo-agent interlinks snooze <id>              # adiar
.venv/bin/hermes-seo-agent interlinks done <id>                # concluído
```

Depois de executar as melhorias, o `impact` mede o antes × depois e o
`reindex-status` mostra quando o Google re-rastreou.

---

## 7. Operação agendada

### Hermes (recomendado)

O `install.sh` cria o job `Hermes SEO Agent` (a cada 6h) com skill + monitor.
O monitor só acorda o LLM quando a assinatura do inventory muda (idle = 0 tokens).

### Docker

```bash
docker compose up -d                    # roda `schedule` (watchdog)
docker compose run --rm seo-agent cycle --limit 500   # execução única
```

### Cron (fallback sem Hermes)

```bash
crontab crontab.example
```

O `schedule` decide a fase por horário:
- **sempre**: audit + report (limit `MAX_URLS_PER_RUN`);
- **diário às 06:00** (`--inspect-hours 6`): inspeção GSC;
- **semanal (segunda)** (`--deep-weekday 1`): opportunities + deep report + coleta GA4.

---

## 8. Opportunity Agent (M0–M8)

Camada consultiva: sugere, prioriza, mede e aprende — **nunca publica conteúdo
nem altera links automaticamente**. Todas as decisões ficam para revisão humana.

### Saúde das fontes (M0)

```bash
hermes-seo-agent integration-status            # estado persistido (sem rede)
hermes-seo-agent integration-status --live     # checagens ao vivo (uma chamada por fonte)
```

Cada fonte reporta `data_status` canônico: `available | partial | missing |
invalid`. Uma fonte ausente NUNCA vira métrica zero.

### Memória editorial — corpus (M2)

```bash
hermes-seo-agent corpus rebuild --limit N      # crawl incremental com checkpoint
hermes-seo-agent corpus search "termo"
hermes-seo-agent corpus coverage "tema"        # quais SEÇÕES cobrem o tema
hermes-seo-agent corpus stats                  # coverage %, falhas, staleness
```

O rebuild é idempotente por `content_hash`: re-executar só reindexa o que
mudou. `stats` mostra `coverage_pct`, `sitemap_without_corpus`,
`staleness` e o último run (`processed/changed/failed`). **Antes de propor
"new content", consulte `corpus coverage`** — "não encontrei conteúdo" só
vale para o que foi indexado.

### Tópicos e clusters (M3)

```bash
hermes-seo-agent topics graph                  # clusters por entidade
hermes-seo-agent topics coverage "nintendo"    # posts, indexáveis, links, Top3/10, GA4
```

### Inteligência externa — Google Trends (M4)

```bash
hermes-seo-agent market status                 # provider, custo, quota
hermes-seo-agent market candidate "one piece"  # candidato (checa o corpus; nunca pauta)
```

A Google Trends API está em **alpha com allowlist por conta**. Para liberar:

1. Acesse <https://developers.google.com/search/apis/trends?hl=pt-br>;
2. Preencha o **formulário de inscrição como testador alfa** (seção "Ter
   acesso antecipado à versão Alfa");
3. Quando a conta for aprovada, a chave `GOOGLE_API_KEY` (ou `TRENDS_API_KEY`)
   do `.env` passa a funcionar — **não é preciso gerar chave nova**;
4. Confirme com `integration-status --live` (a fonte `external` sai de
   `invalid` para `available`).

Enquanto não autorizado, o `market candidate` degrada com `external_note` e o
candidato é gerado só pela checagem interna (seguro).

### Rankability (M5)

```bash
hermes-seo-agent rankability "nintendo" [--external-difficulty 0.5]
```

Score calibrável (não "probabilidade"), cada fator com explicação.

### Decision engine (M6)

```bash
hermes-seo-agent decide "jujutsu kaisen" [--impressions 500] [--trend growing]
```

Árvore: demanda → relevância → cobertura → `new_content` / `expand_existing` /
`refresh` / `internal_link` / `cannibalization_review` / `monitor` / `discard`.
`CandidateScore` (5 fatores) e `ActionScore` (impacto×confiança×facilidade)
são **separados**.

### Brief de pesquisa (M7)

```bash
hermes-seo-agent brief "jujutsu kaisen"
```

URL recomendada (ou justificativa p/ novo), diferenciação, subtópicos, risco
de duplicação, links internos, critérios de aceite. Revisão humana obrigatória.

### Medição e aprendizado (M8)

```bash
hermes-seo-agent outcomes register "gojo idade" --human-decision approved \
    --implemented-action expand --url https://...   # baseline automático + scores
hermes-seo-agent outcomes list
hermes-seo-agent outcomes measure --id 1 --days 28   # exige janela completa
hermes-seo-agent outcomes recalibrate                # só SUGERE ajustes
```

`register` liga a decisão M6 ao outcome (grava evidência + CandidateScore +
ActionScore) e captura baseline GSC+GA4. `measure` bloqueia antes da janela
mínima e deriva o verdict de GSC+GA4. Os pesos permanecem fixos até haver
volume suficiente de outcomes medidos.

---

## 10. Onde está o estado

| O quê | Onde |
|---|---|
| SQLite (ciclos, findings, fila, orçamento, ações, audit) | `state/seo_agent.db` (config `SQLITE_PATH`) |
| Relatórios | stdout / `state/` (logs de cron/docker) |
| Credenciais | `.env` (nunca commitado) |

---

## 11. Troubleshooting rápido

| Sintoma | Solução |
|---|---|
| `pip install` falha (mirror interno) | o `install.sh` já tenta o PyPI público em fallback |
| `cron: job já existe` mas duplicou | gateway do Hermes parado não persiste `jobs.json`; inicie com `hermes gateway install` |
| `inspect` avisa "GSC não configurado" | siga [`SETUP.md`](SETUP.md) seções 3–7 |
| `apply` retorna `skipped: no supported fix spec` | o JSON precisa de `fix.type` ∈ {`wp_media_alt`, `wp_post_meta`} |
| `apply` retorna `skipped: already executed` | ação já feita (idempotente) — é o comportamento correto |
| `market candidate` mostra `Trends indisponível: HTTP 403 GetGraph blocked` | a chave não está na allowlist do alpha — inscreva-se como testador alfa (ver seção 8, M4) |
| `corpus stats` mostra `coverage_pct` baixo | rode `corpus rebuild --limit N` (ou sem limit p/ o sitemap todo); o rebuild é incremental por hash |
| WordPress local fora do ar | `cd devilbox && docker-compose up -d php httpd mysql` |
| Estático local fora do ar | `cd unicorniohater-static && python3 -m http.server 8081 --directory _site` |

---

## 12. Documentos relacionados

- [`SETUP.md`](SETUP.md) — credenciais Google passo a passo
- [`DESIGN.md`](DESIGN.md) — arquitetura, modelo de dados, roadmap
- [`README.md`](README.md) — visão geral
- `hermes/SKILL.md` — instruções para o agente LLM do Hermes
