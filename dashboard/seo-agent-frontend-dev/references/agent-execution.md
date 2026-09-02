# Agent Execution UX and Technical Pattern

## Run model

A run should expose at least:

```ts
type RunStatus = 'queued' | 'running' | 'success' | 'partial' | 'failed' | 'cancelled'

type AgentRun = {
  id: string
  agent: string
  status: RunStatus
  trigger: 'schedule' | 'manual' | 'system'
  mode: string
  startedAt?: string
  finishedAt?: string
  durationMs?: number
  summary: RunSummary
  stages: RunStage[]
  comparison?: RunComparison
  errors?: RunError[]
}
```

Adapt to actual backend contracts rather than forcing this exact type.

## Run list hierarchy

1. currently running;
2. failed/partial requiring attention;
3. latest successful;
4. historical runs.

A row should show agent, purpose, status, start time, duration, key output counts, and a clear open-detail action.

## Detail hierarchy

Summary first, technical log last.

Show:

- success/partial/failure outcome;
- human-readable run purpose;
- run metadata;
- counts: URLs, findings, opportunities, suggested safe fixes, executed changes;
- delta versus prior comparable run;
- stage timeline;
- outputs grouped by product concept;
- errors with affected scope;
- raw logs in a separate tab or disclosure.

## Polling MVP

While the run status is `queued` or `running`, refetch every 2-5 seconds. Stop polling on terminal states. Avoid polling all historical runs individually; refresh the run list at a slower cadence if needed.

Pseudo-pattern:

```ts
useQuery({
  queryKey: runKeys.detail(id),
  queryFn: () => getRun(id),
  refetchInterval: query => {
    const status = query.state.data?.status
    return status === 'queued' || status === 'running' ? 3000 : false
  },
})
```

## SSE evolution

Add SSE when the backend can emit stable run/stage events. Use it for one-way progress updates. Keep REST GET endpoints as the source for recovery, deep links, and reconnect.

## Errors

Translate failure into:

1. what failed;
2. what data/result is affected;
3. what remains valid;
4. whether automatic retry is scheduled;
5. manual recovery action.

Example: `CrUX returned 429. Core Web Vitals were not refreshed; GSC, sitemap and technical checks remain valid.`

## Logs

Do not stream raw logs into the primary summary. Provide search/copy/download only in the log view. Mask secrets server-side; the browser should never receive credentials to redact.
