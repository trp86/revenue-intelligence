# Design tokens

The design system of the POC frontend (epic #145; built in story #146). It was reviewed with the
UI UX Pro Max skill: a minimal "Swiss" enterprise dashboard style, at dashboard density. The
source of truth is `frontend/src/tokens/tokens.css`, the only file that may hold colour values:
`src/test/tokens.test.ts` fails on any other, and `src/test/design-system.test.tsx` checks the
contrast of the pairs below. Tailwind (`frontend/tailwind.config.js`) and the shadcn/ui
components map to these tokens. Light theme only.

## Colour roles
| Role | Token | Value | Contrast checked |
|---|---|---|---|
| Page background | `--color-bg` | #F4F6F9 | text 16.5:1 |
| Card | `--color-surface` | #FFFFFF | muted text 7.6:1 |
| Text / muted text | `--color-text` / `--color-text-muted` | #0F172A / #475569 | – |
| Card border (decorative; cards also have a shadow) | `--color-border` | #E2E8F0 | – |
| Form-control border | `--color-border-strong` | #64748B | 4.8:1 (needs 3:1) |
| Sidebar | `--color-sidebar-bg` | #0F1B33 | text #CBD5E1 11.6:1, active #FFFFFF 17.1:1, muted #94A3B8 6.7:1 |
| Opportunity (primary action) | `--color-opportunity`, `--color-primary` | #0F766E (tint #E6F4F1) | 5.5:1 on white, 4.8:1 on the tint |
| Estimate (the opportunity's value) | `--color-estimate` | teal, as the opportunity | – |
| Measured evidence | `--color-measured` | #1D4ED8 (tint #EFF6FF) | 6.2:1 |
| AI suggestion | `--color-ai` | #334155 slate (tint #F1F5F9); no purple since story #171 | 10.4:1 |
| Attention | `--color-warn` | #B45309 (tint #FFFBEB) | 4.8:1 |
| Risk | `--color-danger` | #B91C1C (tint #FEF2F2) | 5.9:1 |
| Focus ring | `--color-focus` / `--color-focus-on-dark` | #2563EB / #60A5FA | 5.2:1 on white / 6.7:1 on navy |
| Opportunity type (one colour each, everywhere: pills, tabs, charts) | `--color-chart-1` cross-sell, `-2` whitespace, `-3` dormant, `-4` recovery | #2A78D6, #C9531E, #0F8A63, #A06D00 | each 3:1 or more on white; validated CVD-safe (story #174) |
| Priority (one hue, three shades) | `--color-priority-high` / `-medium` / `-low` | #1E293B, #64748B, #B6C2D2 | with an arrow icon and the word; red is for errors and risks only (story #174) |

Colour is never the only signal: every badge, block and chart series also has text and a Lucide
icon or a label.

## Type, space, shape, depth, motion
- **Font:** Inter, a Google font, for all text: headings, body and numbers (`tabular` class:
  tabular figures), weights 400 to 700. It is bundled with `@fontsource/inter` (the Google Fonts
  files, served by the app, so it works offline and behind the company proxy); no font CDN.
  One font since story #171.
- **Type scale:** 12 (captions) / 14 (table cells, labels) / 16 (body, line height 1.5) /
  20 (section titles) / 28 (page titles, KPI values). Weights 400, 500 and 600–700.
- **Spacing:** 4, 8, 12, 16, 24 and 32 px (`--space-*`).
- **Radius:** 8 px for inputs, buttons and badges; 12 px for cards, dialogs and the sheet.
- **Shadows:** `--shadow-sm` for cards, `--shadow-md` for popovers, dialogs and the sheet.
- **Layers:** sticky 10, top bar 20, sheet 40, dialog 50, toast 100.
- **Motion:** 150 ms or 200 ms, colour and opacity only. Nothing animates under
  `prefers-reduced-motion`.
- **Focus:** a 2 px outline from `--color-focus` on every `:focus-visible` element; inside the
  navy sidebar it uses `--color-focus-on-dark` (the `on-dark` class).

## Components (frontend/src/components)
- `ui/`: Button, Card, Badge, Input, Select, Table, Skeleton, Dialog, Sheet, Tooltip,
  Breadcrumb and the Toaster (shadcn/ui on Radix; the Toaster is our own small live region since
  story #150, because sonner's markup failed axe).
- `feedback/`: EmptyState (an icon, the reason, an action), ErrorState (the cause and Retry),
  ConfirmDialog (Cancel or Escape closes it; focus stays inside and returns to the control that
  opened it).
- `AsyncBoundary`: skeletons shaped like the content (`lines`, `cards`, `table`, `detail`), with
  `aria-busy`.
- Toasts close after 4 s, are announced politely, and never take focus.
