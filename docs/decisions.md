# Project decisions

Status: living document. Change a decision through a PR.

## 1. Purpose
POC for a prospective FMCG client: an app that helps SALES MANAGERS
decide where to focus to grow revenue. Not a reporting dashboard.
Primary user: sales manager (decision-maker). Business question:
where can we generate extra revenue, why, and what should we do?

## 2. Data scope (from profiling)
- Core: RAW SCJ SALES, about 662k order lines, ~12k customers,
  181 products, 2017-07-02 to 2020-02-29 (as-of date 2020-02-29).
- Reference only: July 2019 closing report (targets, reconciliation).
- Separate / not in Phase 1: Oct 2019 DC (batteries), BBL, Beverage,
  YLT target.
- Ignored: Oct SCJ sheet (duplicates master), lookups, old extracts.
- Pivots are validation fixtures, never data.
- Raw data is confidential: never committed, never sent to external
  services unmasked.

## 3. Open business questions (use defaults in config until answered)
- Net sales field: DECIDED (provisional, client to confirm): source column
  46 (Excel AT, raw header `Net Amount`), final name `Net_Amount_2`. It is
  net of the first and second discount and before the 3% back margin.
  Why: it is the last step of the price chain that does not depend on a
  margin the client may treat as a cost; column 48 (`Net_AMOUNT_3`, after
  back margin) differs from it on about 8,700 of 658,763 rows and by about
  0.11% of the total. The client may prefer column 48; changing it is a
  one-line change to `net_sales.field` in `config/settings.yaml` through a
  PR. The value is labelled provisional in the UI. See story #51.
- Meaning of blank Void: DECIDED (provisional, client to confirm):
  blank Void sets void_flag = 0 (not void); the original value is
  kept. See spec 01 D3.
- Exact duplicates: DECIDED (provisional, client to confirm):
  excluded (all source columns identical except _source_row; first
  occurrence kept) in silver/gold, recorded in silver_excluded_rows,
  bronze untouched, effect stated in the quality report. See spec 01
  D4. Free goods (zero value with quantity) are flagged, not
  excluded. Provisional: assumed to be load duplicates. If the
  client confirms they are genuine repeated lines, set
  duplicates.exclude_from_net_sales to false.
- Customer identity (multi-spelling and multi-branch codes). Do not
  merge near-duplicate codes.
- Permission to send evidence to an external AI service.
- Every other open question in docs/specs uses its proposed default
  for now. The defaults are listed as OPEN QUESTION entries in each
  spec. A default is changed only through a PR.
- Recorded as decided (spec 01): the stray row, the source sheet
  layout, and `_source_row` as the lineage key (D1, D2, D5).

## 4. Use cases in scope
Revenue recovery, dormant customers, category whitespace,
cross-sell. Backtest (as-of replay) is a first-class deliverable.
Stretch: assortment expansion, price/discount. Out of scope: margin,
inventory, promotion, forecasting, competitor and macro data.

## 5. Architecture
Medallion on DuckDB, Polars at the edges, SQL in the middle.
- Bronze: raw sheets as Parquet, all text, lineage columns. Polars.
- Silver: typed, normalised, flagged. Keeps every bronze row; marks
  the stray row and exact duplicates as excluded and records them
  in silver_excluded_rows. DuckDB SQL.
- Gold: star schema (dim_customer, dim_product, dim_branch,
  dim_date, fact_sales; excluded rows are not loaded), marts (mart_*), opportunities (opp_*).
- App state (AI outputs, evidence snapshots, action status) lives in
  a separate app.duckdb file (DuckDB single writer).
- Net sales is defined once, in one view, driven by config.
- Thresholds and peer-group definitions live in config/settings.yaml.

## 6. AI rules
- Python/SQL calculates; Gemini communicates.
- Gemini gets a small evidence package, never raw transactions, and
  returns schema-validated JSON (explanation, recommendation,
  actions, risks, confidence label).
- No invented numbers, no invented causes, no margin or pricing
  advice without cost data.
- Store evidence snapshot, model, prompt version, timestamp.
- Separate Measured fact / Estimate / AI suggestion in the UI.
- Chat assistant uses fixed, tested tools over an allow-listed query
  layer, shared with the Explore screen. No free-form SQL.

## 7. Stack
uv (Python), Polars, DuckDB, FastAPI, google-genai (Gemini),
pydantic, typer, pytest, ruff, sqlfluff. Frontend: React +
TypeScript + Vite, Tailwind + shadcn/ui, TanStack Query/Table,
Recharts or ECharts. UI design guided by the ui-ux-pro-max skill.
React calls FastAPI only.

## 8. Screens (POC)
Overview, Opportunities, Opportunity Detail, Customer 360, Explore
(guided self-service), Decision Assistant (chat), Proof (backtest).
Optional: Action tracker, Data and Definitions.

## 9. Way of working
Specs in docs/specs (PR reviewed). Epics and stories are GitHub
issues on the company GitHub, with a Project board
(Backlog, Ready, In progress, In review, Blocked, Done).
Claude Code works ONLY on stories in Ready, never merges, never
expands scope. See docs/process.md for Definition of Ready/Done.

## 10. Epics
E0 Repo and tooling, E1 Bronze/Silver, E2 Gold star and marts,
E3 Opportunity engines, E4 Backtest, E5 AI layer, E6 API,
E7 Frontend foundation and core screens, E8 Explore and Assistant,
E9 Action tracking and demo hardening.
Plan stories for E0 and E1 first.