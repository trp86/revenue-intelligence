# 01 Data foundation (Epic E1: bronze and silver)

Status: DRAFT. FR-D1, FR-D2, FR-D5.

## 1. Purpose and scope
| In | Out |
|---|---|
| Ingest RAW SCJ SALES and July 2019 closing report to bronze | Other workbooks (decisions.md section 2) |
| Header detection, duplicate column handling | Gold modelling (spec 02) |
| Silver typing, normalisation, flags | Merging near-duplicate customer codes |
| Data quality report and reconciliation | Fixing the source data |

## 2. Inputs and outputs
| Kind | Name | Notes |
|---|---|---|
| In | data/raw/*.xlsx | Read-only; never edited or deleted |
| Out | data/bronze/<source>__<sheet>.parquet | All columns text |
| Out | silver tables in warehouse DuckDB: `silver_sales`, `silver_customer_codes`, `silver_products`, `silver_branches`, `silver_targets` | Typed, flagged |
| Out | `dq_rule_results` table + `reports/data_quality.md` | One row per rule |
| Out | `recon_results` table | Reconciliation checks |
| Code | src/revint/ingest/ (Polars), sql/10_silver/*.sql, sql/checks/ | Numbered SQL, run in order |

## 3. Bronze rules
| ID | Rule |
|---|---|
| B1 | Polars reads Excel; every column stored as text (no inference) |
| B2 | Header row detected, not hard-coded: first row where [x] or more cells are non-empty and match the expected column list in config. Known: header is on row 7 in RAW SCJ SALES |
| B3 | Duplicate column names are suffixed deterministically (`name`, `name__2`, ...) in source order; mapping saved in `bronze_column_map` |
| B4 | Lineage columns on every row: `_source_file`, `_sheet`, `_source_row`, `_ingested_at`, `_file_hash` |
| B5 | Row count in bronze equals data rows in the sheet (after header); logged |
| B6 | Re-run is idempotent: same input gives identical Parquet content apart from `_ingested_at` |
| B7 | Sheet names to load come from config, not code |

## 4. Silver rules
| ID | Rule |
|---|---|
| S1 | Cast to types (date, decimal(18,4), integer); keep original text beside each cleaned value as `<col>_raw` |
| S2 | Unparseable values become NULL and set flag `f_bad_<col>`; row kept |
| S3 | Channel and branch label normalisation via a config mapping table; unmapped labels kept as-is and flagged `f_unmapped_label` |
| S4 | Customer identity: code is the key. Multiple name spellings / branches per code are recorded in `silver_customer_codes` with counts. Near-duplicate codes are NOT merged |
| S5 | `f_exact_duplicate`: row identical to another on all source columns. First occurrence by `_source_row` is `is_first = true`. Known count in docs: 556 exact duplicates; the report must show the actual value |
| S6 | `f_blank_void`: Void is blank/NULL. Meaning is an open question, so no exclusion happens in silver |
| S7 | `f_zero_value_with_qty`: net sales = 0 and quantity > 0 (possible free goods) |
| S8 | `f_negative_qty` / `f_negative_value` for returns or credits (treated as data, not errors) |
| S9 | The documented stray row is the only row that may be excluded; excluded via `f_stray_row` and listed by `_source_row` in the report. [x] confirm location |
| S10 | Silver row count equals bronze row count minus rows flagged `f_stray_row` |
| S11 | Six candidate amount columns are all typed and kept; none is dropped (choice happens in spec 02) |

## 5. Quality report
One row per rule: `rule_id`, description, `rows_affected`,
`pct_rows` , `net_sales_impact`, `action_taken` (flagged / excluded),
severity. Output as table and markdown. Counts and aggregates only;
no customer-level values.

## 6. Reconciliation
| ID | Check | Tolerance (config) |
|---|---|---|
| R1 | Bronze rows = Excel data rows | 0 |
| R2 | Silver rows = bronze rows - stray rows | 0 |
| R3 | Sum of each candidate amount column: bronze (cast) = silver | 0.01 |
| R4 | Distinct customers, products, date min/max reported and compared with docs figures (about 12k, 181, 2017-07-02..2020-02-29) | informational, warn if outside +/- [x]% |
| R5 | Net sales by branch/month versus July 2019 closing report, for months it covers | [x]% |
| R6 | Pivots used as fixtures: pivot totals equal SQL totals | 0.01 |

## 7. Configurable parameters
| Key | Default |
|---|---|
| `ingest.sheets` | RAW SCJ SALES sheet name [x] |
| `ingest.header_search_rows` | 30 |
| `ingest.header_min_match` | 0.8 of expected columns |
| `labels.channel_map` / `labels.branch_map` | empty, filled from profiling |
| `recon.tolerance_amount` | 0.01 |
| `recon.tolerance_report_pct` | [x] |

## 8. Edge cases
- Header not found: fail loudly with the rows inspected.
- Same file, new hash: new run, old bronze kept by hash.
- Excel dates stored as serial numbers or text: both parsed; failure flagged.
- Thousands/decimal separators in text amounts: parse rule recorded
  in the report.
- Trailing blank rows: dropped from bronze only if fully empty
  (documented, counted).

## 9. Acceptance-level checks (pytest + sql/checks)
- [ ] Header detected on a fixture with header on row 7 and on row 1
- [ ] Duplicate column fixture yields `name`, `name__2`
- [ ] R1-R3 pass on the real file; R5 reported
- [ ] Each flag has a test with a crafted row
- [ ] No row deleted except `f_stray_row` (count test)
- [ ] Quality report lists every rule S1-S11 with counts
- [ ] Re-run produces identical content hash (excluding timestamps)

## 10. Dependencies
Spec 10 (repo, CLI, config), spec 00 (terms). Feeds spec 02.

## 11. OPEN QUESTIONS
- OPEN QUESTION: Meaning of blank Void. Default: treat as
  "not void" in config (`void.blank_means: not_void`) but flagged.
  Why: unblocks net sales without hiding the issue.
- OPEN QUESTION: Handling of 556 exact duplicates. Default: keep and
  flag; config `duplicates.exclude_from_net_sales: false`. Why:
  decisions say flag, never delete; true duplicates vs repeated
  orders is a client call.
- OPEN QUESTION: Which row is the "documented stray row"? Default:
  identify by profiling in the first story and list it in the
  report. Why: docs mention it without a location.
- OPEN QUESTION: Do exact `_source_row` order lines carry a stable
  order-line key? Default: none; use `_source_row`. Why: needed for
  duplicate logic.
