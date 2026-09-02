# SEO Agent Backend Map for Frontend Work

## Re-inspect before implementation

This reference captures the architecture observed when the skill was created. The repository changes over time; inspect the current default branch before coding.

At creation time, the repository root was primarily the Python `hermes_seo_agent` application and did not contain a dedicated Next.js frontend package.

## Existing concepts to preserve

### Unified opportunity read model

`hermes_seo_agent/services/opportunity.py` defines an `OpportunityFeedService` and `OpportunityDTO` projecting multiple sources into one human-facing feed. Sources include checklist, content brief, editorial backlog, and interlink suggestions.

Use this concept for the Workbox. Do not make the frontend query separate SQLite tables to recreate the feed.

Useful DTO concepts:

- id/source/type/status;
- url/title;
- score and score breakdown;
- evidence;
- recommendation;
- acceptance criteria;
- GSC metrics;
- GA4 metrics;
- measurement state;
- timestamps.

### Integration health

`hermes_seo_agent/services/integration_status.py` models source health with canonical data states such as available, partial, missing, and invalid. It deliberately prevents missing/unconfigured data from appearing as numerical zero.

Use this for Integrations and data-quality callouts across the product.

### Safety model

The backend separates observe, safe_fix, and approval_required behavior. Deletes are blocked by construction; write actions have dry-run/idempotency/audit/rollback concepts.

The frontend must visualize these guarantees rather than invent new write semantics.

### Page history

The backend persists page snapshots and links changes to action fingerprints. This supports the page History timeline and experiment before/after views.

### Editorial workflow

Editorial intelligence produces reviewable briefs/backlog/interlink suggestions and tracks human decisions. The UI should represent this workflow; it must not turn suggestions into automatic publishing.

## API layer recommendation

Add a Python application/API layer in front of these services, preferably FastAPI, instead of allowing Next.js to read SQLite directly. Reuse service methods so CLI, Hermes, and UI share business logic.

## Backend-first questions before a frontend workaround

If the frontend lacks a field needed to explain a decision, ask whether the API/read model should expose it before deriving it client-side. Typical examples:

- score breakdown;
- source freshness;
- action risk;
- affected URLs;
- rollback availability;
- run comparison;
- measurement limitations.
