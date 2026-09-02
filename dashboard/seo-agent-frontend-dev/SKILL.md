---
name: seo-agent-frontend-dev
description: Implement, refactor, review, and extend the frontend of the fagworio/seo-agent product while preserving its human-first SEO operations workflow and design system. Use for Next.js/TypeScript frontend development, dashboard screens, reusable UI/domain components, API integration, agent execution monitoring, opportunity workflows, page workspaces, technical SEO flows, editorial boards, experiments, light/dark themes, accessibility, responsive behavior, or frontend architecture decisions for seo-agent. Inspect the current repository before coding and keep the Python backend as the source of SEO business logic.
---

# SEO Agent Frontend Development

## Objective

Implement the SEO Agent as an operational interface for humans supervising autonomous agents. Keep design, workflow clarity, safety, and evidence ahead of decorative dashboard work.

Preserve this product loop in every feature:

`Detectar -> Entender -> Decidir -> Executar -> Verificar -> Medir`

Treat the frontend as the human control plane. Keep SEO detection, scoring, safety policy, persistence, and measurement logic in the Python backend.

## Mandatory first step

Before changing code:

1. Inspect the current repository tree, package manifests, existing frontend directory, branch conventions, and relevant backend services.
2. Reuse existing architecture and components when they already satisfy the requirement.
3. If no frontend exists, scaffold only the minimum structure required by the requested milestone.
4. Identify the human task before choosing components.
5. Load the relevant references from this skill.

Use the GitHub connector when working against the user's repository content or when repository writes are requested. Do not guess repository state from this skill because the project evolves.

## Product rules that override implementation convenience

Always:

- show what needs attention before passive metrics;
- show evidence before consequential actions;
- distinguish agent work, human decisions, and system verification;
- preserve list context when opening details;
- expose action class, risk, scope, and rollback before writes;
- make partial or missing data explicit instead of rendering misleading zeroes;
- expose recent agent executions and failures as first-class product information;
- support dark and light themes from the same semantic token system;
- include loading, empty, partial, error, permission, and success states;
- keep raw logs behind progressive disclosure;
- make keyboard and responsive behavior part of completion criteria.

Never:

- reproduce Python SEO rules in React;
- parse CLI or Markdown output directly in UI components;
- expose CLI command names as the main navigation model;
- call backend APIs directly from arbitrary presentational components;
- hardcode theme colors in feature components;
- create one-off components when a reusable primitive or domain component fits;
- execute a write from a generic `Fix` button without preview and policy context;
- use charts that do not support a decision.

## Target frontend architecture

Prefer:

- Next.js with App Router
- TypeScript with strict mode
- Tailwind CSS backed by semantic CSS variables
- shadcn/ui-style accessible primitives where useful
- TanStack Query for server state
- TanStack Table for large URL/result datasets
- React Hook Form + Zod for forms
- Recharts for decision-supporting charts
- Lucide icons
- Zustand only for small cross-page UI state when URL state or React context is not a better fit

Read `references/frontend-architecture.md` before scaffolding or reorganizing the frontend.

## State ownership

Use three state classes:

1. **Server state** -> TanStack Query: opportunities, pages, runs, findings, metrics, integrations.
2. **URL state** -> search params: filters, sorting, selected tab when shareable, pagination.
3. **UI state** -> local state/context/Zustand: drawer visibility, sidebar state, transient UI preferences.

Do not mirror server collections into global client stores.

## API boundary

Use one typed API layer between features and FastAPI/backend endpoints.

Preferred flow:

`FastAPI OpenAPI -> generated TypeScript types/client -> domain query hooks -> feature components`

If generated types are not available yet, isolate temporary DTOs in the API layer and mark them for replacement. Never define the same backend contract independently inside multiple components.

Read `references/api-and-state.md` for endpoint shapes, query keys, mutation behavior, polling, and error handling.

## Feature structure

Organize by domain capability, not by generic file type alone:

- `today`
- `workbox`
- `opportunities`
- `pages`
- `technical`
- `editorial`
- `agents`
- `experiments`
- `integrations`
- `activity`

Keep reusable visual primitives separate from domain components.

Example distinction:

- `design-system/Button` knows nothing about SEO.
- `features/opportunities/ApproveOpportunityButton` knows the approval mutation and composes `Button`.

## Canonical workflow states

Use a shared human-readable lifecycle rather than feature-specific inventions:

`detected -> review_required -> approved -> executing -> implemented -> waiting_data -> measured -> completed`

Alternate/terminal states:

- `rejected`
- `snoozed`
- `expired`
- `failed`
- `reverted`

Map backend statuses to these labels in a view-model/adapter layer when necessary.

## Automation classes

Represent these consistently everywhere:

- `observe`
- `safe_fix`
- `approval_required`
- elevated `risk` when applicable

A Safe Fix is not permission to skip human context. Show preview, affected scope, reversibility, and policy gate before execution.

## Required app shell and routes

Use a single dashboard shell with persistent sidebar and top bar. Default product areas:

- `/today`
- `/work`
- `/pages`
- `/pages/[id]`
- `/editorial`
- `/technical`
- `/agents`
- `/agents/runs/[runId]`
- `/experiments`
- `/integrations`
- `/activity`
- `/settings`

Do not create a route for every backend command.

## Core domain components

Prefer composing these shared components:

- `AttentionSummary`
- `OpportunityRow`
- `OpportunityScore`
- `OpportunityDrawer`
- `EvidenceBlock`
- `ImpactSummary`
- `ActionClassBadge`
- `RiskBadge`
- `HumanDecisionBar`
- `AgentRunRow`
- `AgentRunStatus`
- `AgentRunSummary`
- `AgentRunTimeline`
- `ExecutionStage`
- `AgentErrorPanel`
- `BeforeAfterDiff`
- `PageHealthSummary`
- `PageMetricCard`
- `SearchQueryTable`
- `TechnicalFindingRow`
- `SafeFixPreview`
- `EditorialCard`
- `EditorialBoard`
- `MeasurementState`
- `SourceHealthRow`
- `EmptyState`
- `ErrorState`

Read `references/screen-contracts.md` before implementing a product screen.

## Agent execution implementation

Treat agent observability as a dedicated feature, not a log viewer.

For every run show:

1. current/outcome status;
2. plain-language summary;
3. delta versus the prior comparable run;
4. stages and durations;
5. findings/opportunities/actions created;
6. partial data and failures with impact explanation;
7. raw logs only on demand.

For MVP live progress, prefer polling a run endpoint every 2-5 seconds while `running`, then stop automatically. Prefer SSE later when server-to-client event streaming becomes worthwhile. Do not require WebSockets for the first implementation.

Read `references/agent-execution.md` when touching agent screens, polling, run states, stages, errors, or logs.

## Design implementation

Follow `references/design-system.md` and `references/light-theme.md` strictly.

Use semantic tokens such as:

- `background`
- `surface`
- `surface-raised`
- `border`
- `foreground`
- `foreground-muted`
- `primary`
- `success`
- `warning`
- `danger`
- `info`

Do not ship arbitrary theme literals such as `bg-[#09090b]` inside feature code.

Use `assets/dark-design-reference.png` and `assets/light-design-reference.png` for visual direction, not pixel-perfect copying.

## Screen implementation contract

For every new or materially changed screen, determine before coding:

1. **Purpose** — what job this screen performs.
2. **Primary user question** — what the user should answer in under 5-10 seconds.
3. **Hierarchy** — what appears first, second, and only on demand.
4. **Components** — reuse before create.
5. **Actions** — who can perform each action and what permission/risk applies.
6. **States** — loading, empty, partial, error, success, permission.
7. **Dark/light** — identical hierarchy and behavior in both themes.
8. **Responsive** — desktop, tablet, mobile degradation strategy.
9. **Acceptance criteria** — observable behavior, not visual adjectives.

## Development workflow

For an implementation request:

1. Inspect relevant repository files and current API contracts.
2. State the feature boundary and affected files briefly.
3. Map the request to the human workflow and canonical states.
4. Reuse design-system and domain components.
5. Implement the smallest complete vertical slice.
6. Keep API calls in typed client/hooks, not presentation components.
7. Add loading/empty/error/partial-data behavior.
8. Add dark/light and responsive behavior.
9. Add or update tests appropriate to the changed logic.
10. Run deterministic validation.
11. Review against `references/quality-gates.md` and `references/ui-review-checklist.md`.
12. Summarize changed files, behavior, checks run, and remaining limitations.

Do not stop at a written proposal when the user asked to implement code.

## Vertical-slice priority

When bootstrapping the frontend, implement in this order unless the user requests otherwise:

1. foundation: app shell, semantic tokens, API client, Query provider;
2. Today;
3. Workbox + OpportunityDrawer + human decisions;
4. Agents & Runs;
5. Pages + page workspace;
6. Technical SEO + Safe Fix preview;
7. Editorial;
8. Experiments/measurement;
9. deeper integrations and reports.

Do not build a graph-heavy analytics dashboard before the decision workflows exist.

Read `references/implementation-roadmap.md` for milestone acceptance criteria.

## Repository/backend alignment

The backend already contains domain services intended to support an API-facing UI, including a unified opportunity read model and integration health model. Do not bypass these by querying SQLite directly from Next.js.

Read `references/project-backend-map.md` before defining new API DTOs or endpoints.

## Code quality rules

- Use strict TypeScript and avoid `any` except at isolated boundary code with justification.
- Keep components small enough to reveal purpose; extract meaningful domain components, not arbitrary fragments.
- Prefer server components for static shell/data that benefits from SSR and client components only where interaction requires them.
- Keep mutations explicit and invalidate/refetch only the affected query keys.
- Put shareable filters in URL search params.
- Use accessible labels for icon-only buttons.
- Preserve focus when drawers/dialogs close.
- Use tabular numerals for SEO metrics.
- Format dates/numbers through shared utilities and locale-aware APIs.
- Keep data provenance and freshness visible where it affects trust.
- Add a reason before disabling an action; do not silently disable critical controls.

## Validation

Run the project's own scripts first when they exist. Then use bundled checks when useful:

- `scripts/validate_frontend.sh <frontend-dir>` — run available lint/typecheck/test/build scripts without inventing missing commands.
- `scripts/ui_guardrails.py <frontend-dir>` — warn about hardcoded hex colors, direct `fetch()` inside component files, and other design-boundary smells.

Treat guardrail output as review input, not an infallible compiler.

## Completion criteria

A frontend task is complete only when:

- the requested workflow works end-to-end at the UI boundary;
- the human can tell what happened, why, and what to do next;
- agent versus human responsibility is explicit;
- server/business logic is not duplicated in React;
- dark and light themes work;
- responsive and keyboard behavior is handled;
- error/empty/partial/loading states exist;
- relevant tests and validation pass or failures are explicitly reported.
