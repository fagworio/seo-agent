# ADR-0001: Frontend (Next.js + TypeScript)

## Status
Aceito (control plane em construção).

## Contexto
Precisamos de um painel de operações (control plane) para o SEO Agent, não de
outro mecanismo de SEO. O backend Python já detém a inteligência
(OpportunityFeedService, safe_fix, approval_required, editorial, medição,
integrações). O browser é o plano de controle humano, não um motor de regras.

## Decisão
- **Framework**: Next.js com App Router (TypeScript strict).
- **UI**: Tailwind CSS alimentado por CSS variables semânticas + primitivos
  shadcn/ui quando úteis.
- **Server state**: TanStack Query (nunca espelhar coleções em stores globais).
- **Tabelas grandes**: TanStack Table (server-side sorting/filtering/pagination).
- **Forms**: React Hook Form + Zod.
- **Charts**: Recharts, somente quando suportarem uma decisão.
- **Icons**: Lucide (set linear, 16–20px).
- **Estado de UI transitório** (drawer/sidebar/theme): local ou Zustand restrito.

## Consequências
- Frontend não duplica regras de SEO em React (fonte de verdade = Python).
- Não parsear CLI/Markdown em componentes; usar DTOs via camada de API tipada.
- Dark e light derivam do mesmo sistema de tokens semânticos.
