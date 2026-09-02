# Screens and Human Workflows

## 1. Hoje

Primary question: **What changed, and what needs me now?**

Hierarchy:
1. attention summary
2. recent agent activity
3. top opportunities
4. organic performance trend
5. site health summary
6. onboarding/next step only when relevant

Do not show more than 4 top-level KPI cards. Prefer change since previous period/run over static totals.

Primary actions:
- open work queue
- open failed execution
- run analysis now

## 2. Caixa de trabalho

Primary question: **Which decision should I process next?**

Default sort: priority/score descending, then recency.

Filters:
- all
- requires approval
- safe fix
- observe
- technical
- editorial
- responsible
- status

Interaction:
- click row -> right drawer
- approve/reject/snooze -> immediately advance to next item when safe
- retain filter/list scroll position

Batch actions only for homogeneous, low-risk items.

## 3. Opportunity detail

Primary question: **Do I trust this recommendation enough to act?**

Required:
- recommendation
- evidence and freshness
- expected impact
- risk
- affected URLs
- action class
- agent/source that generated it
- decision controls

Never lead with an AI explanation before evidence.

## 4. Agentes & Execucoes

Primary question: **What did automation do, and did it work?**

List view:
- recent runs
- active runs
- failed/partial runs visible first

Detail view:
- run summary
- delta vs prior comparable run
- stages
- outputs
- changes
- errors
- logs

Tabs: Summary, Stages, Results, Changes, Logs.

Manual run dialog asks human intent, not CLI command flags:
- normal cycle
- technical SEO
- sitemap/indexing
- opportunities
- content
- specific URL

Then mode:
- analyze only
- generate safe fixes

## 5. Page Explorer

Primary question: **What is the SEO state and history of this URL?**

List columns:
- page/title
- health/status
- clicks/impressions trend or traffic change
- position
- primary opportunity
- index state

Page tabs:
- Summary
- Search
- Content
- Links
- Technical
- History

Summary starts with attention items, not raw metadata.

History is a narrative timeline connecting detection -> approval -> implementation -> recrawl -> measurement.

## 6. Editorial

Primary question: **Which content decision should move forward?**

Use a pipeline/board with limited visible columns:
- Discovery
- Review
- Approved
- Published
- Measuring

Rejected/snoozed/expired are filter states, not permanent main columns.

Opening a card shows Content Brief, evidence, existing-content comparison, duplication risk, internal links, and actions.

## 7. SEO Tecnico

Primary question: **What is broken, and what can safely be corrected?**

Separate views:
- Problems
- Available corrections

Problems organize by severity/rule. Corrections organize by action class and affected scope.

Safe Fix workflow:
`finding -> preview -> approve -> execute -> verify -> rollback if needed`

## 8. Experimentos

Primary question: **Did the intervention improve the target metric?**

Show:
- hypothesis
- intervention type
- implemented date
- baseline window
- measurement window
- before/after
- confidence/limitations
- state: awaiting data, measuring, positive, neutral, negative

Use "observed change" language unless causal inference is justified.

## 9. Data Sources

Primary question: **Can I trust the data feeding recommendations?**

Show WordPress, sitemap, corpus, GSC, GA4, CrUX, external providers.

Every source exposes availability, freshness, coverage, limitations, and recovery action.

## 10. Global History

Primary question: **Who or what changed the system?**

Use one audit timeline mixing:
- human approvals/rejections
- agent run completion
- executed fixes
- rollbacks
- data source failures/recovery
- measurements completed

Filter by actor, entity, action type, and time.
