# Runbook — Validação de produção (SEO Agent Control Center)

Valida a **persistência e as análises** com fontes reais (WordPress, GSC/GA4,
corpus, concorrentes) e o deploy. Execute como `www`, a partir do
WorkingDirectory do serviço (`/www/wwwroot/hermes/seo-agent`).

> Auditoria de sanidade (executada no sandbox) confirmou: 0 ações órfãs (todas
> executadas → outcome), 0 itens implementados na Caixa, 0 campanha-items/
> outcomes sem lifecycle, e amostra V2 em faixa (topic/opportunity 0–100,
> confidence 0–1). O objetivo destes passos é reproduzir isso com dados reais.

## 0) Pré-flight
```bash
cd /www/wwwroot/hermes/seo-agent
# .env (produção): session_cookie_secure=true; WORDPRESS_URL=https://prod.unicorniohater.com.br
# GOOGLE_APPLICATION_CREDENTIALS=<service-account.json>; GSC_SITE_URL=...; GA4_PROPERTY_ID=...
# COMPETITOR_SITES=omelete.com.br,jovemnerd.com.br,ign.com,tecmundo.com.br
# (a)sanity: dados reais de GSC/GA4 presentes?
sqlite3 state/seo_agent.db "SELECT COUNT(*) FROM query_pages; SELECT COUNT(*) FROM ga4_page_metrics;"
```

## 1) Corpus editorial (memória de conteúdo)
```bash
# Incremental por fila; retoma run parcial. --limit 0 = até 20.000 por execução.
sudo -u www .venv/bin/hermes-seo-agent corpus rebuild --limit 0
# Repita até queue.pending=0 e run_status=ok. Depois confirme:
sudo -u www .venv/bin/hermes-seo-agent corpus stats   # documents>0, last_run_status=ok
```
> Se o sitemap do site estático (`www.`….) retornar 403 do Cloudflare, o
> `corpus_source` (R7) prefere a **API do WordPress** — garanta `WORDPRESS_URL`
> + Application Password no `.env`.

## 2) Gerar candidatos pendentes (delegação real)
```bash
# Cria ações safe_fix (pending) + itens de checklist a partir do GSC (sem rede WP-stática).
sudo -u www .venv/bin/hermes-seo-agent title-opportunities --persist
```
> Depois, na UI: Caixa → selecionar → **Delegar melhorias** → item sai da Caixa e
> vai para Lotes. Ferramenta de validação de persistência do ciclo de decisão.

## 3) Competitor Corpus + Content Gap (R7/R8)
```bash
sudo -u www .venv/bin/hermes-seo-agent competitor-crawl
sudo -u www .venv/bin/hermes-seo-agent content-gap --percent
```
> Valida a análise cruzada (nosso topic graph × concorrentes) → aba Editorial →
> **Lacunas**.

## 4) Análises V2 (Rankability/Headroom/Opportunity/Calibração)
```bash
sudo -u www .venv/bin/hermes-seo-agent rankability-v2 "dragon ball" --query "dragon ball daima temporada 2" --percent
sudo -u www .venv/bin/hermes-seo-agent calibrate   # pesos ajustados por banda (R9)
```
> A UI (Páginas, Caixa Melhorias/Calibração, Editorial/Tópicos) mostra os scores.

## 5) Deploy (mesma origem, Docker)
```bash
cd /www/wwwroot/hermes/seo-agent
export SEO_AGENT_HOST=seo.unicorniohater.com.br
export TLS_CERTS_PATH=/caminho/tls   # fullchain.pem + privkey.pem
docker compose -f docker-compose.control-center.yml up -d --build
docker compose -f docker-compose.control-center.yml ps   # api/web/worker/proxy healthy
curl -k https://$SEO_AGENT_HOST/api/v1/health             # {"status":"ok"}
```

## 6) Testes
```bash
# Backend (fonte de regra)
.venv/bin/python -m pytest -q
# Frontend (unit + componentes + e2e com Next real e API mockada)
cd frontend && npm run build && npm run test && npm run test:e2e
```

## 7) Verificação de latência (pós-fix P1–P4)
> Incidente 2026-09-08: endpoints V2 computavam sinais O(N×M) por request
> (cluster_coverage com ~8-10 queries POR URL; índice do corpus reconstruído por
> cluster) → minutos por request → 500 no nginx (timeout 60s) + CPU presa.
> Após o fix, cluster_coverage faz queries em LOTE e o índice do topic graph é
> construído 1x por request (P1/P2/P3). Confirme as latências abaixo no banco real:
```bash
cd /www/wwwroot/hermes/seo-agent
sqlite3 state/seo_agent.db "ANALYZE;" 2>/dev/null || true   # opcional
time curl -s -o /dev/null -w "%{http_code} %{time_total}s\n" \
  "https://$SEO_AGENT_HOST/api/v1/topics?limit=200"        # esperado < 15s (antes: minutos)
time curl -s -o /dev/null -w "%{http_code} %{time_total}s\n" \
  "https://$SEO_AGENT_HOST/api/v1/dashboard/today"          # esperado < 2s
time curl -s -o /dev/null -w "%{http_code} %{time_total}s\n" \
  "https://$SEO_AGENT_HOST/api/v1/pages?limit=100"          # esperado < 0.5s (sem V2 na lista)
```
- Se algum endpoint passar de ~15s, o nginx corta em 60s e devolve 500 → investigar
  antes de deixar no ar (e medir `top`/`py-spy` no worker se a CPU subir).
- `topics` processa os clusters maiores por tamanho; `limit` menor reduz o custo linearmente.

## Critérios de aceite (persistência + análise corretas — como a auditoria)
- [ ] Nenhuma ação `executed` sem `opportunity_outcome` (0 órfãs).
- [ ] Nenhum item executado/implementado aparece na Caixa (lifecycle).
- [ ] Todo `improvement_campaign_items.work_item_id` e `opportunity_outcomes.work_item_id`
      têm correspondência em `work_item_lifecycle`.
- [ ] Scores V2 sempre em faixa (topic/opportunity ∈ 0–100; confidence ∈ 0–1).
- [ ] `/health` OK e `docker compose ps` healthy.
