# Frontend Architecture

## Target topology

```text
Next.js UI
  -> feature modules
  -> domain query/mutation hooks
  -> typed API client
  -> FastAPI/application API
  -> Python application services
  -> SQLite / GSC / GA4 / WordPress / CrUX / Hermes
```

The browser is not an SEO rules engine. It is an operational client.

## Suggested tree

```text
frontend/
  src/
    app/
      layout.tsx
      (dashboard)/
        layout.tsx
        today/page.tsx
        work/page.tsx
        pages/page.tsx
        pages/[id]/page.tsx
        technical/page.tsx
        editorial/page.tsx
        agents/page.tsx
        agents/runs/[runId]/page.tsx
        experiments/page.tsx
        integrations/page.tsx
        activity/page.tsx
    features/
      today/
      workbox/
      opportunities/
      pages/
      technical/
      editorial/
      agents/
      experiments/
      integrations/
      activity/
    design-system/
      button/
      badge/
      card/
      drawer/
      dialog/
      table/
      tabs/
      feedback/
      tokens/
    api/
      client.ts
      generated/
      opportunities.ts
      agents.ts
      pages.ts
      technical.ts
      editorial.ts
      integrations.ts
    lib/
      query-client.ts
      format.ts
      dates.ts
      permissions.ts
    hooks/
    types/
```

## Dependency direction

Allowed:

`app -> features -> api/lib -> generated contracts`

`features -> design-system`

`features -> shared domain components`

Avoid:

- design-system importing feature code;
- presentational components importing API clients;
- one feature importing another feature's private internals;
- Next.js importing SQLite or backend Python artifacts directly.

## Server vs client components

Use Server Components for shell, static metadata, and initial data where it materially improves the page. Use Client Components for drawers, filters, mutations, live polling, editable forms, tables with client interaction, and charts requiring browser behavior.

Do not turn the whole dashboard into a client component because one child needs interactivity.

## Data flow

```text
route/search params
       -> feature container
       -> query hook
       -> API module
       -> backend
       -> typed DTO
       -> domain/view model
       -> presentational component
```

Mutations:

```text
human action
  -> confirmation/preview if needed
  -> mutation hook
  -> API
  -> success/error result
  -> targeted query invalidation
  -> visible post-action state
```

## App shell

Use one persistent shell:

- sidebar: compact domain navigation;
- top bar: current site/workspace, search, run-analysis action, theme/user controls;
- content: max-width only where readability benefits; operational tables may use full width;
- right drawer: evidence/detail while preserving the work queue context.

## Performance defaults

- paginate or virtualize large page datasets;
- debounce free-text server searches;
- use query stale times intentionally per data freshness;
- avoid fetching charts before the parent section is visible when data is expensive;
- render concise summaries before large evidence datasets.
