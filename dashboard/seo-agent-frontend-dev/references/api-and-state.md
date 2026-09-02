# API and State Model

## API principle

Expose product concepts, not CLI commands. A route may internally invoke existing services, but the UI contract should describe the human operation.

## Recommended API areas

```text
GET  /api/dashboard/today
GET  /api/opportunities
GET  /api/opportunities/{id}
POST /api/opportunities/{id}/approve
POST /api/opportunities/{id}/reject
POST /api/opportunities/{id}/snooze

GET  /api/pages
GET  /api/pages/{id}
GET  /api/pages/{id}/history

GET  /api/findings
GET  /api/actions/{id}/preview
POST /api/actions/{id}/execute

GET  /api/agents
GET  /api/runs
GET  /api/runs/{id}
POST /api/runs

GET  /api/editorial
POST /api/editorial/{id}/approve
POST /api/editorial/{id}/reject
POST /api/editorial/{id}/published

GET  /api/experiments
GET  /api/integrations
GET  /api/activity
```

These are design contracts, not permission to invent backend semantics. Inspect current services before implementing endpoints.

## Query keys

Keep stable factories instead of ad-hoc arrays:

```ts
export const opportunityKeys = {
  all: ['opportunities'] as const,
  list: (filters: OpportunityFilters) => [...opportunityKeys.all, 'list', filters] as const,
  detail: (id: string) => [...opportunityKeys.all, 'detail', id] as const,
}
```

Use the same pattern for pages, runs, findings, editorial, experiments, and integrations.

## Server state

Use TanStack Query for data returned by the API. Configure retries carefully:

- safe GET: normal retry with backoff;
- mutation: do not silently retry non-idempotent actions unless the backend contract supports idempotency;
- 401/403: do not retry;
- 429: respect retry metadata where available;
- partial data: return a successful response with data-status metadata when the backend can distinguish partial from failed.

## URL state

Persist shareable list state in search params:

- status
- priority
- source/type
- owner
- page
- sort
- search
- selected tab when useful

Opening a drawer may also use a URL id when deep linking is valuable, but preserve quick queue navigation.

## UI state

Keep transient state local unless multiple distant components require it. Candidate global UI state:

- sidebar collapsed state;
- theme;
- optional command-palette state.

Do not store opportunity/page/run arrays in Zustand.

## Generated contracts

Prefer OpenAPI generation. Generated code should live in `src/api/generated/`. Wrap generated clients with small domain API modules so feature code does not depend on generator internals.

## Mutations and optimistic UI

Default to pessimistic confirmation for approval, write, and execution actions. Optimistic updates are acceptable for low-consequence UI-only changes or clearly reversible metadata such as snoozing when backend semantics are stable.

After approval/execution, show the next lifecycle state rather than merely closing a toast.

## Freshness and provenance

DTOs that influence a decision should expose when relevant:

- `generated_at` / `updated_at`;
- source/agent;
- data window;
- `data_status`;
- limitations;
- evidence identifiers.

Do not infer fresh data from the time the browser loaded it.
