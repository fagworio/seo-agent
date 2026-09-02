# UI Review Checklist

## Human workflow
- Is the user's primary question obvious within 5 seconds?
- Is the next action obvious?
- Is evidence shown before consequential approval?
- Is agent versus human responsibility explicit?
- Is the post-action state clear?
- Is measurement or verification represented when applicable?

## Information hierarchy
- Is attention prioritized over passive metrics?
- Are repeated items rows/tables instead of unnecessary cards?
- Are charts decision-supporting rather than decorative?
- Is raw technical detail progressively disclosed?

## Safety and trust
- Are write actions labeled by risk/action class?
- Is scope shown before execution?
- Is rollback visible when available?
- Are destructive actions confirmed?
- Are partial/missing data states explicit?

## Agent transparency
- Can the user see the last execution and outcome?
- Can the user understand what changed versus the previous run?
- Are failed stages and their impact explained?
- Are raw logs optional rather than primary?

## Design consistency
- Uses semantic tokens only.
- Works in dark and light themes.
- Uses the shared spacing/radius/type scale.
- Reuses domain components.
- Avoids one-off colors and badges.

## Accessibility
- Keyboard reachable.
- Visible focus state.
- Status does not rely on color only.
- Adequate contrast.
- Dialog/drawer focus is trapped and restored.
- Tables have accessible headers.
- Icon-only controls have labels/tooltips.

## Responsive
- Desktop flow remains efficient.
- Tablet preserves primary actions.
- Mobile stacks detail sections sensibly.
- Sticky decision actions remain reachable.
- Large tables degrade to priority columns or cards only when necessary.
