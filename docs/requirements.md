# Requirements: AI Revenue Intelligence (POC)

Status: draft for specs. Decisions live in docs/decisions.md.

## 1. Purpose
Help SALES MANAGERS decide where to focus to grow revenue, using
historical FMCG sales transactions. The product answers:
where can the business generate extra revenue, why does the
opportunity exist, and what should the team do next?
It is not another sales reporting dashboard.

## 2. Users
- Primary: sales manager. Decides where to allocate attention,
  who owns an opportunity, and what to approve or defer.
- Secondary: executive (overview) and account owner (receives the
  brief for an assigned opportunity).

## 3. POC objectives
1. Detect evidence-backed opportunities from the sales data.
2. Prioritise them with a transparent, configurable score.
3. Explain each one with measured evidence.
4. Use Gemini to explain, recommend and propose actions, using only
   supplied evidence.
5. Prove the logic with a backtest on the client's own history.
6. Let managers explore the data in a guided, safe way.
7. Let managers approve, assign and defer opportunities.
8. Present all of this in a polished web app.

## 4. Data
- Core source: RAW SCJ SALES (about 662k order lines, 2017-07-02 to
  2020-02-29, about 12k customers, 181 products). As-of date
  2020-02-29.
- Reference: July 2019 closing report (branch targets, reconciliation).
- Out of Phase 1: DC, BBL, Beverage/YLT, Oct SCJ sheet (duplicate).
- Known data issues (must be handled and reported, not hidden):
  - 3 blank rows, header on row 7, data from row 8, 75 columns;
    duplicate column names suffixed _1/_2 (decision D2).
  - Six candidate amount columns; net sales is PROVISIONAL.
  - Customer codes with multiple name spellings or branches; do not
    merge near-duplicate codes.
  - Blank Void on some lines: void_flag = 0 (not void), original
    value kept, flagged (D3, provisional).
  - 556 exact duplicates (all source columns identical except
    _source_row): kept and flagged in silver, excluded from gold,
    first occurrence kept, each recorded in silver_excluded_rows
    (D4, provisional).
  - One stray row (only "Change to Ctn" = 1): excluded from gold,
    kept in silver (D1).
  - Zero-value lines with quantity (possible free goods): flagged,
    not excluded.
  - Bronze and data/raw are never modified; no other row is excluded.
  - Inconsistent channel labels and branch names.
- Raw data is confidential: never committed, never sent unmasked to
  external services.

## 5. Functional requirements

### 5.1 Data foundation (bronze, silver, gold)
- FR-D1 Ingest sheets to bronze Parquet unchanged, with lineage.
- FR-D2 Build silver with typed, normalised, flagged data; keep the
  original value beside each cleaned one. Silver keeps every bronze
  row and marks exclusions (stray row, exact duplicates) with a
  reason.
- FR-D3 Build the gold star schema and marts. Gold excludes the
  rows marked excluded in silver.
- FR-D4 Net sales is defined once and driven by configuration.
- FR-D5 Automated reconciliation checks against raw data and the
  July 2019 report; a data quality report lists every rule and its
  impact, including the excluded row count and revenue effect.

### 5.2 Opportunity engines
- FR-O1 Revenue recovery: material decline versus a comparable prior
  period (seasonality-aware).
- FR-O2 Dormancy: inactivity beyond the customer's own buying
  interval (not a fixed day count).
- FR-O3 Category whitespace: missing brand/category versus peers
  (peer group defined in config).
- FR-O4 Cross-sell: product/category affinity with minimum support
  and lift; weak relationships suppressed.
- FR-O5 Unified, ranked opportunity table: score, priority,
  confidence, evidence, value (a documented range, or a qualitative
  level if no defensible estimate).
- FR-O6 All thresholds in config; algorithms versioned.

### 5.3 Backtest (Proof)
- FR-B1 Replay as of a past date, generate opportunities from data
  up to then, measure outcomes in the following months.
- FR-B2 Report hit rate and lift versus a baseline.

### 5.4 AI layer (Gemini)
- FR-A1 Build a small evidence package per opportunity.
- FR-A2 Gemini returns schema-validated JSON: headline, explanation,
  recommendation, sales actions, risks, confidence label.
- FR-A3 Gemini never calculates metrics or invents values, causes
  or percentages; no pricing or margin advice without cost data.
- FR-A4 Store evidence snapshot, model, prompt version, timestamp
  and review status. Do not silently regenerate approved output.
- FR-A5 UI separates Measured fact, Estimate and AI suggestion.

### 5.5 Application screens
Overview, Opportunities, Opportunity Detail, Customer 360, Explore,
Decision Assistant, Proof. Optional: Action tracker, Data and
Definitions.
- FR-U1 Overview: where to focus this week (KPIs, opportunities by
  type, top opportunities).
- FR-U2 Opportunities: ranked, filterable by region, channel,
  branch, type, status.
- FR-U3 Detail: evidence, AI recommendation, actions, with
  Approve, Assign owner and Defer.
- FR-U4 Customer 360: history, categories bought and missing,
  flags, opportunities.
- FR-U5 Explore: guided self-service. Fixed measures and
  dimensions, filters, period comparison, drill-through, CSV
  export. Every view states its definition.
- FR-U6 Decision Assistant: chat that uses fixed, tested tools,
  shows its evidence, and says when the data cannot answer.
- FR-U7 Proof: backtest results.

### 5.6 Action tracking
- FR-T1 Approve, assign, defer (with reason), and set status.
- FR-T2 Statuses: New, Approved, Assigned, Done, Deferred.
- FR-T3 Stored in app.duckdb, separate from the warehouse.

## 6. Non-functional requirements
- Security: Gemini key server-side only; React never touches
  DuckDB or secrets; .env never committed.
- Privacy: minimum evidence to Gemini; customer identifiers masked
  unless permission is confirmed.
- Explainability: every number shows its definition; every
  recommendation links to evidence.
- Reproducibility: one command rebuilds raw to gold; all thresholds
  and the net sales choice are configuration.
- Quality: pytest, SQL checks, ruff, sqlfluff in CI.
- Accessibility: colour is never the only signal; loading, empty
  and error states on every screen.
- Performance: pre-aggregated marts; pages query the API, never
  raw transactions.

## 7. Out of scope
Margin or profit analysis, inventory, promotion effectiveness,
forecasting, competitor or macro data, vector DB/RAG, autonomous
execution of actions, multi-tenant admin, SSO.

## 8. Success criteria
1. One command builds bronze, silver and gold; reconciliation checks
   pass.
2. At least recovery, whitespace and one more engine produce ranked
   opportunities, each with evidence.
3. Backtest result is available and explainable.
4. Gemini output is schema-valid and uses only supplied evidence.
5. A manager can go from Overview to an opportunity, read the
   evidence and AI recommendation, and approve or assign it.
6. The assistant answers the suggested questions correctly, with
   evidence.

## 9. Open questions (defaults used until answered)
Net sales field; customer identity; permission for external AI; peer
group definition; value-estimation method; targets beyond July 2019.