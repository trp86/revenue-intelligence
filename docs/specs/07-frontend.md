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

## 4. Design tokens
- All colour, spacing, radius, type, elevation as tokens (CSS variables
  mapped in Tailwind config). No hard-coded colours in components;
  lint rule (or grep test) enforces it.
- Semantic tokens: `--color-measured`, `--color-estimate`,
  `--color-ai`, `--color-success/warn/danger`, `--color-priority-high/med/low`.
- Light theme required; dark theme optional [x].
- Palette and type scale chosen with ui-ux-pro-max, recorded in
  docs/design-tokens.md when decided.

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
| WCAG 2.1 AA contrast; keyboard operable; visible focus | |
| Colour never the only signal (priority = text + icon + colour) | |
| Charts: text alternative / data table toggle | |
| Semantic landmarks, labelled form controls, aria-live for async status | |
| Respect `prefers-reduced-motion` | |

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
