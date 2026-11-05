# 07 Frontend (Epic E7)

Status: DRAFT. React + TypeScript + Vite, Tailwind + shadcn/ui,
TanStack Query/Table, Recharts or ECharts. UI design guided by the
ui-ux-pro-max skill. Calls the API only.

## 1. Purpose and scope
| In | Out |
|---|---|
| Foundation (tokens, layout, API client) and core screens | Explore and Assistant internals (spec 08) |
| Overview, Opportunities, Detail, Customer 360, Proof | Mobile-first design (desktop first, responsive down to tablet) |
| Optional: Data and Definitions | Auth screens, admin |

## 2. Inputs and outputs
| Kind | Name |
|---|---|
| In | API endpoints (spec 06), generated TS types from OpenAPI |
| Out | frontend/ app; routes below |
| Code | src/api (client), src/tokens, src/components, src/screens |

## 3. Navigation and screens

**POC scope (2026-11-02, docs/decisions.md section 11):** only Overview, Opportunities and
Opportunity Detail are built; Detail shows the Measured, Estimate and AI blocks without
Approve, Assign or Defer. Customer 360, Explore, Assistant, Proof, the Action tracker and Data
and Definitions are out of scope for the POC (E4, E8 and E9 were dropped).
| Route | Screen | Purpose (the decision it supports) |
|---|---|---|
| / | Overview | Where do I focus this week? KPIs, opportunities by type, top N, data as-of and net sales label |
| /opportunities | Opportunities | Which to act on? Ranked table, filters region/channel/branch/type/status, sort by score/value |
| /opportunities/:id | Opportunity Detail | Why does it exist and what do we do? Measured / Estimate / AI blocks, actions, Approve / Assign / Defer |
| /customers/:key | Customer 360 | Who is this customer? History, categories bought and missing, flags, opportunities |
| /explore | Explore | Spec 08 |
| /assistant | Decision Assistant | Spec 08 |
| /proof | Proof | Can I trust it? Backtest hit rate and lift vs baseline, N, caveats |
| /actions (optional) | Action tracker | What was decided? |
| /definitions (optional) | Data and Definitions | What does each number mean? Quality report |

Persistent shell: sidebar nav, header with as-of date and
"Net sales: <field> (provisional)" badge.

### Built in story #135 (foundation)
`frontend/`: Vite 5 + React 18 + TypeScript + Tailwind 3, TanStack Query and React Router. Commands
(in `frontend/`): `npm install`, `npm run dev` (http://localhost:5173, the API at
`VITE_API_BASE`, default `http://localhost:8000/api/v1`), `npm test` (Vitest and Testing
Library), `npm run lint` (ESLint and the type check) and `npm run build`. `src/tokens/tokens.css` is
the only file with colour values; `src/api/client.ts` is the only module that calls the network
(ESLint forbids `fetch` elsewhere, and a test checks both). Shared components: `AsyncBoundary`
(loading, empty, error with retry, partial), `Metric` (one formatter in `src/format.ts`, its unit,
and a definition button that works by mouse and keyboard) and `AppShell` (navigation, as-of date
and the net sales label from `/health`). Light theme only and en-US numbers with no currency
symbol, labelled net sales (provisional). Install scripts are not needed: esbuild ships its binary
as a package.

### Built in story #136 (screens)
`src/screens/Overview.tsx` (KPIs, counts by type and priority, the top 10 with links),
`Opportunities.tsx` (the ranked table; type, priority, confidence, branch and sort held in the URL;
25 a page) and `Detail.tsx` (Measured fact, Estimate and AI suggestion blocks, each with a heading,
an icon and its token colour; reasons and data-quality notes; a multiple-spellings notice). Priority
is text and an icon, never colour alone. Tests: `src/test/screens.test.tsx` (each screen, its
loading, empty and error states, and an axe check per screen; contrast is left to the browser run)
and the Playwright walkthrough `e2e/walkthrough.spec.ts` (`npm run e2e`): it builds a synthetic
warehouse with `e2e/make_warehouse.py`, starts `revint serve` and Vite, goes Overview -> a type ->
an opportunity -> its evidence, opens a definition from the keyboard, and runs axe (contrast
included) on all three screens. Until story #138 the AI block says the brief is not available.

### Built in story #138 (AI brief)
`src/components/AiBrief.tsx` fills the AI suggestion block of the Detail screen: the headline,
explanation, recommendation, actions and risks, with "AI suggestion, not a measured fact", the
model, prompt version, time and review status. With no brief it offers "Generate brief" (loading
and error states); when AI is off or failing it says so and the measured facts and estimate stay.
The walkthrough generates and reads a brief through `e2e/serve_fake_ai.py` (a fake Gemini, its
own ports 8765 and 5174), so it never calls Gemini.

### Layout (story #147, epic #145)
`src/components/layout/`: `AppLayout` (skip link, sidebar, top bar, `<main id="main">`, which takes focus on every
route change), `Sidebar` (navy, 768 px and wider: the app name, Overview and Opportunity Explorer, which is marked
"Main workspace"; the active item has a bar, bold text and `aria-current`), a `Sheet` with the same navigation
below 768 px (opened by "Open menu", closed by Escape or by choosing a screen), `TopBar` (breadcrumbs, the as-of
date, the provisional net sales badge, and the not-reachable and not-built banners), `PageHeader` (title, subtitle,
actions) and `crumbs.tsx` (the trail per route; a page sets its last crumb with `useCrumbTitle`, as the Detail page
does with "<Type>: <Customer>").

### Overview (story #148, epic #145)
`screens/Overview.tsx`: four `StatCard`s (`components/display/`: an icon badge, a label, the number through
`Metric`, and the estimates badged "Estimate"); two `ChartCard`s, each named by a one-line summary and with a
"Show as table" alternative of the same numbers with links: opportunities by type and priority (a stacked bar)
and the high value estimate by type (a sorted horizontal bar, chosen over a donut on the UI UX Pro Max chart
guidance); and the top 10 as a table with type and priority pills. Clicking a bar, a table cell, a type or the
Opportunities KPI opens the Explorer with that filter. Charts do not animate (the data is readable at once),
use the chart and priority tokens, and short axis labels (full names in the tooltip and the table). Badges
and the definition button use Lucide icons. `components/display/` is not named `data/`, because the root
`.gitignore` ignores every `data/` folder (it keeps client data out of git).

### Opportunity Explorer (story #149, epic #145)
`screens/Opportunities.tsx` is the main working screen. `components/explorer/` holds:
- `TypeTabs`: toggle buttons with `aria-pressed`;
- `FilterBar`: labelled native selects for priority, confidence and sort, and a branch search applied on Enter
  or when the field loses focus;
- `FilterChips`: each active filter as a removable chip, plus "Clear all";
- `OpportunityPreview`: loads the selected opportunity by id and shows what happened, why it matters (value
  range, priority, confidence, score) and "Open details".

The table shows rank, a short type pill, the customer with its category beneath, priority, confidence (on
screens 1536 px and wider; it is always in the preview), score and the value range. The sorted column has
`aria-sort`. The score and value definitions sit once in their column headers (`DefinitionButton` in
`Metric.tsx`) rather than on every number. A row is selected by clicking it or its Preview button; the
customer link opens the Detail page. The filters, sort, page and `selected` are in the URL, so back, forward
and shared links restore them. "What happened" comes from `src/summaries.ts`: one line per engine, built only
from the measured facts. When nothing matches, the empty state offers "Clear filters".

### Opportunity Detail (story #150, epic #145)
`screens/Detail.tsx` answers, in this order:
1. **What happened:** a line from `summaries.ts`, built only from measured facts.
2. **Where:** the customer, branch, channel and category.
3. **Why it matters:** priority, confidence and score in the header, and the value range in the Estimate block.
4. **What to do:** the AI suggestion.

`components/detail/panels.tsx` gives each block its own card, heading, icon and token colour:
- `EvidencePanel`: blue "Measured fact", "Calculated from the sales data", the facts as tiles with their
  definitions;
- `EstimatePanel`: teal "Estimate", "Not a measured result";
- `AiPanel`: purple "AI suggestion", "Generated by Gemini".

The blocks are siblings, never nested. In `AiBrief.tsx`, "Generate brief" opens a `ConfirmDialog`. It says the
measured facts (never customer names or codes) go to Gemini and count toward the daily limit, and nothing is
sent before confirming. A toast reports success, a cached brief or a failure, and a failure also shows its
reason inline. Reason codes show as chips and data-quality notes as amber notes. The page loads with a
detail-shaped skeleton. The toaster (`ui/toaster.tsx`) is our own polite live region: sonner's
`<li role="status">` markup failed axe.

### Information architecture and components after the redesign (story #151, epic #145)
```
Sidebar (navy; a Sheet "Open menu" below 768 px)   Top bar: breadcrumb · Data as of · Net sales badge
 ├ Overview               /                      Overview
 ├ Opportunity Explorer   /opportunities          Overview / Opportunities   (marked "Main workspace")
 └ (Detail)               /opportunities/:id      Overview / Opportunities / <Type>: <Customer>
```
- **Flow:** Overview (KPIs, two charts, the top 10) → the Explorer, filtered by a chart, type or KPI
  link → a row preview (what happened, why it matters) → Open details → the Detail page: what
  happened, where, why it matters, then the Measured fact, Estimate and AI suggestion blocks.
- **Filters, sort, page and the selected row live in the URL**, so a view can be shared and the
  Back button works.
- **Components** (`frontend/src/components/`):
  - `ui/`: shadcn-style primitives (button, card, badge, input, select, table, skeleton, dialog,
    sheet, tooltip, breadcrumb) and our own `toaster`;
  - `feedback/`: `EmptyState`, `ErrorState` (Retry), `ConfirmDialog`; `AsyncBoundary` (skeleton
    variants `lines`, `cards`, `table`, `detail`);
  - `layout/`: `AppLayout` (skip link, focus to `<main>` on route change), `Sidebar`, `TopBar`,
    `PageHeader`, breadcrumbs (`crumbs.tsx`);
  - `display/`: `StatCard`, `ChartCard` (chart or table toggle, text summary);
  - `explorer/`: `TypeTabs`, `FilterBar`, `FilterChips`, `OpportunityPreview`;
  - `detail/panels.tsx`: `EvidencePanel`, `EstimatePanel`, `AiPanel`; `AiBrief.tsx`;
  - `labels.tsx` (type, priority and confidence badges with icons), `Metric.tsx` (every number and
    its definition button).
- **Tokens:** `src/tokens/tokens.css` is the only file with colour values (enforced by
  `tokens.test.ts`); the palette and its roles are in `docs/design-tokens.md`.
- **Browser checks** (`npm run e2e`, `e2e/walkthrough.spec.ts`, one worker, in order): a
  keyboard-only pass, the mouse walkthrough ending in a generated brief (fake Gemini), and axe with
  colour contrast on all three screens at 1440, 1024 and 390 px with no sideways page scroll;
  screenshots are saved to `frontend/test-results/` (git-ignored).

## 4. Design tokens
- All colour, spacing, radius, type, elevation as tokens (CSS variables
  mapped in Tailwind config). No hard-coded colours in components;
  lint rule (or grep test) enforces it.
- Semantic tokens: `--color-measured`, `--color-estimate`,
  `--color-ai`, `--color-success/warn/danger`, `--color-priority-high/med/low`.
- Light theme required; dark theme optional [x].
- Palette and type scale chosen with ui-ux-pro-max (story #146), recorded in
  docs/design-tokens.md.

## 5. States
Every screen and every data region has: loading (skeleton), empty
(says why and what to do), error (message + retry), partial (e.g. AI
unavailable but evidence shown). Implemented via shared
`<AsyncBoundary>`; tested per screen.

## 6. Definitions and provenance
- Every number renders through `<Metric>`; click/hover opens its
  definition from /definitions (`definition_id`).
- Blocks are labelled Measured fact / Estimate / AI suggestion with
  text + icon + token colour (never colour alone).
- AI block shows model, prompt version, time, review status.
- Data-quality badge where flags affect an entity.

## 7. Accessibility
| Requirement | |
|---|---|
| WCAG 2.1 AA contrast; keyboard operable; visible focus | axe with contrast on every screen at 3 widths; keyboard-only e2e pass; 2 px `:focus-visible` ring checked in the browser (#151) |
| Colour never the only signal (priority = text + icon + colour) | badges and blocks carry text and a Lucide icon (#146, #150) |
| Charts: text alternative / data table toggle | `ChartCard`: summary as the image name, a Show as table toggle (#148) |
| Semantic landmarks, labelled form controls, aria-live for async status | skip link, landmarks, labelled filters, polite status and toast regions (#147, #149) |
| Respect `prefers-reduced-motion` | `index.css` turns off transitions and animations (#146) |

## 8. Behaviour rules
- Approve / Assign / Defer call API; optimistic update rolled back on error.
- Defer requires a reason (spec 09).
- URL holds filters and sort (shareable); table state persisted in query string.
- Currency/number formatting via one formatter; units and as-of always shown.
- Proof screen shows N and "low sample" label when N < `backtest.min_n`.

## 9. Configurable parameters
| Key | Default |
|---|---|
| `VITE_API_BASE` (env) | `http://localhost:8000/api/v1` |
| Top N on Overview | 10 |
| Table page size | 25 |
| Currency symbol / locale | [x] |

## 10. Edge cases
- Very long customer names truncated with tooltip.
- Opportunity with no AI brief: "Generate brief" button (if AI enabled).
- Stale data: banner if API as-of older than [x] days of the build.
- Customer with identity flag shows a "multiple spellings" notice.

## 11. Acceptance-level checks
- [ ] Each screen renders loading, empty, error states (component tests)
- [ ] Grep test: no hex/rgb colours outside the token file
- [ ] axe check passes on each screen
- [ ] A number's definition opens from keyboard
- [ ] Walkthrough test (Playwright): Overview -> opportunity -> read evidence -> Approve
- [ ] No frontend import of duckdb or Gemini SDKs; only the API client calls network
- [ ] Measured / Estimate / AI blocks distinguishable in greyscale screenshot

## 12. Dependencies
Spec 06 (API). Hosts 08 screens and 09 controls.

## 13. OPEN QUESTIONS
- OPEN QUESTION: Currency and locale. Default: show unit as configured
  `display.currency` = [x]; no conversion. Why: currency not stated in docs.
- OPEN QUESTION: Branding/theme of the client. Default: neutral theme. Why: none supplied.
- OPEN QUESTION: Chart library, Recharts or ECharts? Default: Recharts. Why: simpler for POC chart set.
- OPEN QUESTION: Are the Action tracker and Data and Definitions screens in the POC? Default: Definitions yes (cheap, supports explainability), Tracker via Detail page only until E9.
