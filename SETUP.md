# SETUP — Credenciais Google (GSC, PageSpeed, CrUX, GA4)

Passo a passo para liberar as integrações ao vivo do Hermes SEO Agent.
Os comandos `inspect` e `opportunities` funcionam em modo seco (sem
credenciais), mas só consomem APIs reais depois desta configuração.

**Tempo estimado:** 15–30 min · **Custo:** R$ 0 (tudo no free tier do Google Cloud).

---

## 1. Visão geral — o que cada chave faz

| Variável | Para quê | Onde criar |
|---|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | Search Analytics, **URL Inspection**, sitemaps, GA4 — auth de servidor | Service Account (IAM) |
| `GOOGLE_API_KEY` | Chave compartilhada usada por **PageSpeed e CrUX** (APIs que aceitam API key) | API Keys |
| `PAGESPEED_API_KEY` | Core Web Vitals de laboratório (LCP/CLS/INP por URL) — sobrescreve `GOOGLE_API_KEY` | API Keys |
| `CRUX_API_KEY` | Core Web Vitals de campo (dados reais dos usuários) — sobrescreve `GOOGLE_API_KEY` | API Keys |
| `GA4_PROPERTY_ID` | Sinais de engajamento (sessões/bounce) → "low-value" | Google Analytics 4 |
| `GSC_SITE_URL` | Propriedade registrada no Search Console | já definida (`https://www.unicorniohater.com.br/`) |

> ⚠️ **Importante:** a **Search Console API não aceita API key** — as chamadas
> de Search Analytics, URL Inspection e sitemaps exigem o **Service Account**
> (OAuth 2.0). Uma API key criada para "Google Search Console API" não
> destrava `inspect`. Essa mesma chave serve, porém, para PageSpeed/CrUX
> (desde que as restrições da chave incluam essas APIs).

> Service Account = identidade de **servidor** (automação). API Key = chave
> simples para APIs públicas por URL (PageSpeed/CrUX). São coisas diferentes.

---

## 2. Pré-requisito: projeto no Google Cloud

1. Acesse o **[Google Cloud Console](https://console.cloud.google.com/)** e
   crie um projeto (ex.: `seo-agent`), ou reutilize um existente.
2. Anote o **Project ID** (aparece no topo do console).

---

## 3. Ativar as APIs

Abra **[APIs & Services → Library](https://console.cloud.google.com/apis/library)**
e habilite, no seu projeto:

1. **Google Search Console API**
   (também listada como *Webmaster Tools API*)
   → [referência oficial](https://developers.google.com/webmaster-tools/v1/api_reference_index)
2. **PageSpeed Insights API**
   → [guia oficial (Get Started)](https://developers.google.com/speed/docs/insights/v5/get-started)
3. **Chrome UX Report API (CrUX)**
   → [documentação oficial](https://developer.chrome.com/docs/crux/api/)
4. **Google Analytics Data API**
   → [referência oficial](https://developers.google.com/analytics/devguides/reporting/data/v1)

Cada uma tem um botão **Enable** — ative as 4 (pode demorar ~1 min para
propagar).

---

## 4. Service Account (para GSC + GA4)

A automação (Search Analytics, URL Inspection, sitemaps) usa um **Service
Account** — uma conta de máquina com e-mail próprio e uma chave JSON.

### 4.1 Criar e baixar a chave JSON

1. **[IAM → Service Accounts](https://console.cloud.google.com/iam-admin/serviceaccounts)** →
   **+ Create service account**.
2. Nome: `seo-agent`. Role: **nenhuma** (as permissões são dadas no Search
   Console/GA4, não aqui).
3. Depois de criado, clique no SA → aba **Keys** → **Add key → Create new key** →
   **JSON**. O arquivo `*.json` é baixado — **guarde fora do repositório**
   (ex.: `~/.config/hermes-seo-agent/service-account.json`).
4. Referência: [visão geral de Service Accounts](https://cloud.google.com/iam/docs/service-account-overview) ·
   [criar/gerenciar](https://cloud.google.com/iam/docs/creating-managing-service-accounts).

### 4.2 Conceder acesso no Search Console

O SA precisa ser **usuário da propriedade** no Search Console (permissão mínima:
**Full**, que inclui leitura de dados):

1. Abra o **[Search Console](https://search.google.com/search-console)** e
   selecione a propriedade `https://www.unicorniohater.com.br/`
   (se ainda não estiver cadastrada, [verifique a propriedade](https://support.google.com/webmasters/answer/9008080)).
2. **Configurações → Usuários e permissões → Adicionar usuário**.
3. Cole o **e-mail do Service Account** (termina em `@<projeto>.iam.gserviceaccount.com`)
   e escolha **Full**.
4. Referência: [adicionar usuários ao Search Console](https://support.google.com/webmasters/answer/2455991).

> O e-mail do SA está na página do SA ou dentro do JSON baixado (`client_email`).

### 4.3 (Opcional) Conceder acesso no GA4

Só se for usar `GA4_PROPERTY_ID` (engajamento):

1. **[Google Analytics](https://analytics.google.com/)** → **Admin → Property →
   Property access management**.
2. **+ Add users** → e-mail do Service Account → role **Viewer**.
3. Referência: [criar propriedade GA4](https://support.google.com/analytics/answer/9744165) ·
   [gerenciar acesso](https://support.google.com/analytics/answer/1009702).

---

## 5. API Keys (PageSpeed + CrUX)

PageSpeed e CrUX são APIs por URL — usam **API Key**, não Service Account.

1. **[APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials)** →
   **+ Create credentials → API key**.
2. Copie a chave (ex.: `AIzaSy...`).
3. **Recomendado — restringir a chave** (segurança):
   - **API restrictions**: selecione apenas *PageSpeed Insights API* e
     *Chrome UX Report API*.
   - **Application restrictions**: deixe em "None" (chamadas de servidor) ou
     restrinja por IP do servidor, se souber o IP fixo.
4. Se preferir, crie **uma chave por API** (uma só para PageSpeed, outra só
   para CrUX) e limite cada uma.
5. Referência: [PageSpeed — onde fica a chave](https://developers.google.com/speed/docs/insights/v5/get-started#APIKey).

---

## 6. GA4 — achar o Property ID

1. **[Google Analytics](https://analytics.google.com/)** → **Admin**.
2. Em **Property**, o **Property ID** é o número (ex.: `123456789`).
3. Coloque em `GA4_PROPERTY_ID` (opcional — só para regras de "low-value").

---

## 7. Preencher o `.env`

Copie o exemplo e edite:

```bash
cp .env.example .env
```

```dotenv
# ---- Google ----
GOOGLE_APPLICATION_CREDENTIALS=/caminho/para/service-account.json
GSC_SITE_URL=https://www.unicorniohater.com.br/
PAGESPEED_API_KEY=AIzaSy...           # chave restrita à PageSpeed API
CRUX_API_KEY=AIzaSy...                # chave restrita à CrUX API
GA4_PROPERTY_ID=123456789             # opcional

# ---- Orçamento / alertas ----
URL_INSPECTION_DAILY_BUDGET=1800
ALERT_WEBHOOK_URL=https://hooks.slack.com/services/...   # opcional
ALERT_HIGH_THRESHOLD=10

# ---- Segurança ----
DRY_RUN=true                          # mantenha true até validar tudo
```

Instale a dependência de auth do Google:

```bash
./install.sh                          # ou:
.venv/bin/pip install 'hermes-seo-agent[google]'
```

> `install.sh` já instala o extra `[google]` (via `pip install -e .[dev]` não
> inclui o google — rode o comando acima uma vez).

---

## 8. Verificação ao vivo

Com o `.env` preenchido e `DRY_RUN=true` (sem escrever nada):

```bash
# 1. Reconciliação (não precisa de Google)
.venv/bin/hermes-seo-agent inventory

# 2. Auditoria determinística (não precisa de Google)
.venv/bin/hermes-seo-agent audit --limit 100

# 3. GSC — constrói a fila e mostra o orçamento
.venv/bin/hermes-seo-agent inspect --dry-run
#   Agora NÃO deve mais aparecer o aviso "GSC não configurado".

# 4. GSC — executa de verdade (consome até 1.800 inspeções/dia)
DRY_RUN=false .venv/bin/hermes-seo-agent inspect --budget 50

# 5. Oportunidades: low-CTR/zero-click + CWV de campo
.venv/bin/hermes-seo-agent opportunities

# 6. Telemetria + alerta (se ALERT_WEBHOOK_URL configurado)
.venv/bin/hermes-seo-agent telemetry --notify
```

Se `inspect` retornar `"inspected": 50` e o `budget_remaining` cair, está tudo
funcionando.

---

## 9. Troubleshooting

| Sintoma | Causa provável | Solução |
|---|---|---|
| `GSC not configured: set GOOGLE_APPLICATION_CREDENTIALS` | `.env` sem o caminho do JSON | Preencha `GOOGLE_APPLICATION_CREDENTIALS` (caminho absoluto) |
| `google-auth is required...` | extra `[google]` não instalado | `.venv/bin/pip install 'hermes-seo-agent[google]'` |
| HTTP 403 `Access Not Configured` | API não ativada no projeto | Ative Search Console / PSI / CrUX / GA4 (seção 3) |
| HTTP 403 `The caller does not have permission` | SA sem acesso na propriedade | Adicione o e-mail do SA no Search Console (seção 4.2) com **Full** |
| HTTP 400 `Property not found` | `GSC_SITE_URL` errado | Use exatamente `https://www.unicorniohater.com.br/` (com barra) |
| HTTP 403 `API key not valid` | chave restrita ou projeto errado | Verifique restrições e o Project ID (seção 5) |
| Quota URL Inspection esgotada | 2.000/dia por propriedade | Reduza `URL_INSPECTION_DAILY_BUDGET` ou aguarde o dia seguinte |
| CrUX `404: no field data` | URL sem dados de campo suficientes | É normal para URLs novas/pouco acessadas — não é erro |

---

## 10. Links oficiais (resumo)

| Recurso | Link |
|---|---|
| Google Cloud Console | https://console.cloud.google.com/ |
| Ativar APIs (library) | https://console.cloud.google.com/apis/library |
| Credenciais (API keys / SA) | https://console.cloud.google.com/apis/credentials |
| Service Accounts (IAM) | https://console.cloud.google.com/iam-admin/serviceaccounts |
| Visão geral de Service Accounts | https://cloud.google.com/iam/docs/service-account-overview |
| Search Console API (referência) | https://developers.google.com/webmaster-tools/v1/api_reference_index |
| URL Inspection API | https://developers.google.com/webmaster-tools/v1/urlInspection.index/inspect |
| Verificar propriedade no GSC | https://support.google.com/webmasters/answer/9008080 |
| Adicionar usuário no GSC | https://support.google.com/webmasters/answer/2455991 |
| PageSpeed Insights API | https://developers.google.com/speed/docs/insights/v5/get-started |
| CrUX API | https://developer.chrome.com/docs/crux/api/ |
| GA4 Data API | https://developers.google.com/analytics/devguides/reporting/data/v1 |
| Criar propriedade GA4 | https://support.google.com/analytics/answer/9744165 |
| Acesso à propriedade GA4 | https://support.google.com/analytics/answer/1009702 |

---

## 11. Checklist final

- [ ] Projeto no Google Cloud criado
- [ ] 4 APIs ativadas (Search Console, PageSpeed, CrUX, GA4 Data)
- [ ] Service Account criado + JSON baixado
- [ ] SA adicionado no Search Console com permissão **Full**
- [ ] (Opcional) SA adicionado no GA4 como Viewer + `GA4_PROPERTY_ID`
- [ ] API Key criada e restrita (PageSpeed/CrUX) → `PAGESPEED_API_KEY`/`CRUX_API_KEY`
- [ ] `.env` preenchido + `pip install 'hermes-seo-agent[google]'`
- [ ] `inspect --dry-run` sem aviso de "não configurado"
- [ ] `inspect --budget 50` (com `DRY_RUN=false`) retornando `inspected > 0`
