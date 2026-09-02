# Frontend Implementation Roadmap

## F0 - Foundation

Deliver:
- Next.js/TypeScript project or integrate with existing frontend;
- semantic design tokens and dark/light theme;
- dashboard shell and navigation;
- Query provider and typed API client boundary;
- loading/error/empty primitives;
- lint/typecheck/test/build scripts.

Accept when both themes render the shell consistently and a mocked/real health endpoint can be consumed through the API layer.

## F1 - Today

Deliver attention summary, recent agent runs, top opportunities, a restrained organic trend, health summary, and contextual next step.

Accept when the user can identify what needs attention and open the relevant queue/run in under two interactions.

## F2 - Workbox

Deliver unified opportunity list, filters in URL, right-side detail drawer, evidence, decision controls, approve/reject/snooze, and next-item progression.

Accept when a decision can be processed without losing list position/filter context.

## F3 - Agents & Runs

Deliver run list, detail summary, stages, outputs, changes, errors, logs, manual-run intent dialog, and live polling.

Accept when a failed/partial run communicates impact without reading raw logs.

## F4 - Pages

Deliver Page Explorer plus per-URL workspace with Summary/Search/Content/Links/Technical/History.

Accept when the user can trace an opportunity or change to historical evidence for one URL.

## F5 - Technical SEO

Deliver findings, rule groupings, affected pages, separate safe-fix queue, preview, execution, and verification state.

Accept when no write can be triggered without scope/risk/preview context.

## F6 - Editorial

Deliver review board, content brief detail, approval/rejection/snooze, publish confirmation, and measuring state.

Accept when suggestions remain human-controlled from proposal through measurement.

## F7 - Experiments

Deliver intervention list/detail, baseline, implementation marker, waiting period, current metrics, delta, and limitations.

Accept when the UI distinguishes observed movement from causal certainty.
