# Frontend Quality Gates

## Functional

- Requested workflow completes without relying on hidden CLI steps.
- Mutations surface success/failure and the new lifecycle state.
- Relevant query caches refresh correctly.
- Deep links and browser back/forward preserve meaningful state.

## Design system

- No feature-specific hardcoded theme colors.
- Semantic token usage works in dark and light modes.
- Shared spacing, radius, typography, badges, buttons, drawers, and tables are reused.
- Repeated operational data uses rows/tables instead of decorative cards.

## Human workflow

- The primary user question is obvious within 5-10 seconds.
- Evidence precedes consequential approval.
- Agent/human/system responsibility is explicit.
- Next action and post-action state are visible.
- Measurement/verification is represented when relevant.

## Data trust

- Missing/partial data never masquerades as zero.
- Source and freshness appear when they materially affect confidence.
- Errors explain what remains valid.

## Accessibility

- Keyboard navigation works for main flow.
- Focus is visible.
- Drawers/dialogs trap focus and restore it on close.
- Icon-only buttons have accessible names.
- Status is not communicated through color alone.
- Tables have headers and sensible reading order.
- Reduced-motion preferences are respected for non-essential motion.

## Responsive

Test at least:

- desktop >= 1280px;
- tablet 768-1279px;
- mobile < 768px.

On small screens, keep primary decision controls reachable, stack evidence sections, and collapse secondary table columns before abandoning the table model.

## Engineering

Run available project checks:

- lint;
- TypeScript typecheck;
- unit/component tests;
- build;
- e2e tests when configured.

Do not claim a check passed if the script does not exist or was not executed.
