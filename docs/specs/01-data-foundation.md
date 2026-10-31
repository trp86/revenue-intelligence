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
| B1 | Polars reads Excel; every column stored as text (no inference). Implemented in `revint.ingest.bronze` (`revint build bronze`): values are written exactly as the Excel reader gives them, with no trimming, casting or cleaning; blank cells are NULL. Two reader behaviours are recorded from the real file: date cells (stored as serial numbers) arrive as ISO text `YYYY-MM-DD HH:MM:SS`, which matched the stored serial on every cell compared (30,000 of 30,000); and a floating-point cell can arrive with fewer digits than the stored number (relative difference up to 1.6e-13, about 8% of the money cells compared), so bronze text for such cells is the reader's text, not the stored text |
| B2 | Header row detected, not hard-coded (`revint.ingest.header.detect_header`): first row within `ingest.header_search_rows` (rows numbered as in Excel) where at least `ingest.header_min_match` of the expected columns (config) match. Names are compared after the B3 naming rule, so surrounding spaces and `_1`, `_2` suffixes are accounted for; the order of the columns does not matter. If no row qualifies the call fails with `HeaderNotFoundError`, whose message lists the rows inspected, the best match and the required share; it holds row numbers and counts, never cell values. An empty `ingest.expected_columns` is a configuration error, not "header not found". The result carries the header row, the data start row (header + 1) and the source-position map (position, Excel column letter, raw name, final name) that is stored as `bronze_column_map`. Known (decision D2): in RAW SCJ SALES there are 3 blank rows, the header is on row 7 and data starts on row 8; the detector must find row 7 and a test asserts it |
| B3 | Final column names (decision D2, naming rule decided on issue #31), implemented in `revint.ingest.columns`: (1) trim spaces at both ends of the source name; (2) replace each remaining space with `_`, keeping every other character; (3) names that are equal ignoring case, which includes exact repeats, are suffixed in source order as `name_1`, `name_2`, ..., each keeping its own capitalisation, because DuckDB treats column names case-insensitively; names that are unique ignoring case stay unsuffixed. Mapping of source position, raw name and final name saved in `bronze_column_map`. The sheet has 75 columns |
| B4 | Lineage columns on every row: `_source_file`, `_sheet`, `_source_row`, `_ingested_at`, `_file_hash`. `_source_row` is the 1-based Excel row number in the sheet (decision D5), so the first data row of RAW SCJ SALES is 8 and a row "about 662,135" is read in the same numbering |
| B5 | Row count in bronze equals data rows in the sheet (after header); logged. Blank rows between data rows and the stray row are kept; only trailing rows with every cell empty are dropped, and they are counted in the build output. A value to the right of the last header column fails the build. Outputs: `<paths.bronze>/<source>__<sheet>.parquet` (all text, source columns then the five lineage columns, all text including `_source_row`) and `bronze_column_map.parquet` (`source_file`, `sheet`, `position`, `source_column`, `raw_name`, `final_name`). All sheets are read and checked before anything is written, each file is written to a temporary name and renamed, and `paths.bronze` must not be inside `paths.raw`. `_ingested_at` is UTC, `YYYY-MM-DDTHH:MM:SSZ`. A workbook open in Excel (its `~$` lock file exists) or unreadable stops the build with exit code 6 |
| B6 | Re-run is idempotent: same input gives identical Parquet content apart from `_ingested_at` |
| B7 | Sheet names to load come from config, not code |

## 4. Silver rules
| ID | Rule |
|---|---|
| S1 | Cast to types (date, decimal(18,4), integer); keep original text beside each cleaned value as `<col>_raw`. Implemented in `sql/10_silver/02_silver_sales.sql` with the helper macros in `01_helpers.sql`; the typed columns are listed in `revint.silver.COLUMN_TYPES` and a test compares that list with the SQL. 28 of the 75 source columns are typed (2 dates, 3 whole numbers, 23 decimals, all six candidate amounts among them); the others stay text, passed through untouched. Blank means NULL, empty or only spaces, tabs, line breaks or non-breaking spaces. Dates accept ISO text (with or without a time) or an Excel serial number; any other layout, such as `01/08/2019`, is not guessed. A decimal with more than four places is rounded to four, with the original text in `<col>_raw` (on the real file, rounding moves the candidate amount sums by under 0.2 in 15 billion). A whole number must have no fractional part. `_source_row` becomes a whole number, with its text in `_source_row_raw` |
| S2 | Unparseable values become NULL and set flag `f_bad_<col>`; row kept. A blank cell is NULL without a flag. Every typed column has a flag; text columns have none |
| S3 | Channel and branch label normalisation via a config mapping table; unmapped labels kept as-is and flagged `f_unmapped_label`. Implemented in `sql/10_silver/07_label_normalisation.sql`. The columns the labels come from are `labels.channel_columns` (default `Channel_Category`) and `labels.branch_columns` (default `Branch_Name`), because the maps `labels.channel_map` and `labels.branch_map` are flat and have no column in them; this is the maintainer's decision on issue #37. Each listed column keeps its original value and gets a twin `<column>_normalised`; `f_unmapped_label` is one row-level flag, true when any listed column holds a non-blank label with no map entry. A label matches a key when the text is equal after trimming spaces at both ends, case-sensitive; a blank label stays blank and is not unmapped; an unlisted label is never guessed. The columns and maps reach the SQL as parameters (the maps as two parallel lists), so a label with a quote or any other character is data, never SQL. The build fails if a listed column is one that silver types (a date or number), if a column is in both lists, or if a column is missing from the bronze file; loading the settings fails if a key is blank or two keys are the same once trimmed. The shipped maps hold only the obvious spelling variants: channel `MODERN TRADE` and `MT` to `Modern Trade`; branch `MAGWAY`, `Hpa-an`, `PyinooLwin`, `PYAY` and `DAWEI` to `Magway`, `Hpa-An`, `Pyinoolwin`, `Pyay` and `Dawei`. Every other label stays unmapped until a person adds it. On the real file the maps change 532 channel labels and 2,422 branch labels |
| S4 | Customer identity: code is the key. Multiple name spellings / branches per code are recorded in `silver_customer_codes` with counts. Near-duplicate codes are NOT merged. Implemented in `sql/10_silver/09_customer_codes.sql`. The code, name and branch columns are `customers.code_column`, `customers.name_column` and `customers.branch_column` in config (defaults `CustomerCode`, `Customer`, `Branch_Name`), checked against `ingest.expected_columns` at load time. One row per distinct code, exactly as written (case and spaces included): `customer_code`, `order_lines`, `name_count`, `branch_count` (distinct non-blank values; a name differing by case or a space is another spelling), `near_duplicate_count` (how many other codes equal this one once trimmed and case-folded; they are counted, never merged), and the booleans `f_multiple_names` and `f_multiple_branches`. Counts are over the order lines silver keeps (`is_excluded` false); a blank code gets no row. `99_checks.sql` fails the stage if the table does not cover every kept line that has a code, or has a code twice. The table holds codes and counts, so it stays in the warehouse file and is never printed to issues, PRs or logs. On the real file: 12,239 codes covering 661,566 lines; 437 codes with more than one name, 87 with more than one branch; 109 codes have a near-duplicate (54 groups, 12,184 codes after folding) |
| S5 | Exact duplicate (decision D4): all source columns identical except `_source_row` (lineage columns are ignored). Comparison is on the text values in bronze: NULL, empty string and whitespace-only values are all treated as blank and compare equal to each other; any other value is compared exactly (no trimming, no case folding). Within each identical group the first occurrence (lowest `_source_row`) is kept and has `is_duplicate = false`; every extra copy has `is_duplicate = true`, `is_excluded = true`, `exclusion_reason = 'exact_duplicate'`. Silver marks and records them whatever `duplicates.exclude_from_net_sales` says; that setting only decides whether gold omits them (spec 02). Known count in docs: 556; the report must show the actual value. Bronze is never modified; silver keeps every row. Implemented in `sql/10_silver/04_duplicates.sql`: the columns compared are `duplicates.key_columns`, by default every source column in `ingest.expected_columns` (`Settings.duplicate_key_columns`), passed to the SQL as `$duplicates_key_columns`; the build fails if that list is empty or names a column that is not in the bronze file, because the SQL would otherwise ignore the name and make rows look more alike. The text is compared, not the typed value, so `10` and `10.0` are different. Each copy also gets `duplicate_of_source_row`, the `_source_row` of its kept first occurrence. On the real file the rule finds 556 extra copies in 547 groups (539 groups with one copy, 7 with two, 1 with three), which matches the figure in the docs |
| S6 | `void_flag` (decision D3, provisional): blank/NULL Void gives `void_flag = 0` (not void), per `void.blank_means`. The original value stays untouched in the original Void column. `f_blank_void` is also set so the assumption stays visible and counted. A non-blank value gets `void_flag` from `void.value_map` (filled from the distinct Void values listed by the first profiling story, section 10a). A non-blank value with no mapping gets `void_flag = NULL` and `f_unmapped_void = true`; it is reported, never guessed. `void_flag` alone does not exclude a row from silver or gold; whether voided lines count in net sales is an open question (section 12). Implemented in `sql/10_silver/06_void_flags.sql`: `void_flag` is a small whole number (1, 0 or NULL) and the original Void column is never changed. A blank is NULL, empty or only spaces, tabs, line breaks or non-breaking spaces. A mapped value is matched exactly (case-sensitive) after trimming those at both ends, and a quote or any other character in a map key is data, never SQL (the map is bound as parameters). `void.blank_means: void` makes a blank void_flag 1 instead of 0; `f_blank_void` is true either way. With the default empty `void.value_map` every non-blank value is unmapped (`void_flag` NULL, `f_unmapped_void` true) until a person fills the map from the profiling. The void rule never sets `is_excluded`. On the real file: 28,034 blank Void cells (28,033 data rows plus the stray row) get `void_flag` 0, and 634,094 cells hold one other value, which is unmapped, so no line is voided yet |
| S7 | `f_zero_value_with_qty`: net sales = 0 and quantity > 0 (possible free goods). Flagged only, never excluded. Implemented in `sql/10_silver/05_value_flags.sql`. Net sales is the column in `net_sales.field` and quantity the column in `net_sales.quantity_field` (passed to the SQL as `$net_sales_field` and `$net_sales_quantity_field`), so changing either needs no code edit. The test reads the typed values: a blank or unparseable value or quantity is unknown, not zero, and sets no flag. A value that rounds to 0.0000 in decimal(18,4) counts as zero. The build fails if `net_sales.candidate_columns` or `net_sales.quantity_field` names a column that silver does not type as a number. On the real file the flag is set on 120,727 rows (356 of them are also excluded duplicates), matching the profiling count for `Net_Amount_2` |
| S8 | `f_negative_qty` / `f_negative_value` for returns or credits (treated as data, not errors). `f_negative_qty` is true when the quantity column is below zero and `f_negative_value` when the net sales column is below zero; zero is not negative, and unknown (NULL) sets neither flag. All three flags are true or false, never NULL. On the real file both negative flags are set on 0 rows |
| S9 | Stray row (decision D1): the row where only "Change to Ctn" = 1 (all other columns blank), expected near `_source_row` 662,135. Silver keeps it with `is_excluded = true`, `exclusion_reason = 'stray_row'`, `f_stray_row = true`; gold excludes it. If more than one row matches, the build fails for review. Implemented in `sql/10_silver/03_exclusions.sql`: the rule looks at every source column in the bronze file, so a row matches only if "Change to Ctn" is 1 (`1`, `1.0` and ` 1 ` all count) and every other source cell is blank (NULL, empty or only spaces). A row with nothing filled is a blank row, not the stray row. `99_checks.sql` raises an error, and the stage rolls back, if more than one row matches; the message lists the counts and source rows, never cell values. The silver columns it adds are `is_excluded`, `exclusion_reason`, `f_stray_row` and `is_duplicate` (set by the duplicate rule, S5, in a later story) |
| S10 | Silver keeps every bronze row: `count(silver_sales) = count(bronze)`. Excluded rows are exactly the rows with `is_excluded = true`; the only reasons allowed are `stray_row` and `exact_duplicate`. No other rule may set `is_excluded` |
| S11 | Six candidate amount columns are all typed and kept; none is dropped (choice happens in spec 02) |
| S12 | `silver_excluded_rows` records every excluded row: `_source_row`, `exclusion_reason`, `duplicate_of_source_row` (nullable, the kept first occurrence), the six candidate amount columns, `excluded_at`. Written by the build, never edited by hand. Row-level detail stays in the warehouse file and is never printed to issues, PRs or logs. The table is built in `08_excluded_rows.sql`, after every file that can exclude a row (`03_exclusions.sql`, `04_duplicates.sql`), and rebuilt on every silver build (never appended); `excluded_at` is one UTC timestamp for the whole build; and `99_checks.sql` fails the stage if the table and the excluded rows of `silver_sales` differ in source rows or reasons, if an excluded row has no reason, if a row has a reason but is not excluded, or if any reason other than `stray_row` or `exact_duplicate` appears (S10; the allowed list is `revint.silver.ALLOWED_EXCLUSION_REASONS`). Neither file reads `duplicates.exclude_from_net_sales`, so `is_excluded` and the table are identical for both settings (S5) |

## 5. Quality report
One row per rule: `rule_id`, description, `rows_affected`,
`pct_rows`, `net_sales_impact`, `action_taken` (flagged / excluded),
severity. Output as table and markdown. Counts and aggregates only;
no customer-level values.

Implemented in `sql/10_silver/10_quality_results.sql` (story #41), which builds three tables
in the warehouse on every silver build. They hold counts and sums only, never a row, customer,
label or order value. The markdown report is a separate story (#42).

- `dq_rule_results`: one row per silver rule S1 to S12 with `rule_id`, `description`,
  `rows_affected`, `pct_rows` (rows over all silver rows, NULL when silver is empty),
  `net_sales_impact`, `action_taken` and `severity`.
- `dq_exclusion_effect`: one row per exclusion reason (`exact_duplicate`, `stray_row`) and
  candidate amount column, with `rows_excluded`, `excluded_amount`, `column_total`,
  `pct_of_column_total`, `pct_of_net_sales_total` and `is_net_sales_field`.
- `dq_void_effect`: one row with `voided_lines`, `voided_net_sales`, `blank_void_lines` and
  `unmapped_void_lines`.

`rows_affected` counts the PROBLEM rows of a rule (maintainer's decision on issue #41): S1 rows
where rounding a decimal to four places changed a value; S2 rows with at least one value that
could not be typed; S3 rows whose channel or branch label the map changed; S4 the kept order lines
of customer codes with more than one name or branch or a near-duplicate; S5 duplicate copies; S6
rows with a blank Void; S7 possible free goods; S8 negative quantity or value; S9 the stray row;
S10 excluded rows of any reason; S11 rows with a bad value in a candidate amount column; S12 rows
in `silver_excluded_rows`. `net_sales_impact` is the sum of `net_sales.field` over those rows,
NULL for S1 and S4. A row with no net sales value adds 0, so the impact undercounts there; the
description states how many such rows there are. The S6 description also states the voided lines
(`void_flag = 1`) and the unmapped Void values. `severity` (`info`, `warning`, `high`) and
`action_taken` (`flagged`, `excluded`, `transformed`, `recorded`) are a fixed value per rule in
config (`quality.severity`, `quality.action`), not computed from a percentage, because where to
draw a threshold is a business judgement. `99_checks.sql` fails the stage unless
`dq_rule_results` has exactly one row per rule, the exclusion table one row per reason and
candidate column, and the counts agree with the exclusion tables (S10 = S12 = S5 + S9).

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

How R1 to R4 run (story #43, `revint check`): the SQL is in `sql/checks` (numbered, run in order in one transaction by `revint.recon`), and the results are written to the warehouse table `recon_results` (`check_id`, `subject`, `description`, `status` = pass, fail or info, `expected`, `actual`, `difference` = actual - expected, `tolerance`, `detail`, `checked_at`), rebuilt on every run. R1 counts Excel data rows straight from the workbook (read-only): rows from the one under the header to the last row with any value, blank rows between data rows included. R2 has three results: `silver_rows`, `excluded_rows` and `stray_rows`. R3 has one result per `net_sales.candidate_columns` column; bronze text is cast the way silver casts it. R4 reports distinct `customers.code_column` values, distinct `recon.product_column` values and the minimum and maximum of `recon.date_column`, all as `info`; the +/- [x]% warning is still open. `revint check` prints every result and exits 0 when none failed, 7 when a check failed, 4 when the checks could not run (no warehouse, no silver, no workbook) and 5 when the warehouse is in use. R7 (silver side, story #44) has one result per `net_sales.candidate_columns` column and checks `sum(silver_sales)` = sum of the rows gold keeps (from `silver_sales`) + sum of the rows gold leaves out (from `silver_excluded_rows`): with `duplicates.exclude_from_net_sales = true` gold leaves out every excluded row, with `false` only the stray row. R8 is one result, `exact_duplicate_twins`: its actual and difference are the number of `exact_duplicate` rows that lack an identical, non-excluded twin at a lower `_source_row` (identical = every `duplicates.key_columns` column has the same bronze text, blanks equal), and its detail says how many copies were checked. R5, R6 and the gold form of R7 (with `sum(fact_sales)`, which needs the gold layer) are not part of this command yet.

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
| `labels.channel_columns` / `labels.branch_columns` | `Channel_Category` / `Branch_Name` (issue #37) |
| `labels.channel_map` / `labels.branch_map` | only the obvious spelling variants (see S3); every other label stays unmapped |
| `quality.severity` / `quality.action` | one value per rule S1 to S12 (see section 5) |
| `recon.tolerance_amount` | 0.01 |
| `recon.product_column` / `recon.date_column` | `SCJ_CODE_1` / `Date` (story #43): the columns R4 counts and ranges over |
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
