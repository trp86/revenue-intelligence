# 01 Data foundation (Epic E1: bronze and silver)

Status: DRAFT. FR-D1, FR-D2, FR-D5.

## 1. Purpose and scope
| In | Out |
|---|---|
| Ingest RAW SCJ SALES and July 2019 closing report to bronze | Other workbooks (decisions.md section 2) |
| Header detection, duplicate column handling | Gold modelling (spec 02) |
| Silver typing, normalisation, flags, exclusion marking | Merging near-duplicate customer codes |
| Data quality report and reconciliation | Fixing the source data |

## 2. Inputs and outputs
| Kind | Name | Notes |
|---|---|---|
| In | data/raw/*.xlsx | Read-only; never edited or deleted |
| Out | data/bronze/<source>__<sheet>.parquet | All columns text |
| Out | silver tables in warehouse DuckDB: `silver_sales`, `silver_customer_codes`, `silver_products`, `silver_branches`, `silver_targets` | Typed, flagged |
| Out | `silver_excluded_rows` (audit of every excluded row, S12) | Written by the build |
| Out | `dq_rule_results` table + `reports/data_quality.md` | One row per rule |
| Out | `recon_results` table | Reconciliation checks |
| Code | src/revint/ingest/ (Polars), sql/10_silver/*.sql, sql/checks/ | Numbered SQL, run in order |

## 3. Bronze rules
| ID | Rule |
|---|---|
| B1 | Polars reads Excel; every column stored as text (no inference) |
| B2 | Header row detected, not hard-coded (`revint.ingest.header.detect_header`): first row within `ingest.header_search_rows` (rows numbered as in Excel) where at least `ingest.header_min_match` of the expected columns (config) match. Names are compared after the B3 naming rule, so surrounding spaces and `_1`, `_2` suffixes are accounted for; the order of the columns does not matter. If no row qualifies the call fails with `HeaderNotFoundError`, whose message lists the rows inspected, the best match and the required share; it holds row numbers and counts, never cell values. An empty `ingest.expected_columns` is a configuration error, not "header not found". The result carries the header row, the data start row (header + 1) and the source-position map (position, Excel column letter, raw name, final name) that is stored as `bronze_column_map`. Known (decision D2): in RAW SCJ SALES there are 3 blank rows, the header is on row 7 and data starts on row 8; the detector must find row 7 and a test asserts it |
| B3 | Final column names (decision D2, naming rule decided on issue #31), implemented in `revint.ingest.columns`: (1) trim spaces at both ends of the source name; (2) replace each remaining space with `_`, keeping every other character; (3) names that are equal ignoring case, which includes exact repeats, are suffixed in source order as `name_1`, `name_2`, ..., each keeping its own capitalisation, because DuckDB treats column names case-insensitively; names that are unique ignoring case stay unsuffixed. Mapping of source position, raw name and final name saved in `bronze_column_map`. The sheet has 75 columns |
| B4 | Lineage columns on every row: `_source_file`, `_sheet`, `_source_row`, `_ingested_at`, `_file_hash`. `_source_row` is the 1-based Excel row number in the sheet (decision D5), so the first data row of RAW SCJ SALES is 8 and a row "about 662,135" is read in the same numbering |
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
| S5 | Exact duplicate (decision D4): all source columns identical except `_source_row` (lineage columns are ignored). Comparison is on the text values in bronze: NULL, empty string and whitespace-only values are all treated as blank and compare equal to each other; any other value is compared exactly (no trimming, no case folding). Within each identical group the first occurrence (lowest `_source_row`) is kept and has `is_duplicate = false`; every extra copy has `is_duplicate = true`, `is_excluded = true`, `exclusion_reason = 'exact_duplicate'`. Silver marks and records them whatever `duplicates.exclude_from_net_sales` says; that setting only decides whether gold omits them (spec 02). Known count in docs: 556; the report must show the actual value. Bronze is never modified; silver keeps every row |
| S6 | `void_flag` (decision D3, provisional): blank/NULL Void gives `void_flag = 0` (not void), per `void.blank_means`. The original value stays untouched in the original Void column. `f_blank_void` is also set so the assumption stays visible and counted. A non-blank value gets `void_flag` from `void.value_map` (filled from the distinct Void values listed by the first profiling story, section 10a). A non-blank value with no mapping gets `void_flag = NULL` and `f_unmapped_void = true`; it is reported, never guessed. `void_flag` alone does not exclude a row from silver or gold; whether voided lines count in net sales is an open question (section 12) |
| S7 | `f_zero_value_with_qty`: net sales = 0 and quantity > 0 (possible free goods). Flagged only, never excluded |
| S8 | `f_negative_qty` / `f_negative_value` for returns or credits (treated as data, not errors) |
| S9 | Stray row (decision D1): the row where only "Change to Ctn" = 1 (all other columns blank), expected near `_source_row` 662,135. Silver keeps it with `is_excluded = true`, `exclusion_reason = 'stray_row'`, `f_stray_row = true`; gold excludes it. If more than one row matches, the build fails for review |
| S10 | Silver keeps every bronze row: `count(silver_sales) = count(bronze)`. Excluded rows are exactly the rows with `is_excluded = true`; the only reasons allowed are `stray_row` and `exact_duplicate`. No other rule may set `is_excluded` |
| S11 | Six candidate amount columns are all typed and kept; none is dropped (choice happens in spec 02) |
| S12 | `silver_excluded_rows` records every excluded row: `_source_row`, `exclusion_reason`, `duplicate_of_source_row` (nullable, the kept first occurrence), the six candidate amount columns, `excluded_at`. Written by the build, never edited by hand. Row-level detail stays in the warehouse file and is never printed to issues, PRs or logs |

## 5. Quality report
One row per rule: `rule_id`, description, `rows_affected`,
`pct_rows`, `net_sales_impact`, `action_taken` (flagged / excluded),
severity. Output as table and markdown. Counts and aggregates only;
no customer-level values.

The report has an **Exclusions** block stating, per reason
(`exact_duplicate`, `stray_row`): the excluded row count and the
revenue effect (sum of each candidate amount column over the excluded
rows, and as % of the total for the configured net sales field).

## 6. Reconciliation
| ID | Check | Tolerance (config) |
|---|---|---|
| R1 | Bronze rows = Excel data rows | 0 |
| R2 | `count(silver_sales)` = bronze rows; `count(silver_excluded_rows)` = rows with `is_excluded`; stray rows = 1 (or the number found by D1 profiling) | 0 |
| R3 | Sum of each candidate amount column: bronze (cast) = silver | 0.01 |
| R4 | Distinct customers, products, date min/max reported and compared with docs figures (about 12k, 181, 2017-07-02..2020-02-29) | informational, warn if outside +/- [x]% |
| R5 | Net sales by branch/month versus July 2019 closing report, for months it covers | [x]% |
| R6 | Pivots used as fixtures: pivot totals equal SQL totals | 0.01 |
| R7 | Totals reconcile with and without exclusions, for every candidate amount column. With `duplicates.exclude_from_net_sales = true`: `sum(silver_sales)` = `sum(fact_sales)` + `sum(silver_excluded_rows)`. With `false`: `sum(silver_sales)` = `sum(fact_sales)` + `sum(silver_excluded_rows where exclusion_reason = 'stray_row')` | 0.01 |
| R8 | Every `exact_duplicate` row in `excluded_rows` has an identical twin (all source columns) at a lower `_source_row` that is not excluded | 0 |

## 7. Configurable parameters
| Key | Default |
|---|---|
| `ingest.sheets` | `RAW SCJ SALES` |
| `ingest.expected_columns` | list of the 75 source column names after suffixing, filled from profiling (decision D2) |
| `void.blank_means` | `not_void` (provisional; sets `void_flag = 0`) |
| `void.value_map` | empty until the first profiling story lists the distinct Void values (section 10a); unmapped non-blank values are reported |
| `duplicates.exclude_from_net_sales` | `true` (provisional). Controls gold only: when `true`, `fact_sales` omits the extra copies; when `false`, gold keeps them (still flagged `is_duplicate`) and the report shows both totals. Silver marks and records them either way |
| `duplicates.key_columns` | all source columns except `_source_row` (from `ingest.expected_columns`) |
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
- [ ] Bronze is unchanged by the build (file hash before and after)
- [ ] `count(silver_sales)` = bronze rows; no silver row is dropped (count test)
- [ ] `silver_excluded_rows` and `is_excluded` are identical for both settings of `duplicates.exclude_from_net_sales`
- [ ] Excluded rows counted: `count(silver_excluded_rows)` = stray rows + extra duplicate copies = rows with `is_excluded`; actual value reported against the ~556 in the docs
- [ ] Duplicate fixture: 3 identical rows keep only the lowest `_source_row`; rows differing in one column are not duplicates; `is_duplicate` and `exclusion_reason` are set on the extra copies only
- [ ] Stray-row fixture: only the row with "Change to Ctn" = 1 and all else blank is excluded; a second match fails the build
- [ ] Duplicate fixture with NULL, empty-string and whitespace-only cells in the same column: treated as identical; "A" and "a" or "A " are not
- [ ] Unmapped-Void fixture: a non-blank value absent from `void.value_map` gives `void_flag = NULL`, `f_unmapped_void = true`, and appears in the report
- [ ] `_source_row` fixture: first data row of a sheet with the header on row 7 has `_source_row = 8`
- [ ] Blank-Void fixture: blank Void gives `void_flag = 0` and `f_blank_void = true`; the original Void column is unchanged
- [ ] Totals reconcile with and without exclusions (R7) for all six amount columns; with `duplicates.exclude_from_net_sales = false` the gold total equals the silver total minus stray rows only (R7, second form)
- [ ] Free-goods fixture (zero value, quantity > 0) is flagged `f_zero_value_with_qty` and not excluded
- [ ] Quality report states the excluded count and revenue effect per reason
- [ ] Quality report lists every rule S1-S12 with counts
- [ ] Re-run produces identical content hash (excluding timestamps)

## 10. Dependencies
Spec 10 (repo, CLI, config), spec 00 (terms). Feeds spec 02.

## 10a. First profiling story theme (E1 plan)
The first E1 story profiles RAW SCJ SALES and fills config. Outputs
are counts and aggregates only, never customer-level values.

- [ ] Confirm the stray row (D1): exact `_source_row`, and that no
      other row has only "Change to Ctn" = 1
- [ ] Confirm header row, data start row and the 75 column names
      (D2) and write `ingest.expected_columns`
- [ ] **List the distinct Void values with row counts (including
      blank), so the `void_flag` mapping can be set in config**
      (D3). Any non-blank value without a mapping is reported, not
      guessed
- [ ] Count exact duplicates (D4) and compare with the ~556 in the docs
- [ ] Count zero-value lines with quantity (free goods)
- [ ] Distinct channel and branch labels, for the label maps

Profiling results (story #31, counts and aggregates from `uv run python -m revint.ingest.profile`): header row 7, data from row 8 to row 662134 (662,127 rows), 75 columns, exactly one stray row candidate at `_source_row` 662135, 556 exact-duplicate extra copies in 547 groups (matches the docs figure), two distinct Void values (`Unvoid` and blank). The 75 final names are in `config/settings.yaml` (`ingest.expected_columns`). `Void` has no mapping yet: `void.value_map` stays empty until a human supplies it.

## 11. Decisions
Recorded from the spec review. Reasoning kept from the original
open questions.

**D1. Stray row. DECIDED.**
The stray row is the row where only "Change to Ctn" = 1 (all other
columns blank), at about source row 662,135. The first profiling
story confirms the exact row and lists it in the quality report.
Why: the docs mention a stray row without a location; it is the
only permitted exclusion, so it must be identified precisely and
audited (see S9, S10, S12).

**D2. Source sheet RAW SCJ SALES. DECIDED.**
3 blank rows, header on row 7, data from row 8, 75 columns, duplicate
names suffixed `_1`/`_2`. The expected column list is filled from
profiling and kept in `config/settings.yaml`
(`ingest.expected_columns`).
Why: header detection needs a reference list, and keeping it in
config avoids hard-coding.

**D3. Blank Void. DECIDED (provisional, client to confirm).**
When the source Void is blank, `void_flag = 0` (not void). The
original value stays in the original column
(`void.blank_means: not_void`), and `f_blank_void` keeps the
assumption visible.
Why: unblocks net sales without hiding the issue. If the client says
otherwise, change the config value through a PR.
Supersedes: the earlier wording (same meaning, now with an explicit
`void_flag` column).

**D4. Exact duplicates. DECIDED (provisional, client to confirm).**
Excluded. Definition: all source columns identical except
`_source_row`. The first occurrence (lowest `_source_row`) is kept.
Bronze is never modified. Silver keeps every row with `is_duplicate`
and an exclusion reason, whatever the config says. Gold `fact_sales`
excludes the extra copies while `duplicates.exclude_from_net_sales`
is true. Every excluded row is recorded in `silver_excluded_rows`
with the reason. Config: `duplicates.exclude_from_net_sales: true`. The data
quality report states the excluded count and revenue effect. Free-goods
lines (zero value with quantity) stay flagged, not excluded.
Why: Provisional: assumed to be load duplicates. If the client
confirms they are genuine repeated lines, set
`duplicates.exclude_from_net_sales` to false.
Supersedes: the earlier decision "kept and flagged, not excluded".

**D5. Order-line key. DECIDED.**
There is no stable order-line key. `_source_row` is used for lineage
and duplicate logic. It is the 1-based Excel row number in the sheet.
Why: needed for the duplicate rule (S5) and for audit.

## 12. OPEN QUESTIONS
D3 and D4 await client confirmation. If D4 is reversed, set
`duplicates.exclude_from_net_sales: false` and rebuild gold; silver
is unchanged.

- OPEN QUESTION: Do voided lines (non-blank Void mapped to
  `void_flag = 1`) count in net sales? Default: yes until the client
  confirms what Void means; the quality report states the count and
  amount of `void_flag = 1` lines so the effect is visible, and
  excluding them later is a config change
  (`net_sales.exclude_flags`, spec 02). Why: the meaning of Void is
  unconfirmed and the distinct values are not yet known (section 10a).
