# Domain Components

## AttentionSummary

Purpose: summarize only what needs human attention.

Props conceptually:
- decisionsPending
- criticalChanges
- failedSources
- measurementsReady

Do not include passive metrics.

## OpportunityRow

Use in Caixa de trabalho.

Required content:
- score/priority
- concise title
- category/action class
- one-line reason
- key evidence metrics
- age/last update
- status

Entire row opens detail. Keep destructive decisions out of the row unless batch mode is active.

## OpportunityDrawer

Use a right drawer so the list remains visible.

Sections:
1. title + score + action class
2. why it matters
3. evidence
4. impact estimate with caveats
5. recommendation
6. affected pages / related content
7. human decision bar

Tabs allowed: Overview, Evidence, Queries, Pages, History.

## EvidenceBlock

Show source, window, metrics, freshness, limitations. Missing sources must say missing/partial, never zero.

## HumanDecisionBar

Sticky bottom action area.

Typical actions:
- Reject
- Snooze
- Approve

For Safe Fix:
- Cancel
- Preview changes
- Execute approved fix

Keep primary action rightmost.

## AgentRunRow

Required:
- agent name
- run purpose
- outcome
- started/finished or duration
- important output count
- trigger

Do not show raw logs inline.

## AgentRunTimeline

Show stages in execution order with status and duration. On failure, preserve successful stages and mark skipped/blocked stages distinctly.

## BeforeAfterDiff

Use side-by-side on desktop and stacked on mobile. Highlight changed fragments, not entire text blocks. Always identify source action and timestamp.

## SourceHealthRow

Required:
- source name
- availability status
- last data window/sync
- coverage/rows if meaningful
- limitation or failure message
- reconnect/retry action when applicable

## EditorialCard

Keep cards compact. Required:
- working title
- type
- score/priority if available
- intent or cluster
- owner when assigned
- status

Do not put full briefs inside kanban cards.

## EmptyState

Explain why the area is empty and provide one next action. Avoid celebratory copy when absence may be due to missing data.

## ErrorState

Explain:
1. what failed;
2. what this affects;
3. what remains valid;
4. the next recovery action.

Raw exception text is secondary.
