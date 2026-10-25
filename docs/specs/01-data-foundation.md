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
| B2 | Header row detected, not hard-coded: first row within `ingest.header_search_rows` where at least `ingest.header_min_match` of the expected columns (config) match. Known (decision D2): in RAW SCJ SALES there are 3 blank rows, the header is on row 7 and data starts on row 8; the detector must find row 7 and a test asserts it |
| B3 | Duplicate column names are suffixed deterministically, in source order, as `name_1`, `name_2`, ... (decision D2); names that are unique stay unsuffixed. Mapping of source position to final name saved in `bronze_column_map`. The sheet has 75 columns |
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
| S5 | `f_exact_duplicate`: row identical to another on all source columns. First occurrence by `_source_row` is `is_first = true`. Known count in docs: 556 exact duplicates; the report must show the actual value. Kept and flagged, not excluded (decision D4); `_source_row` is the tie-breaker (decision D5) |
| S6 | `f_blank_void`: Void is blank/NULL. Treated as "not void" per `void.blank_means` (decision D3, provisional); the row is kept and flagged, so the choice stays visible |
| S7 | `f_zero_value_with_qty`: net sales = 0 and quantity > 0 (possible free goods) |
| S8 | `f_negative_qty` / `f_negative_value` for returns or credits (treated as data, not errors) |
| S9 | The documented stray row (decision D1) is the only row that may be excluded. Definition: a row where "Change to Ctn" = 1 and every other source column is blank; expected near `_source_row` 662,135. Flagged `f_stray_row`, excluded from silver, listed by `_source_row` in the report. If more than one row matches, the build fails and asks for review rather than excluding them |
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
| `ingest.sheets` | `RAW SCJ SALES` |
| `ingest.expected_columns` | list of the 75 source column names after suffixing, filled from profiling (decision D2) |
| `void.blank_means` | `not_void` (provisional) |
| `duplicates.exclude_from_net_sales` | `false` (provisional) |
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
- [ ] Header detected on a fixture with 3 blank rows and the header on row 7 (data from row 8), and on a fixture with the header on row 1
- [ ] Real file: 75 columns, expected-column list in config matches
- [ ] Duplicate column fixture yields `name_1`, `name_2`
- [ ] R1-R3 pass on the real file; R5 reported
- [ ] Each flag has a test with a crafted row
- [ ] No row deleted except `f_stray_row` (count test)
- [ ] Stray-row fixture: only the row with "Change to Ctn" = 1 and all else blank is excluded; a second match fails the build
- [ ] Blank-Void and duplicate rows are present in silver and flagged; net sales is unchanged by `f_exact_duplicate` while `duplicates.exclude_from_net_sales` is false
- [ ] Quality report lists every rule S1-S11 with counts
- [ ] Re-run produces identical content hash (excluding timestamps)

## 10. Dependencies
Spec 10 (repo, CLI, config), spec 00 (terms). Feeds spec 02.

## 11. Decisions
Recorded from the spec review. Reasoning kept from the original
open questions.

**D1. Stray row. DECIDED.**
The stray row is the row where only "Change to Ctn" = 1 (all other
columns blank), at about source row 662,135. The first profiling
story confirms the exact row and lists it in the quality report.
Why: the docs mention a stray row without a location; it is the
only permitted exclusion, so it must be identified precisely and
audited (see S9, S10).

**D2. Source sheet RAW SCJ SALES. DECIDED.**
3 blank rows, header on row 7, data from row 8, 75 columns, duplicate
names suffixed `_1`/`_2`. The expected column list is filled from
profiling and kept in `config/settings.yaml`
(`ingest.expected_columns`).
Why: header detection needs a reference list, and keeping it in
config avoids hard-coding.

**D3. Blank Void. DECIDED (provisional, client to confirm).**
Blank Void is treated as "not void" (`void.blank_means: not_void`)
and flagged `f_blank_void`.
Why: unblocks net sales without hiding the issue. If the client says
otherwise, change the config value through a PR.

**D4. 556 exact duplicates. DECIDED (provisional, client to confirm).**
Kept and flagged (`duplicates.exclude_from_net_sales: false`).
Why: decisions say flag, never delete; whether they are true
duplicates or repeated orders is a client call.

**D5. Order-line key. DECIDED.**
There is no stable order-line key. `_source_row` is used for lineage
and duplicate logic.
Why: needed for the duplicate rule (S5) and for audit.

## 12. OPEN QUESTIONS
None open in this spec. D3 and D4 await client confirmation.
