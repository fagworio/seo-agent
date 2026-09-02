# Screen Contracts

## Today

Primary question: **What changed and what needs me now?**

Order:
1. attention summary;
2. recent agent executions, failures first;
3. top opportunities;
4. organic trend;
5. health summary;
6. onboarding/next step only when needed.

Maximum four top-level KPI cards. Prefer deltas over static totals.

## Workbox

Primary question: **Which decision should I process next?**

Use dense rows. Default sort by score/priority then recency. Open detail in a right drawer. Preserve filters and scroll when moving to the next item.

Filters: all, approval, safe fix, observe, technical, editorial, owner, status.

Batch actions only for homogeneous low-risk work.

## Opportunity detail

Primary question: **Is there enough evidence to approve this recommendation?**

Order:
1. recommendation title and action class;
2. score/priority;
3. evidence and freshness;
4. expected impact;
5. affected pages;
6. risk/reversibility;
7. recommendation details;
8. decision controls.

Never lead with AI prose before evidence.

## Agents & Runs

Primary question: **What did automation do and did it work?**

List: running, failed/partial, then recent successful runs.

Run detail tabs: Summary, Stages, Results, Changes, Logs.

Manual run dialog asks intent: normal cycle, technical, sitemap/indexing, opportunities, content, specific URL. Then mode: analyze only or generate safe fixes. Hide CLI flags.

## Pages

Primary question: **What is the SEO state and history of this URL?**

Explorer columns: page, health, traffic/search trend, position, primary opportunity, index state.

Page workspace tabs: Summary, Search, Content, Links, Technical, History.

Summary begins with attention items. History is a narrative timeline connecting detection, decision, implementation, recrawl, and measurement.

## Technical SEO

Primary question: **What is broken, and which corrections are safe to execute?**

Separate `Problems` from `Corrections available`. Findings must expose rule, severity, affected URLs, evidence, and action class. Safe fixes require preview before execute.

## Editorial

Primary question: **Which content decision should move forward?**

Primary board: Proposed/Review, Approved, Published, Measuring. Keep cards compact; full brief opens separately. Distinguish expand-existing, supporting-post, hub-page, and cannibalization-review.

## Experiments

Primary question: **What happened after an intervention?**

Show intervention, baseline, implementation date, waiting period, current metrics, delta, measurement quality, and limitations. Use language such as observed improvement/correlation; do not claim causal certainty without evidence.

## Integrations

Primary question: **Can I trust the data feeding the product?**

For each source show configured/availability state, last window/sync, coverage/rows when meaningful, limitations, and recovery action. Missing data is not zero.
