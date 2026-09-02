# SEO Agent Design System

## 1. Product character

The interface is an operational product, not a marketing analytics dashboard. It should feel calm, precise, trustworthy, and fast. Use Linear-like density and hierarchy without copying branding.

## 2. Semantic colors

Use CSS variables. Values may be tuned, but semantic roles must remain stable.

### Dark

```css
--bg: #090d14;
--surface-1: #101620;
--surface-2: #151d29;
--surface-3: #1b2533;
--border: #253142;
--border-strong: #344258;
--text: #f4f7fb;
--text-muted: #98a4b5;
--text-subtle: #69778b;
--primary: #6d5dfc;
--primary-hover: #7b6cff;
--primary-soft: #252147;
--success: #31c77a;
--warning: #f2a51a;
--danger: #ef4e4e;
--info: #4c9cff;
```

### Light

```css
--bg: #f6f7fb;
--surface-1: #ffffff;
--surface-2: #f1f3f8;
--surface-3: #e9edf4;
--border: #dfe4ec;
--border-strong: #cbd3df;
--text: #171b24;
--text-muted: #5f6b7c;
--text-subtle: #8792a2;
--primary: #6356e8;
--primary-hover: #5548d9;
--primary-soft: #eeecff;
--success: #168a52;
--warning: #a96300;
--danger: #c73737;
--info: #246fd6;
```

Never use semantic colors as large decorative fills. Prefer text, icon, border, soft background, or compact badge.

## 3. Typography

Preferred: Inter or system sans fallback.

- Display: 32/40, 600
- H1: 28/36, 600
- H2: 22/30, 600
- H3: 18/26, 600
- Body: 14/21, 400
- Body strong: 14/21, 500
- Small: 12/18, 400
- Micro/meta: 11/16, 500
- Numeric KPI: 24-32, 600 with tabular numerals

Avoid uppercase except compact metadata labels or status tags.

## 4. Spacing

8px base rhythm. Main increments: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64.

- Page horizontal padding: 24 desktop, 20 tablet, 16 mobile
- Card padding: 16 or 20
- Dense row height: 52-64
- Standard control height: 36
- Primary action height: 36-40
- Sidebar width: 220-248 desktop; icon rail only when collapsed

## 5. Radius

- controls: 6-8px
- cards: 8-10px
- drawers/modals: 10-12px
- pill: 999px only for status tags

Avoid exaggerated 20-32px radii.

## 6. Borders and shadows

Default separation is border + surface contrast.

Dark: minimal shadow; use 1px border.
Light: soft shadow only for floating drawers, menus, and elevated overlays.

Suggested overlay shadow:
`0 16px 40px rgba(22, 31, 45, .12)`.

## 7. Density

Use three density modes conceptually:

- **Overview**: spacious, summary focused.
- **Work queue**: compact, row-based.
- **Evidence/details**: readable, 2-column where width permits.

Do not use KPI cards for information that works better as a row or table.

## 8. Icons

Use one linear icon set, 1.75-2px stroke, 18-20px default. Use 16px in dense rows, 24px in empty states. Do not mix filled and outline icon families.

## 9. Status mapping

- Observe: info/blue
- Safe Fix: success/green
- Requires approval: warning/amber
- Risk: danger/red
- Running: primary/indigo + animated indicator
- Partial: warning
- Failed: danger
- Completed: success
- Awaiting data: neutral/info

Always pair color with text and/or icon.

## 10. Charts

Charts are subordinate to decisions.

Use charts for:

- organic clicks/impressions trend;
- CTR or position before/after;
- indexed URL trend;
- experiment measurement windows;
- execution duration/trend only if operationally useful.

Do not chart status counts that can be understood faster as text.

Keep grids subtle, labels sparse, legend compact, tooltips explicit.
