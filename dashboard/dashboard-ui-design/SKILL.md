---
name: seo-agent-ui-design
description: Design and review the SEO Agent dashboard UI/UX with a strict human-first workflow, reusable components, consistent dark/light themes, and agent transparency. Use when creating, modifying, reviewing, or implementing frontend screens, components, flows, layouts, dashboards, cards, tables, drawers, status states, execution monitoring, editorial workflows, technical SEO workflows, or design-system decisions for the seo-agent project.
---

# SEO Agent UI Design

## Purpose

Treat design as a product constraint, not decoration. Build every interface around the SEO Agent operating model: agents detect and analyze, humans understand and decide, the system executes safely, and results are measured.

Never expose CLI concepts as the primary navigation model. Translate internal commands into human tasks and outcomes.

## Required product model

Use this mental model for all screens:

`Detectar -> Entender -> Decidir -> Executar -> Verificar -> Medir`

Distinguish three actors at all times:

- **Agent**: collects, analyzes, detects, recommends, executes approved safe actions.
- **Human**: reviews evidence, approves, rejects, snoozes, edits, or confirms manual work.
- **System**: persists state, runs checks, verifies execution, measures impact, and preserves audit history.

Do not collapse these roles into a generic "Fix" action.

## Mandatory workflow priority

When designing or reviewing a screen, prioritize in this order:

1. What needs the user's attention now?
2. Why does it matter?
3. What evidence supports it?
4. What is recommended?
5. Who can act: agent, human, or both?
6. What is the risk and reversibility?
7. What happens after action?
8. How will the result be measured?

If a screen does not answer the relevant subset of these questions, revise it before polishing visuals.

## Navigation model

Use the following information architecture unless a feature clearly requires another placement:

- **Hoje** — current priorities, changes, recent agents, health, outcomes.
- **Caixa de trabalho** — unified human decision queue.
- **Paginas** — URL explorer and page history.
- **Editorial** — briefs, opportunities, content pipeline, interlinks.
- **SEO Tecnico** — findings and safe corrections.
- **Agentes & Execucoes** — agent runs, stages, failures, schedules, logs.
- **Experimentos** — before/after and measured interventions.
- **Fontes de dados** — WordPress, sitemap, corpus, GSC, GA4, CrUX, external sources.
- **Historico** — immutable human + agent audit timeline.
- **Configuracoes** — runtime and UI settings.

Keep the sidebar compact. Use icons + short labels. Avoid more than two navigation levels.

## Canonical item lifecycle

Represent actionable work using the shared lifecycle:

`detectado -> revisao -> aprovado -> em_execucao -> implementado -> aguardando_dados -> medido -> concluido`

Allow terminal or alternate branches:

- `rejeitado`
- `adiado`
- `expirado`
- `falhou`
- `revertido`

Never show implementation-specific storage status if a clearer human label exists.

## Action classes

Always expose the action class visually and semantically:

- **Observe** — information only; no action required.
- **Safe Fix** — low-risk, reversible action that the agent can execute after the required policy gate.
- **Requer aprovacao** — human decision required before execution.
- **Risco** — elevated risk, destructive consequence, or broad blast radius.

For all write actions, show preview, affected scope, risk, and rollback availability before confirmation.

## Visual direction

Use a restrained Linear-inspired product UI: dense enough for operators, but quiet, ordered, and task-focused.

Do:

- use large negative space around primary decisions;
- use compact rows for repeated operational data;
- use drawers for detail without losing list context;
- use one accent color for primary interaction;
- reserve semantic colors for state;
- use charts only when they support a decision;
- keep critical information visible without scrolling when practical;
- make light and dark themes equally first-class.

Do not:

- fill dashboards with decorative KPI cards;
- use multiple competing accent colors;
- expose raw logs before a human-readable summary;
- rely on color alone to communicate status;
- put approve/reject actions far from the evidence they affect;
- force users to understand agent command names.

## Theme requirements

Support both dark and light modes from the same semantic token model. Never hardcode component colors directly.

Read `references/design-system.md` for tokens, type scale, spacing, borders, shadows, density, and theme mappings.

Use `assets/dark-design-reference.png` and `assets/light-design-reference.png` as visual references, not pixel-perfect specifications.

## Component rules

Build interfaces from reusable primitives and domain components. Read `references/components.md` before creating or modifying UI code.

Core domain components include:

- `AttentionSummary`
- `OpportunityRow`
- `OpportunityDrawer`
- `EvidenceBlock`
- `ImpactSummary`
- `ActionClassBadge`
- `RiskBadge`
- `AgentRunRow`
- `AgentRunTimeline`
- `ExecutionStage`
- `BeforeAfterDiff`
- `PageHealthSummary`
- `SourceHealthRow`
- `EditorialCard`
- `HumanDecisionBar`
- `MeasurementState`
- `EmptyState`
- `ErrorState`

Prefer composition over one-off page components.

## Screen workflows

Read `references/screens-and-flows.md` whenever creating or changing a product screen. Follow the screen purpose, primary user question, hierarchy, and allowed actions defined there.

The most important screens are:

1. **Hoje** — orient the user in under 10 seconds.
2. **Caixa de trabalho** — process decisions rapidly without losing context.
3. **Detalhe da oportunidade** — explain evidence and recommendation before action.
4. **Agentes & Execucoes** — explain what agents did, what changed, and what failed.
5. **Pagina** — tell the full SEO story of one URL.
6. **Editorial** — manage discovery through measurement.
7. **SEO Tecnico** — separate diagnosis from executable corrections.
8. **Experimentos** — measure interventions without overstating causality.

## Agent execution UX

Treat agent observability as a first-class product area.

Every execution detail must show, in this order:

1. outcome: success, partial, failed, running;
2. human-readable summary;
3. changes versus prior comparable execution;
4. stages and durations;
5. artifacts created: findings, opportunities, safe fixes, measurements;
6. errors and their impact;
7. raw logs only on demand.

For failed integrations, explain what data is missing and which parts of the run remain valid.

## Light dashboard requirement

When implementing the light theme:

- use warm/neutral white page backgrounds, not pure white everywhere;
- use subtle gray surfaces and low-contrast borders;
- preserve the purple/indigo primary accent;
- keep semantic success/warning/error colors readable but restrained;
- use shadow sparingly; prefer border + surface separation;
- maintain the same information hierarchy and component dimensions as dark mode;
- test charts, badges, disabled states, hover states, focus rings, and dividers independently in light mode.

See `references/light-theme.md` for exact mapping and examples.

## Implementation workflow

When asked to create or change frontend code:

1. Identify the screen and human task.
2. Map the task to a canonical workflow state.
3. Reuse existing domain components before introducing a new one.
4. Use semantic design tokens only.
5. Design both dark and light states before considering the component complete.
6. Include loading, empty, partial-data, error, and permission states.
7. Preserve human decision context when opening detail views.
8. Validate keyboard navigation, focus order, contrast, and destructive confirmations.
9. Check desktop first, then tablet and mobile behavior.
10. Review against `references/review-checklist.md` before finalizing.

## Frontend architecture guidance

Prefer:

- Next.js + TypeScript
- Tailwind CSS or CSS variables backed by semantic tokens
- shadcn/ui-style primitives where useful
- TanStack Table for large URL/result tables
- Recharts or equivalent for decision-supporting charts
- API-backed domain models instead of UI parsing CLI output

Keep backend terms behind adapter/view-model layers. UI components should receive human-readable domain DTOs.

## Output standard

When proposing a new screen or component, provide:

1. **Purpose**
2. **Primary user question**
3. **Hierarchy**
4. **Components used**
5. **Actions and permissions**
6. **States**
7. **Dark/light behavior**
8. **Responsive behavior**
9. **Acceptance criteria**

When producing code, implement the design instead of only describing it.
