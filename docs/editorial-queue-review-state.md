# Desenho: fila editorial com `review_state` (anti-repetição)

Objetivo: a fila editorial **avança** de um post já tratado em vez de re-processá-lo.
Hoje o predicado casa `status='pending'`, e READY/awaiting_human/blocked fica num
lado-canal (checklist/manifesto) que o seletor ignora → o mesmo post volta todo run.

Este desenho aplica o padrão já endurecido no corpus do `seo-agent`
(claim atômico + lease + TTL por relógio + fencing token + BEGIN IMMEDIATE), removendo
o que causa a repetição e garantindo boas propriedades de concorrência/recuperação.

---

## 1. `review_state` — máquina de estados

Colunas novas na tabela de itens editoriais (ex.: `editorial_items`):

```sql
-- progresso na fila (fonte da seleção)
review_state TEXT NOT NULL DEFAULT 'pending',
-- gate de publicação SEPARADO (só o cron publish-ready toca publicado)
published TEXT,            -- NULL | 'pending_publish' | 'published'
-- lease de processamento (fencing)
worker_id TEXT,
leased_at TEXT,
lease_version INTEGER NOT NULL DEFAULT 0,
handled_at TEXT,
```

Valores de `review_state`:

| Estado        | Significado                                                  |
|---------------|--------------------------------------------------------------|
| `pending`     | elegível, ainda não reclamado (único que o seletor pega)     |
| `processing`  | reclamado por um worker (tem lease + fencing token)          |
| `ready`       | processado, aguardando o cron publish-ready                  |
| `awaiting_human` | precisa de decisão humana (retry / discard / featured alternativa) |
| `blocked`     | falha que exige intervenção manual                          |

Estados terminais: `published` (via cron) ou `discarded` (via humano). Podem ser
colunas/valores extras; a seleção só olha `review_state = 'pending'`.

---

## 2. Claim atômico + recuperação de `processing` vencido

### Claim (de `pending` → `processing`), atômico sob `BEGIN IMMEDIATE`

```sql
BEGIN IMMEDIATE;
-- revalida dentro da escrita exclusiva e devolve o fencing token incrementado
UPDATE editorial_items
SET review_state='processing', worker_id=:w, leased_at=:now,
    lease_version=lease_version+1
WHERE id IN (
    SELECT id FROM editorial_items
    WHERE review_state='pending'
    ORDER BY priority DESC, created_at ASC
    LIMIT :limit
)
RETURNING id, lease_version;
COMMIT;
```

- `BEGIN IMMEDIATE` garante escrita exclusiva → dois workers **não** reclamam o mesmo
  item; `RETURNING` devolve `(id, lease_version)` (encurtamento não é neutro: um só ganha).
- O worker guarda `lease_version` e usa-o em TODAS as transições subsequentes.

### Recuperação de `processing` vencido (sweeper)

```sql
-- só reseta leases VENCIDOS (TTL por relógio) e NÃO do worker ativo
UPDATE editorial_items
SET review_state='pending', worker_id=NULL, leased_at=NULL,
    lease_version=lease_version+1
WHERE review_state='processing'
  AND leased_at < :cutoff                -- agora - lease_seconds
  AND (worker_id IS NULL OR worker_id != :exclude_worker)
RETURNING id;
```

- `cutoff = now - lease_seconds`. Um `processing` **vivo** (lease não vencido) **não** é tocado.
- O `lease_version` incrementado no recovery **invalida** o token antigo → se o worker
  original (achando que ainda é dono) tentar concluir, a transição falha (`not_owned`).
- Lease/heartbeat: o worker renova `leased_at` antes de cada passo longo (fetch/visão),
  via `corpus_renew_lease`-equivalente. TTL configurável (ex.: `EDITORIAL_LEASE_SECONDS`).

---

## 3. Transições permitidas e quem pode executá-las

| Transitão                     | Executor        | Guarda |
|-------------------------------|-----------------|--------|
| `pending → processing`        | worker (claim)  | atômico (BEGIN IMMEDIATE), fencing `lease_version+1` |
| `processing → ready`          | worker          | `owns_lease(id, worker_id, lease_version)` |
| `processing → awaiting_human` | worker          | `owns_lease(...)` |
| `processing → blocked`        | worker          | `owns_lease(...)` |
| `processing → pending`        | sweeper         | **só** lease vencido + `worker_id != exclude_worker` (não precisa owns_lease; incrementa token p/ invalidar) |
| `ready → published`           | cron publish-ready | separado: só toca `published` (não mexe no `review_state`) |
| `awaiting_human → pending`    | humano (retry)  | permissão `editorial.review`/admin |
| `awaiting_human → discarded`  | humano          | permissão `editorial.review`/admin |
| `blocked → pending`           | humano (unblock+retry) | permissão `editorial.review`/admin |
| `blocked → discarded`         | humano          | permissão `editorial.review`/admin |

Regras:
- **worker** SÓ transita de `processing` e precisa do `lease_version` correto
  (`owns_lease`). Qualquer transição com token defasado → `not_owned`, nada muda.
- **humano** transita de `awaiting_human`/`blocked` (estados não-processionados) e é
  sujeito a autorização (permissão, não só botão escondido — enforced server-side).
- **cron publish-ready** só marca `published`; nunca re-enfileira.
- Estados terminais (`published`/`discarded`) não re-entram na fila.

---

## 4. Predicado de seleção (só `pending`)

```sql
SELECT id FROM editorial_items
WHERE review_state = 'pending'
ORDER BY priority DESC, created_at ASC
LIMIT :limit;
```

- NUNCA inclui `processing/ready/awaiting_human/blocked`. Portanto um post já
  processado **não** volta, mesmo que o `status` "antigo" siga como era.
- Quota/prioridade aplicada no chamador (ex.: `--limit`), mas a seleção em si é exata.
- Idempotência de re-run: após o claim, os itens são `processing`/`ready` → o próximo
  run pega os **próximos** `pending`, nunca os já tratados.

---

## 5. Migração / backfill dos itens existentes

```sql
-- 1) colunas novas
ALTER TABLE editorial_items ADD COLUMN review_state TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE editorial_items ADD COLUMN published TEXT;
ALTER TABLE editorial_items ADD COLUMN worker_id TEXT;
ALTER TABLE editorial_items ADD COLUMN leased_at TEXT;
ALTER TABLE editorial_items ADD COLUMN lease_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE editorial_items ADD COLUMN handled_at TEXT;

-- 2) backfill a partir do veredito já conhecido (lado-canal: manifestos/queue --compact)
UPDATE editorial_items SET review_state = CASE
    WHEN :ready_verdict_condition   THEN 'ready'          -- ex.: já consta como READY
    WHEN :awaiting_condition        THEN 'awaiting_human' -- ex.: precisa de retry/discard
    WHEN :blocked_condition         THEN 'blocked'
    WHEN review_state = 'processing' THEN 'pending'       -- órfãos -> volta pra fila
    ELSE 'pending'
END;
```

- Idempotente: re-rodar não muda `review_state` já correto (CASE determinístico).
- Deve rodar dentro de uma transação, com checagem de contagem (`SELECT review_state, COUNT(*)...`)
  antes/depois; e um **backup** do SQLite antes da migração (já é requisito do repo).
- Os itens hoje READY/awaiting_human/blocked saem do `pending` → **deixam de ser
  re-selecionados imediatamente**, que é exatamente o bug reportado.

---

## 6. Testes exigidos

| Caso | Cenário | Asserção |
|------|---------|----------|
| **Reexecução** | item `ready`/`awaiting_human`/`blocked` | o predicado de seleção NÃO o devolve; pós-reset humano (`→pending`) volta a devolver |
| **Concorrência** | 2 workers claimam o mesmo batch (2 conexões) | só 1 vence cada claim (BEGIN IMMEDIATE + RETURNING); o perdedor recebe `[]`/`not_owned`; nenhum `processing` duplicado |
| **Falha no meio** | worker claima (`processing`) e morre; lease vence | sweeper reseta só os `processing` com `leased_at < cutoff` e `worker_id != exclude`; o item volta a `pending` e é re-selecionado; um `processing` **vivo** NÃO é tocado |
| **Fencing** | worker com token defasado tenta concluir depois do recovery | transição → `not_owned`; o `review_state` não muda; nada gravado |
| **Relógio (TTL)** | com `lease_seconds`, transição após expirar por clock | rejeitada (`not_owned`) mesmo sem nenhum sweeper; sem `lease_seconds`, só o sweeper recupera (serializável) |
| **Backfill idempotente** | re-rodar a migração | `review_state` inalterado; contagens conferem |
| **Publish desacoplado** | item `ready` marcado `published` pelo cron | `review_state` continua `ready`; não re-enfileira |

Infra: relógio injetável nos testes (para TTL determinístico); 2 conexões SQLite
(`check_same_thread`/threads) para concorrência; `httpx.MockTransport`/stub dos
provedores para o worker sem rede.

---

## Resumo de implementação (para o repo do agente editor)
1. Adicionar `review_state/published/worker_id/leased_at/lease_version/handled_at`.
2. `claim_pending(limit, worker_id)` atômico (BEGIN IMMEDIATE + RETURNING) devolvendo o fencing token.
3. `owns_lease(id, worker_id, lease_version)` em toda transição de `processing`.
4. `recover_expired(ttl_seconds, exclude_worker)` resetando `processing` vencido (incrementa token).
5. Predicado de seleção = `review_state='pending'`.
6. Transições com guardas por executor (worker/humano/cron) + autorização server-side.
7. Migração/backfill idempotente com backup.
8. Testes da tabela §6.
