# Light Theme Specification

## Intent

The light dashboard must feel like the same product, not a separate skin. Preserve spacing, density, information hierarchy, typography, and component structure.

## Surface hierarchy

- page background: `--bg #f6f7fb`
- sidebar: `--surface-1 #ffffff`
- card: `--surface-1 #ffffff`
- inset/filter area: `--surface-2 #f1f3f8`
- hover row: `#f5f6fa`
- selected row: `--primary-soft #eeecff`
- default border: `--border #dfe4ec`

Avoid pure white page background with white cards; separation must remain visible.

## Text

- primary: #171b24
- muted: #5f6b7c
- subtle: #8792a2

Do not use low-contrast #aaa text for operational metadata.

## Primary accent

Use indigo/purple consistently:
- primary: #6356e8
- hover: #5548d9
- selected surface: #eeecff
- focus ring: rgba(99, 86, 232, .28)

## Semantic states

Use tinted surfaces rather than saturated full backgrounds:

- success bg: #edf9f2; text: #168a52
- warning bg: #fff6e6; text: #a96300
- danger bg: #fff0f0; text: #c73737
- info bg: #eef5ff; text: #246fd6

## Cards

Default:
- background white
- 1px gray border
- 8-10px radius
- no shadow

Floating drawer/menu:
- border
- subtle elevation shadow

## Tables and queues

Use borders between rows, not alternating zebra fills. Hover should be subtle. Selected rows may use primary-soft background plus a 2px primary inset/accent.

## Charts

Use the same series identity as dark mode. Light grid lines become slightly darker than card background but remain low contrast. Ensure tooltip uses white surface + border + shadow.

## Inputs

Inputs use white or surface-2 depending on context. Focus state must use visible primary ring. Disabled controls must remain readable.

## Sidebar

Use white sidebar with border-right. Active item uses primary-soft fill, primary icon/text, no oversized pill.

## Reference

Use `assets/light-design-reference.png` to maintain overall visual direction. Treat it as composition guidance, not an exact source of token values.
