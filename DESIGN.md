# Hermes SEO Agent — Design Document

> Documento de arquitetura e roadmap. Complementa o `README.md`.
> Status: **Fases 0–5 implementadas** (fundação, inventory/auditoria, fila + URL
> Inspection GSC, oportunidades/CWV, executor safe_fix, ferramentas externas +
> operação). Conectores Google prontos e testados com mocks; execução real exige
> credenciais (GSC/PSI/CrUX/GA4).

---

## 1. Visão

Agente autônomo de auditoria e correção de SEO, executável em ciclos a partir de um
pipeline Hermes. Ele:

1. Reconcilia URLs (WordPress, site estático, sitemap, Google Search Console).
2. Detecta problemas técnicos, de conteúdo e de performance.
3. Descobre oportunidades de tráfego (Search Analytics, GA4, Core Web Vitals).
4. Aplica apenas correções de baixo risco (`safe_fix`); ações destrutivas vão para
   `approval_required`.
5. Emite relatório JSON (stdout, para Hermes) e Markdown (para humanos).

**Princípios não negociáveis:**
- Nunca deletar conteúdo automaticamente (invariante de código, não de convenção).
- Toda ação deve ser idempotente, auditável e reversível.
- `--dry-run` disponível e recomendado como default em qualquer comando.
- Credenciais nunca em repositório; automação usa Service Account.
- **IA só para julgamento.** Tarefas mecânicas/repetitivas são tooling
  determinístico (scripts/CLI), nunca chamadas de LLM. Ver seção 8.

---

## 2. Stack e decisões

| Decisão | Escolha | Justificativa |
|---|---|---|
| Linguagem | Python 3.11+ | Fiel ao README (`python -m hermes_seo_agent.cli ...`) |
| Persistência | SQLite (arquivo local) | Estado por instância; evoluir para Postgres se houver multi-site |
| Config | `.env` + `pydantic-settings` | Tipado, validação no startup |
| HTTP | `httpx` (async) | Suporte a timeout, retry, proxy |
| Scheduling | `cron` / Docker; opcionalmente Prefect/Airflow | Começar simples |
| Auth Google | Service Account (automação) + OAuth 2.0 (ações humanas) | Separação de privilégio |
| Auth WordPress | Application Passwords (Basic auth) | Mesmo padrão já usado no `unicornio-agent` |
| Logging | `structlog` (JSON) | Observabilidade e integração com Hermes |

**Diretório do pacote:**

```
seo-agent/
├── README.md
├── DESIGN.md
├── .env.example
├── pyproject.toml
├── hermes_seo_agent/
│   ├── __init__.py
│   ├── cli.py                 # inventory, audit, inspect, opportunities, report, cycle
│   ├── config.py              # settings (pydantic-settings)
│   ├── connectors/
│   │   ├── __init__.py
│   │   ├── base.py            # contrato: auth, rate-limit, retry/backoff, timeout
│   │   ├── wordpress.py       # REST via Application Passwords (espelho do unicornio-agent)
│   │   ├── static_site.py     # site estático Eleventy + sitemap_index.xml
│   │   ├── search_console.py  # Search Analytics + sitemaps + URL Inspection + coverage
│   │   ├── indexing_api.py    # best-effort (JobPosting/BroadcastEvent)
│   │   ├── pagespeed.py       # PageSpeed Insights API
│   │   ├── crux.py            # CrUX API (Core Web Vitals campo)
│   │   ├── analytics.py       # GA4 Data API
│   │   └── safe_browsing.py   # Safe Browsing API
│   ├── inventory/             # reconciliação WP vs sitemap vs estático vs GSC
│   ├── checks/                # http status, redirects, canonical, robots, orphan, thin
│   ├── rules/                 # catálogo de regras (detect + severity + suggested_action)
│   ├── queue/                 # fila persistente da URL Inspection
│   ├── planner/               # monta action plan
│   ├── executor/              # aplica safe_fix / marca approval_required
│   ├── storage/               # SQLite: estado, snapshots, audit trail
│   ├── tools/                 # tooling determinístico (seção 8) — sem LLM
│   └── report/                # JSON + Markdown
└── tests/
```

---

## 3. Ambiente alvo (site)

**Single-site.** Um único site, duas superfícies de URL que precisam ser reconciliadas:

### 3.1 WordPress (fonte de conteúdo — dinâmico)

| Item | Local (Devilbox Docker) | Produção |
|---|---|---|
| URL | `http://wordpress.dvl.to:8080` | `https://prod.unicorniohater.com.br/wp-admin/` |
| Caminho | `/home/joaofagner/workfolder/devilbox/data/www/wordpress` | — |
| REST base | `/wp-json/wp/v2` | `/wp-json/wp/v2` |
| Auth | Application Passwords (Basic) | Application Passwords (Basic) |
| SEO plugin | Rank Math | Rank Math |

- Auth espelha o `unicornio-agent`: header `Authorization: Basic base64(user:app_password)`,
  com `context=edit` para expor `content.raw`, `title.raw` e meta.
- Rank Math guarda `rank_math_title`, `rank_math_description`,
  `rank_math_focus_keyword`, canonical e robots por post (ver
  `unicornio-agent/src/unicornio_editor/seo/rank_math.py`).

### 3.2 Site estático (o que o Google rastreia — Eleventy/11ty)

| Item | Valor |
|---|---|
| Repo local | `/home/joaofagner/workfolder/unicorniohater-static` |
| Gerador | Eleventy (11ty) |
| Publicado | `https://www.unicorniohater.com.br/` |
| Sitemap | `https://www.unicorniohater.com.br/sitemap_index.xml` |
| Geração do sitemap | `scripts/sitemap.mjs` (`writeSitemaps`) — **no build do estático**, não no WP |
| robots.txt | `Sitemap: {{ site.url }}/sitemap_index.xml` |
| Webhook server | porta 8082 (recebe eventos do WP) |
| Static server | porta 8081 |
| CDN | Cloudflare (purge via `wp wse cdn purge`) |

**Implicação crítica para o agente:** o **sitemap é gerado pelo site estático**, então a
reconciliação é de **três vias**, não duas:

```
WordPress (prod.unicorniohater.com.br/slug)
   └─→ site estático (www.unicorniohater.com.br/slug/)
          └─→ sitemap_index.xml (www.unicorniohater.com.br)
                └─→ Google Search Console (indexação/impressões)
```

O domínio público/canônico é `www.unicorniohater.com.br` (o plugin WP Static Engine já
faz o override de domínio interno → público no Instant Indexing e nos payloads).

### 3.3 O que JÁ existe e o agente NÃO deve reinventar

- **IndexNow / Instant Indexing:** já feito pelo Rank Math + override do WP Static Engine.
- **Purge de CDN (Cloudflare):** já feito via `wp wse cdn purge`.
- **Geração de sitemap:** já feito pelo Eleventy no build.
- **Bridge WP → estático (webhooks assinados HMAC):** já feito pelo WP Static Engine.

O agente de SEO deve **consumir** essas superfícies (ler sitemap, ler GSC, ler o estático)
e **acionar** o que já existe (ex.: pedir purge/rebuild via `wp wse` quando detectar
divergência), em vez de reimplementar.

---

## 4. Conectores (integrações)

### 4.1 Contrato base (`connectors/base.py`)

Todo conector implementa:

```python
class BaseConnector:
    async def request(self, ...) -> Response:
        """Aplica retry com backoff exponencial, respeita Retry-After,
        aplica timeout e reporta quota consumida."""
```

Requisitos comuns:
- Retry exponencial com jitter; respeitar `Retry-After`.
- Timeout global e por requisição configuráveis.
- Métrica de quota consumida (para orçamento dinâmico).
- Mascaramento de segredos em logs.

### 4.2 WordPress (`wordpress.py`)

Espelha o client já validado em `unicornio-agent/src/unicornio_editor/wordpress.py`:
- Basic auth via `WORDPRESS_APP_USER` / `WORDPRESS_APP_PASSWORD` (Application Passwords).
- `context=edit` obrigatório para expor `raw` e meta.
- Leitura de posts/pages/media; **escrita somente** por `safe_fix` e sempre atrás de
  `dry_run` e das invariantes de segurança (seção 7).

### 4.3 Site estático + sitemap (`static_site.py`)

- Baixa e parseia `sitemap_index.xml` + sub-sitemaps (posts, pages, categories, authors).
- Crawl leve do HTML publicado para extrair canonical, robots, title, meta, OG, schema.
- `SITE_URL` / `SITEMAP_URL` configuráveis (local: `http://localhost:8081`; prod: `https://www.unicorniohater.com.br`).

### 4.4 Google — fase 1 (prioridade)

| Conector | API | Uso | Escopos / notas |
|---|---|---|---|
| `search_console.py` | Search Console | Search Analytics, sitemaps, coverage (indexação), **URL Inspection** | Service Account com acesso à propriedade `https://www.unicorniohater.com.br/` |
| `pagespeed.py` | PageSpeed Insights | Core Web Vitals (LCP/CLS/INP), diagnósticos | Chave de API |
| `crux.py` | CrUX | CWV de campo por origem/URL | Chave de API |
| `analytics.py` | GA4 Data API | Sessões, bounce, conversões → "low-value" | Service Account |
| `indexing_api.py` | Indexing API | Notificar URLs novas/atualizadas | **Somente** JobPosting/BroadcastEvent; best-effort |
| `safe_browsing.py` | Safe Browsing | Detectar URLs comprometidas | Chave de API |

> Nota: o site usa **IndexNow** (via Rank Math) para indexação rápida. A Indexing API do
> Google é reservada a JobPosting/BroadcastEvent — usar como *best-effort*, nunca como
> substituta do fluxo normal.

**Auth — dois caminhos:**
- **Service Account** (`GOOGLE_APPLICATION_CREDENTIALS`): automação headless.
- **OAuth 2.0**: para ações que exigem identidade humana (approval flow).

**Quota/limites a respeitar (documentar no config):**
- URL Inspection: 2.000/dia (orçamento default 1.800, ajustável).
- Search Analytics: 1.200 queries/min por propriedade.
- PageSpeed/CrUX: quotas por chave.

### 4.5 Ferramentas gratuitas — fase 2

| Ferramenta | API | Uso |
|---|---|---|
| Wayback Machine | CDX / availability | Histórico de URL antes de decisão de remoção |
| Schema.org validator | richresults / validator | Validar dados estruturados |
| Sitemap/robots validators | local + via GSC | Validação de formato |

**Ferramentas pagas (opcionais, desativadas por default, fase 5):**
Screaming Frog (crawl profundo), Ahrefs/Semrush/DataForSEO (backlinks/keywords/rank).

---

## 5. Modelo de dados (SQLite)

Tabelas principais (schema inicial):

```sql
-- Estado corrente de cada URL conhecida
urls(
  id INTEGER PRIMARY KEY,
  url TEXT UNIQUE NOT NULL,
  source TEXT,                -- wordpress | static | sitemap | gsc | external
  wp_url TEXT,                -- URL no WordPress (prod.unicorniohater.com.br/...)
  static_url TEXT,            -- URL publicada (www.unicorniohater.com.br/...)
  first_seen TEXT,
  last_seen TEXT,
  last_status_code INTEGER,
  canonical TEXT,
  robots_state TEXT,
  in_sitemap INTEGER,
  in_index INTEGER,           -- GSC coverage
  impressions INTEGER,        -- últimos N dias
  clicks INTEGER,
  is_orphan INTEGER,
  cwv_json TEXT,              -- CrUX/PSI snapshot
  updated_at TEXT
);

-- Fila persistente da URL Inspection
inspection_queue(
  id INTEGER PRIMARY KEY,
  url_id INTEGER REFERENCES urls(id),
  priority INTEGER,           -- ver estratégia no README
  status TEXT,                -- pending | in_progress | done | failed
  last_inspected_at TEXT,
  result_json TEXT,
  created_at TEXT
);

-- Regras avaliadas e seus resultados
findings(
  id INTEGER PRIMARY KEY,
  cycle_id TEXT,
  rule_id TEXT,
  url_id INTEGER REFERENCES urls(id),
  severity TEXT,              -- info | low | medium | high | critical
  detail_json TEXT,
  created_at TEXT
);

-- Ações propostas / executadas
actions(
  id INTEGER PRIMARY KEY,
  cycle_id TEXT,
  finding_id INTEGER REFERENCES findings(id),
  level TEXT,                 -- safe_fix | approval_required
  status TEXT,                -- pending | executed | approved | rejected | rolled_back
  fingerprint TEXT,           -- idempotência
  before_json TEXT,
  after_json TEXT,
  rollback_json TEXT,         -- ação inversa
  executed_at TEXT
);

-- Trilha de auditoria imutável (append-only)
audit_log(
  id INTEGER PRIMARY KEY,
  ts TEXT,
  actor TEXT,
  action_type TEXT,
  entity TEXT,
  before_json TEXT,
  after_json TEXT
);

-- Snapshot por ciclo (para diff entre execuções)
cycles(
  id TEXT PRIMARY KEY,
  started_at TEXT,
  finished_at TEXT,
  summary_json TEXT
);

-- Estado SEO completo de cada página ao longo do tempo (histórico before/after)
page_snapshots(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  cycle_id TEXT,
  source TEXT,                -- audit | executor | opportunities | manual
  linked_action TEXT,         -- fingerprint da ação que causou este estado
  status_code INTEGER,
  title TEXT,
  meta_description TEXT,
  canonical TEXT,
  meta_robots TEXT,
  h1 TEXT,
  word_count INTEGER,
  content_hash TEXT,          -- sha256 do HTML (detecção de mudança de conteúdo)
  cwv_json TEXT,              -- {"lcp":..,"cls":..,"inp":..}
  gsc_json TEXT               -- {"impressions":..,"clicks":..}
);
CREATE INDEX idx_snapshots_url ON page_snapshots(url, captured_at);
```

---

## 6. Regras de detecção (catálogo)

Cada regra: `id`, `severity`, `suggested_action`, `level` (safe/approval/none) e
`mode` (deterministic | ai) — ver seção 8.

### Integridade técnica
| id | Regra | Severidade | Ação sugerida | mode |
|---|---|---|---|---|
| `broken_internal_link` | Link interno 404 | high | corrigir/remover (safe, se configurado) | deterministic |
| `broken_external_link` | Link externo 404 | medium | substituir/remover (safe) | deterministic |
| `redirect_chain` | >1 hop | medium | normalizar destino (approval) | deterministic |
| `redirect_loop` | loop | critical | normalizar (approval) | deterministic |
| `canonical_missing` | sem canonical | medium | definir (approval) | deterministic |
| `canonical_conflict` | canonical ≠ sitemap/estático | high | alinhar (approval) | deterministic |
| `wp_static_mismatch` | URL WP publicada mas ausente do estático/sitemap | high | publicar/rebuild (approval) | deterministic |
| `static_orphan` | URL no estático sem correspondente no WP | medium | investigar (info) | deterministic |
| `noindex_inconsistency` | meta vs X-Robots-Tag vs robots | high | alinhar (approval) | deterministic |
| `sitemap_blocked` | URL do sitemap bloqueada no robots.txt | high | corrigir robots (approval) | deterministic |
| `orphan_page` | no sitemap, sem links internos | medium | linkar ou noindex (approval) | deterministic |
| `duplicate_content` | title+H1+meta idênticos | high | canonizar/consolidar (approval) | deterministic (normalizado) |
| `thin_content` | poucas palavras/template vazio | medium | melhorar/noindex (approval) | deterministic (limiar) / ai (ambiguidade) |

### Performance
| id | Regra | Severidade | Ação sugerida | mode |
|---|---|---|---|---|
| `cwv_lcp_poor` | LCP > 2.5s | medium | otimizar (safe, se configurado) | deterministic |
| `cwv_cls_poor` | CLS > 0.1 | medium | otimizar (safe) | deterministic |
| `cwv_inp_poor` | INP > 200ms | medium | otimizar (safe) | deterministic |
| `image_no_dimensions` | sem width/height | low | corrigir (safe) | deterministic |
| `image_no_lazy` | sem loading=lazy | low | corrigir (safe) | deterministic |
| `image_no_alt` | sem alt | low | corrigir (safe) | deterministic |
| `render_blocking` | CSS/JS bloqueante | low | adiar (safe) | deterministic |

### Conteúdo / Oportunidades
| id | Regra | Severidade | Ação sugerida | mode |
|---|---|---|---|---|
| `keyword_cannibalization` | 2+ URLs mesma query | high | consolidar/canonizar (approval) | ai (agrupamento semântico) |
| `title_duplicate` | title duplicado | medium | reescrever (sugestão LLM) | deterministic (deteção) / ai (sugestão) |
| `title_missing` | sem title | high | reescrever (approval) | deterministic |
| `title_too_long` | >60 chars | low | reescrever (sugestão) | deterministic |
| `meta_duplicate` | meta description duplicada | medium | reescrever (sugestão) | deterministic / ai |
| `meta_too_long` | >160 chars | low | reescrever (sugestão) | deterministic |
| `structured_data_invalid` | schema inválido | high | corrigir (approval) | deterministic (parser) |
| `structured_data_missing` | FAQ/Article/Product ausente | low | adicionar (approval) | deterministic |
| `low_ctr_opportunity` | alta impressão, CTR baixo | medium | reescrever title (sugestão) | deterministic (deteção) / ai (sugestão) |
| `zero_click_impression` | impressões sem cliques por N dias | medium | revisar conteúdo (sugestão) | deterministic |

### Valor (via GA4)
| id | Regra | Severidade | Ação sugerida | mode |
|---|---|---|---|---|
| `low_value_page` | alto bounce + baixo tempo | medium | melhorar/consolidar (approval) | deterministic (limiar) / ai |
| `stale_low_traffic` | sem tráfego por N dias | info | revisar (nunca deletar) | deterministic |

---

## 7. Modelo de segurança (refinado)

Níveis (mantidos do README) + invariantes adicionais:

1. `observe` — somente leitura.
2. `safe_fix` — mudanças de baixo risco (sitemap/cache refresh, metadata, imagens).
3. `approval_required` — delete, canonical, redirects, noindex, conteúdo publicado.

**Invariantes de código (bloqueadas por construção, não por convenção):**
- O `executor` **rejeita** qualquer ação de tipo `delete`.
- **Blast radius:** máximo de `N` `safe_fix` por ciclo (default 10) e `M` URLs por execução.
- **Reversão:** todo `safe_fix` registra `rollback_json`.
- **Idempotência:** `fingerprint` impede re-execução sem mudança de estado.
- **Pausa automática:** se a taxa de erro subir, o ciclo para e reporta.
- **`--dry-run`** global: gera o plano sem nenhuma escrita.

---

## 8. Tooling determinístico (evitar IA em tarefas repetitivas)

> **Princípio:** o LLM é caro, lento e não-determinístico. Qualquer verificação com
> resposta determinística é **código puro**, nunca uma chamada de IA. A IA entra apenas
> onde há **julgamento semântico** ou **geração criativa**.

### 8.1 O que é determinístico (sempre script/CLI, sem LLM)

| Verificação | Como | Ferramenta |
|---|---|---|
| HTTP status (200/301/404/5xx) | request + status code | `checks/http.py` |
| Cadeias/loops de redirect | seguir `Location` até N hops | `checks/redirects.py` |
| Diff sitemap ↔ URLs (órfãs, ausentes, órfãs estáticas) | set difference | `tools/sitemap_diff.py` |
| Canonical presente/duplicado/conflitante | parse `<link rel=canonical>` + compare | `checks/canonical.py` |
| noindex/robots/X-Robots-Tag | parse meta + headers + robots.txt | `checks/robots.py` |
| Comprimento de title/meta | contagem de caracteres | `checks/meta.py` |
| Title/meta duplicados | hash normalizado + group by | `checks/duplicates.py` |
| Links quebrados internos/externos | crawl + status | `checks/links.py` |
| CWV fora do limiar | PSI/CrUX número vs threshold | `checks/cwv.py` |
| Atributos de imagem (alt/width/height/loading) | parse HTML | `checks/images.py` |
| Schema válido | parser de JSON-LD/microdata | `checks/schema.py` |
| URL WP presente no estático/sitemap | join por slug/ID | `tools/reconcile.py` |
| Purge CDN / rebuild estático | `wp wse cdn purge` / `wp wse rebuild` | `tools/wse_trigger.py` |

### 8.2 Onde a IA é necessária (julgamento/criação)

| Tarefa | Por quê IA |
|---|---|
| Detectar "thin content" semanticamente vazio (não só poucas palavras) | ambiguidade de contexto |
| Agrupar queries para canibalização de keyword | semântica, não string match |
| Sugerir reescrita de title/meta/description | geração criativa |
| Avaliar se uma URL é "low-value" além do limiar numérico | julgamento |
| Priorizar oportunidades com contexto editorial | julgamento |

### 8.3 Regras de projeto

1. **Uma regra só usa IA se `mode == "ai"`.** O executor nunca chama LLM para regras `deterministic`.
2. **Cache por entrada:** resultados determinísticos são cacheados por hash(entrada); não re-rodar o que não mudou.
3. **IA é opt-in e custo-controlada:** limite de chamadas por ciclo, e só após os gates determinísticos passarem (mesmo padrão do `unicornio-agent`, que só paga visão para posts que já passaram nos outros gates).
4. **Hermes chama as ferramentas diretamente:** a CLI expõe comandos atômicos (`reconcile`, `diff-sitemap`, `check-links`...) para o orquestrador acionar **sem** passar pela IA quando a tarefa é mecânica.

### 8.4 Analogia com o padrão já existente

O `unicornio-agent` já segue este princípio: o enriquecimento de links internos é
**determinístico** (`internal_links.py`, sem IA — uma string replace não julga contexto),
e a IA é reservada para visão/checklist de publicação. O SEO agent herda a mesma linha:
**mecânica → código; julgamento → IA.**

---

## 9. Contrato de saída (mantido do README)

```json
{
  "status": "ok",
  "summary": {},
  "findings": [],
  "safe_actions": [],
  "approval_required": []
}
```

Hermes usa `approval_required` como **fila de revisão**, nunca como fila de execução.

---

## 10. Roadmap

### Fase 0 — Fundação ✅
- Estrutura do pacote, `pyproject.toml`, `config.py`, `connectors/base.py`, `structlog`.
- SQLite (`storage/`) com schema inicial e migrações simples.
- CLI mínima com `--dry-run` global.
- `.env.example` (Application Passwords + sitemap/estático).
- `install.sh` idempotente (padrão unicornio-agent) + `hermes/SKILL.md` + `monitor.sh`.

### Fase 1 — Inventory + Auditoria técnica ✅
- Conectores WordPress (Application Passwords) + site estático/sitemap.
- Reconciliação de três vias (WP vs sitemap vs estático) por **path** (host-agnóstico).
- Checks HTTP/redirect/canonical/robots/meta (todos determinísticos).
- Rules registry (20 regras, mode deterministic|ai) + planner (blast radius) + report JSON/MD + snapshot SQLite.
- Tooling `diff-sitemap` (sem IA) e `wp_static_mismatch` por amostra.
- Verificado contra o ambiente real local (Devilbox WP 16.130 posts + sitemap estático 15.080 URLs): 1.196 posts fora do sitemap, 114 titles longos em 120 URLs auditadas.

### Fase 2 — Fila + URL Inspection ✅
- `connectors/search_console.py`: Search Analytics (query/page), URL Inspection, sitemaps — auth via Service Account (`google-auth`, extra `[google]`) ou token provider injetável (testes).
- `queue/inspection.py`: priorização determinística em 6 tiers (README) + `build_queue_entries` puro; orçamento diário persistido (`inspection_budget`).
- `storage/db.py`: tabelas `inspection_queue` (idempotente: UNIQUE(url,status)) e `inspection_budget`; snapshot de pendências.
- CLI `inspect`: constrói a fila (inventory + GSC opcional), dry-run ou drena dentro do orçamento (`--budget`).
- Verificado local: 15.080 URLs enfileiradas, posts recentes em tier 1. Real GSC requer `GOOGLE_APPLICATION_CREDENTIALS`.

### Fase 3 — Oportunidades + Performance ✅
- `connectors/pagespeed.py` (LCP/CLS/INP normalizados), `crux.py` (p75 de campo), `analytics.py` (GA4 engajamento, auth injetável).
- `checks/cwv.py`: thresholds determinísticos (LCP≤2.5s, CLS≤0.1, INP≤200ms).
- Regras novas: `cwv_lcp_poor`, `cwv_cls_poor`, `cwv_inp_poor`, `image_no_alt`, `image_no_dimensions`, `low_ctr_opportunity`, `zero_click_impression`.
- CLI `opportunities`: detecção determinística de low-CTR/zero-click (GSC) + CWV de campo (CrUX). Real requer `PAGESPEED_API_KEY`/`CRUX_API_KEY`/`GA4_PROPERTY_ID`.

### Fase 4 — Executor seguro ✅
- `executor/executor.py`: aplica `safe_fix` com invariantes de código — sem delete por construção, fingerprint de idempotência, before/after/rollback, audit trail, blast radius, dry-run bloqueia escrita.
- Fixes suportados: `wp_media_alt` (alt de mídia) e `wp_post_meta` (meta Rank Math); o executor **nunca adivinha** — o fix spec vem do agente/AI.
- CLI `apply <file.json>`: executa ações com fix spec (dry-run por default).
- Verificado end-to-end contra o WordPress local do Devilbox: write real no-op executado (fingerprint gravado) e re-execução pulada por idempotência; `actions` + `audit_log` populados.

### Fase 5 — Ferramentas externas + operação ✅
- `connectors/wayback.py`: availability + contagem de snapshots (CDX) — evidência de arquivo antes de qualquer decisão de remoção (sem custo, sem chave).
- `checks/schema.py`: extração de JSON-LD (`application/ld+json`) + validação determinística dos campos obrigatórios por `@type` (Article/NewsArticle/FAQPage/Product/Organization/WebSite/BreadcrumbList); regras `structured_data_invalid`/`structured_data_missing`.
- `tools/screaming_frog.py`: import de crawl CSV (Address/Status Code) — crawl externo opcional como entrada do audit.
- `tools/wse_trigger.py`: aciona o que já existe (`wp wse cdn purge`, `wp wse rebuild smart|full|flush`, `wp wse status`) via wp-cli, com dry-run.
- `report/notify.py`: alerta por webhook genérico (`ALERT_WEBHOOK_URL`) quando high+critical ≥ threshold (`ALERT_HIGH_THRESHOLD`).
- CLI novos: `wayback URL`, `validate-schema URL`, `import-crawl FILE.csv`, `wse purge|rebuild|status`, `telemetry [--notify]`, `schedule [--inspect-hours N] [--deep-weekday N]` (watchdog por janela de horário, padrão publish-cron).
- Operação: `Dockerfile` + `docker-compose.yml` (schedule em container) + `crontab.example` (fallback sem Hermes gateway).
- Verificado local: Wayback real (910 snapshots da home), schema do site válido (NewsArticle completo), telemetry lendo o SQLite real.

### Fase 6 — Histórico confiável por página (before/after) ✅
- **`page_snapshots`** (SQLite): estado SEO completo de cada URL por captura — status, title, meta, canonical, robots, h1, word_count, `content_hash` (sha256 do HTML), `cwv_json`, `gsc_json`; `source` (audit|executor|opportunities|manual) e `linked_action` (fingerprint da ação que causou o estado).
- **`report/history.py`**: `diff_snapshots` (before→after por campo, incluindo CWV improved/worsened e deltas de GSC), `summarize_page` (timeline por página, amigável ao agente), `aggregate_trends` (achados por ciclo, ações executadas, evolução de CWV no site).
- CLI: `snapshot URL` (captura manual), `history URL [--limit N]` (timeline + diffs), `trends` (agregados por ciclo).
- Captura automática: `audit` salva snapshot de cada página analisada; `apply` re-captura a página afetada **pós-fix** (`source=executor`, `linked_action`); `opportunities` salva snapshot com CWV da origem.
- Verificado: histórico local de URLs reais, diffs estáveis (hash idêntico = sem mudança), trends agregando 6 ciclos.

---

## 11. Perguntas em aberto (a decidir antes da implementação)

1. **GSC:** a propriedade registrada é `https://www.unicorniohater.com.br/` (domain ou
   URL-prefix)? Isso define como consultar coverage e URL Inspection.
2. **LLM para sugestões:** integrar já na Fase 3 ou adiar? (Recomendação: adiar; começar
   100% determinístico e adicionar IA só para as regras `mode == ai`.)
3. **Frequência/limiares default:** grace period de "URL nova" e janela de "recentemente
   perdeu impressões" — valores iniciais?
4. **Escrita via REST:** quais `safe_fix` o WordPress permite via Application Passwords
   (ex.: atualizar meta Rank Math, corrigir alt de imagem)? Mapear permissões do app
   password antes de codar o executor.
