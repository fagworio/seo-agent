# ADR-0005: Server state com TanStack Query

## Status
Aceito.

## Contexto
Dados de oportunidades, páginas, runs, findings, métricas e integrações são
estado de servidor. Espelhá-los em stores globais gera dessincronização.

## Decisão
- **Server state** → TanStack Query (query keys estáveis por factory).
- **URL state** → search params (filtros, sort, tab compartilhável, paginação).
- **UI state** → estado local/context/Zustand (drawer, sidebar, tema, paleta).
- Retries: GET seguro com backoff; mutação não-idempotente só se o backend for
  idempotente; 401/403 não retry; 429 respeitar meta.
- Dados parciais retornam resposta de sucesso com metadado de `data-status`
  quando o backend distingue partial de failed.

## Consequências
- Caches invalidados por alvo, não com refresh total.
- Nenhuma coleção de servidor fora dos stores do TanStack Query.
- Proveniência e frescor expostos onde afetam confiança.
