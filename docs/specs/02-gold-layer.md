# 02 Gold layer (Epic E2)

Status: DRAFT. FR-D3, FR-D4.

## 1. Purpose and scope
| In | Out |
|---|---|
| Star schema, net sales view, marts, data dictionary | Opportunity logic (spec 03) |
| Fiscal/calendar date dimension | Forecasting, margin |
| Marts used by Explore and engines | App state (spec 09) |

## 2. Inputs and outputs
| Kind | Name |
|---|---|
| In | silver tables (spec 01) |
| Out dims | `dim_customer`, `dim_product`, `dim_branch`, `dim_date` |
| Out fact | `fact_sales` (grain: one silver order line, flagged rows included) |
| Out view | `v_net_sales` (single definition of net sales) |
| Out marts | `mart_customer_month`, `mart_customer_category_month`, `mart_customer_profile`, `mart_peer_category_share`, `mart_branch_month` |
| Out docs | `docs/data_dictionary.md` generated from `dim/fact/mart` metadata |
| Code | sql/20_gold/*.sql (numbered), sql/checks/ |

## 3. Net sales view (FR-D4)
| ID | Rule |
|---|---|
| N1 | `v_net_sales` is the ONLY place net sales is defined. All marts and queries use it |
| N2 | Net sales column = `config.net_sales.field` (default `Net_Amount_2`, source column 46, provisional). Must be one of `config.net_sales.candidate_columns` (the six candidate amount columns), else loading the settings fails; every net sales column must also be in `ingest.expected_columns` |
| N3 | Row inclusion driven by config: `net_sales.exclude_flags` (default empty list). Gold never loads the stray row, and loads exact-duplicate extra copies only when `duplicates.exclude_from_net_sales` is false, so the view needs no extra filter for them |
| N4 | View exposes `net_sales`, `net_sales_field_used`, `included` (bool) so the UI can label the definition |
| N5 | Switching `net_sales.field` changes marts after rebuild without code edits; a test proves it |

Implemented in `sql/20_gold/01_v_net_sales.sql` (story #74), run by `revint.gold.run_gold` (the command `revint build gold` is story #87). A view cannot take bound parameters, so the parameterised result is the table `gold_net_sales_lines` (rebuilt in full on every gold run) and `v_net_sales` is a plain view over it. Columns: `sales_line_id` (the silver `_source_row`), `net_sales`, `net_sales_field_used`, `included`, `quantity` (from `net_sales.quantity_field`) and `amount_<column>` for each `net_sales.candidate_columns` column, so later SQL selects `amount_*` and never names a source amount column; this is the only gold file that names a column, and only through parameters. The rows are every silver row except the stray row, and except the exact-duplicate copies when `duplicates.exclude_from_net_sales` is true. `included` is false when the row has any flag in `net_sales.exclude_flags`; such a row stays in the view. On the real file: 661,571 rows (662,128 - 557) with the setting true and 662,127 with it false; the Net_Amount_2 total with it false is the silver total, 15,473,904,687.2629.

## 4. Dimensions
| Table | Key | Key attributes |
|---|---|---|
| dim_customer | `customer_key` (surrogate), `customer_code` | name (most frequent spelling), `n_name_variants`, `n_branches`, channel, first/last order date, `f_multi_identity` |
| dim_product | `product_key`, `product_code` | name, brand, category [x] (source columns TBD) |
| dim_branch | `branch_key` | normalised name, region (config mapping) |
| dim_date | `date_key` | date, week, month, quarter, year, month_start; fiscal fields if config enables |

`dim_date` (story #75, `sql/20_gold/02_dim_date.sql`): one row per calendar day from the first to the last date in `silver_sales` (the column is `calendar.date_column`, default `Date`, which gold checks is a typed date column), with no gaps, so a month with no sales still has its days; dates silver could not type add no day. Columns: `date_key` (the day as yyyymmdd), `date`, `week` (ISO week, Monday first), `iso_year` (the year the ISO week belongs to; 30 December 2019 is week 1 of 2020), `week_start`, `month`, `quarter`, `year`, `month_start`, `fiscal_year`, `fiscal_quarter` and `f_after_asof` (the day is after `asof.date`; the fact uses it to flag a line dated after the as-of date, and keeps the line). The fiscal year is named by the calendar year it starts in: with `calendar.fiscal_year_start_month` 1 the fiscal fields equal the calendar ones; with 4 (April), March 2020 is fiscal year 2019, quarter 4. The unknown member `date_key = -1` has NULL fields and `f_after_asof = false`; a line with no usable date joins it. On the real file: 973 days (2017-07-02 to 2020-02-29), none after the as-of date.

`dim_branch` (story #76, `sql/20_gold/03_dim_branch.sql`): one row per normalised branch, taken from the normalised twin of the branch label column (`labels.branch_columns`, exactly one column; silver rule S3), trimmed. The variants the label map joins are one branch (`MAGWAY` and `Magway`); a variant it does not join, such as a case difference, stays a separate branch, and nothing is merged here beyond that map. Columns: `branch_key` (the first 60 bits of the md5 of the name: positive, deterministic, never -1), `branch_name`, `region`, `region_source` (`config`, `source` or `unknown`) and `f_region_conflict`. Region is `regions.branch_to_region` when the branch has an entry (matched after trimming both ends, case-sensitive, like the label maps), else the most frequent non-blank value of `regions.source_column` (a tie goes to the value on the lowest `_source_row`), else `Unknown`. `f_region_conflict` is true when the source column gives the branch several regions and the config map does not settle it. The unknown member `branch_key = -1` (name and region `Unknown`) is where a line with a blank branch joins; no line is dropped. On the real file: 33 branches plus the unknown member, 6 branches with several source regions (224 of 454,119 lines are on the minority region), 2 regions, no line without a branch row, and 1 line on the unknown member.

`dim_customer` (story #77, `sql/20_gold/04_dim_customer.sql`): one row per customer code in `silver_customer_codes` (rule S4), plus the unknown member. The code is the identity: near-duplicate codes (equal once trimmed and case-folded) stay separate rows with their own keys, are counted and are never merged. Like the silver table, everything is counted over the lines silver keeps (`is_excluded` false). Columns: `customer_key` (the first 60 bits of the md5 of the code as written, case and spaces included; positive, deterministic, never -1), `customer_code`, `customer_name`, `n_name_variants`, `n_branches` and `n_near_duplicate_codes` (from silver), `f_multi_identity` (several names, several branches, or a near-duplicate code), `channel`, `branch`, `first_order_date`, `last_order_date` and `order_lines`. The name is the most frequent spelling; a tie goes to the spelling on the later order, then to the lowest `_source_row`. Channel and branch are the normalised labels (rule S3) of the latest order that has one (latest date first, then the lowest `_source_row`; a blank on the latest order does not hide an earlier one). A customer with no name, channel or branch gets `Unknown`; a customer with no dated line has NULL dates. The unknown member `customer_key = -1` has no code; a line with a blank code joins it, so no line is dropped. The gold stage refuses a typed code or name column and needs exactly one channel and one branch label column (`labels.channel_columns`, `labels.branch_columns`). On the real file: 12,239 codes plus the unknown member, 623 with `f_multi_identity` (437 with several names, 87 with several branches, 109 with a near-duplicate code), 2 with no name, none with a tied latest branch (6 have a tied top spelling, settled by the rule above), 661,566 order lines, and 6 silver lines on the unknown member (5 blank-code lines plus the excluded stray row); no line with a code is unmatched.

`dim_product` (story #78, `sql/20_gold/05_dim_product.sql`): one row per product code (trimmed, otherwise as written) plus the unknown member, from the lines silver keeps (`is_excluded` false). The columns come from `product.*` (chosen in story #73, section 12); the gold stage refuses a typed one. Columns: `product_key` (the first 60 bits of the md5 of the code: positive, deterministic, never -1), `product_code`, `product_name`, `brand`, `category`, `n_name_values`, `n_brand_values` and `n_category_values` (distinct non-blank values), `f_value_conflict` (any column has several values), `f_no_category` and `order_lines`. A code with several values in a column takes the most frequent value; a tie goes to the value on the lowest `_source_row`; a blank beside a value is not a conflict. A product with no name, brand or category shows `Unknown`, and `f_no_category` says that the source had no category (a real category called `Unknown` is not flagged). The unknown member `product_key = -1` has no code; a line with a blank code joins it, so no line is dropped. On the real file: 181 product codes plus the unknown member, 12 codes with several names, 4 with several brands, 2 with several categories (16 products with any conflict, none with a tie), 4 without a category, 9 without a name, 7 brands and 40 categories (8 and 41 on the dimension, where Unknown counts as a value), 660,545 order lines, and 1,107 silver lines on the unknown member (blank code); no line with a code is unmatched.

Rules: surrogate keys deterministic (hash of natural key); unknown
members use key `-1` rather than dropping rows; near-duplicate
customer codes remain separate rows.

## 5. Fact
`fact_sales`: `sales_line_id` (from `_source_row`), `date_key`, `customer_key`,
`product_key`, `branch_key`, quantity, all six amount columns,
`net_sales` (from view), all silver flags.
Silver marks `is_excluded` the same way for both settings of the config (spec 01 S5). Gold omits the stray row always, and the exact-duplicate extra copies when `duplicates.exclude_from_net_sales` is true. When it is false, copies stay in the fact with `is_duplicate = true`. The fact keeps `void_flag`, `is_duplicate` and the other flags.
Check: with the config true, fact row count = silver row count - `count(silver_excluded_rows)`; with false, fact row count = silver row count - stray rows.

Implemented in `sql/20_gold/06_fact_sales.sql` (story #79). The rows are exactly the rows of `v_net_sales` (the stage fails and rolls back if a join drops or multiplies a line). Columns, in order: `sales_line_id`, `date_key`, `customer_key`, `product_key`, `branch_key`, `quantity`, `net_sales`, `included`, one `amount_<column>` per `net_sales.candidate_columns` column (from the view), `void_flag`, every silver flag column (`revint.silver_schema.SILVER_FLAG_COLUMNS`, passed to the SQL as `$silver_flag_columns`, so the SQL names none; the stage fails if the list and the silver table disagree) and `f_after_asof` (from `dim_date`; the line is kept). Flags are carried over unchanged, so a kept copy shows `is_duplicate` and `is_excluded` true. A line whose date, customer code, product code or branch is blank, or not in its dimension, gets key -1 (the dimensions build their keys from the same text rule), so no line is dropped and there are no orphan keys. A line with `included = false` stays in the fact. With the setting switched from true to false the total of every amount column rises by exactly the `exact_duplicate` amount in `silver_excluded_rows`. On the real file: 661,571 rows with the setting true (662,128 - 557) and 662,127 with it false (the stray row only is omitted), 53 columns, 0 orphan keys in either case, no line dated after the as-of date, 120,371 free-goods lines (120,727 with the copies kept), 27,990 blank-Void lines, and lines on the unknown member: 5 for customer and 1,026 for product (1,106 with the copies kept).

## 6. Marts
| Mart | Grain | Used by |
|---|---|---|
| mart_customer_month | customer x month | recovery, dormancy, Customer 360 |
| mart_customer_category_month | customer x category x month | whitespace, cross-sell, Explore |
| mart_customer_profile | customer | buying interval stats, last order, peer group keys |
| mart_peer_category_share | peer group x category | whitespace |
| mart_branch_month | branch x month | Overview, reconciliation vs July 2019 |

Mart rules: built from `v_net_sales` only; months with no sales are
present as rows with 0 where an engine needs continuity (config
`marts.zero_fill`, default true); every mart has a header comment
stating grain and definition.

`mart_customer_month` (story #80, `sql/20_gold/07_mart_customer_month.sql`): grain customer x month, where the month is `dim_date.month_start` and the customer is the fact's `customer_key` (-1, the unknown customer, is kept). Columns: `customer_key`, `month_start`, `net_sales`, `n_lines` and `f_zero_filled`. Net sales and the `included` flag come from `v_net_sales`; the fact supplies each line's customer and date. A line with `included = false` adds nothing, so the mart total equals the fact total of included rows whichever way `duplicates.exclude_from_net_sales` is set. With `marts.zero_fill` true, every month between a customer's own first and last month with sales that has none is present with `net_sales` 0, `n_lines` 0 and `f_zero_filled` true; with false such months are absent. Lines with no usable date have no month and keep a row with a NULL month. On the real file: 12,240 customers (the unknown customer included) over 32 months; with zero fill on, 203,183 rows of which 111,554 are filled; with it off, 91,629 rows; the net sales total equals the fact total of included rows in each case (15,471,215,121.1399 with the copies excluded, 15,473,904,687.2629 with them kept), and the line count equals the included fact rows (661,571 and 662,127).

## 7. Data dictionary outline
Per column: name, table, type, plain-language definition, source
column, rule ID, flags that affect it, example [x]. Generated, plus
hand-written definitions in `config/definitions.yaml` shown in UI
("every number can show its definition").

## 8. Configurable parameters
| Key | Default |
|---|---|
| `net_sales.field` | `Net_Amount_2` |
| `net_sales.candidate_columns` | `Selling_Amount`, `NET_AMOUNT_1`, `AMOUNT_AF_DIS`, `Net_Amount_2`, `Net_AMOUNT_3`, `TAX_AMOUNT` |
| `net_sales.quantity_field` | `Quantity(PCS)` |
| `net_sales.exclude_flags` | `[]`. Each name must be a silver flag column (`revint.silver_schema.SILVER_FLAG_COLUMNS`: the rule flags, `is_duplicate`, `is_excluded` and one `f_bad_<column>` per typed column); a test compares the list with the real silver table. A row with such a flag gets `included = false` in `v_net_sales` and stays in the fact |
| `duplicates.exclude_from_net_sales` | `true` (provisional, owned by spec 01) |
| `marts.zero_fill` | true |
| `calendar.fiscal_year_start_month` | 1 [x] |
| `calendar.date_column` | `Date` (story #75): the typed silver date column that sets the range of `dim_date` |
| `regions.branch_to_region` | empty, from profiling; overrides `regions.source_column` |
| `regions.source_column` | `Region` (story #72): the source column a branch's region defaults to |
| `peer_groups.columns` / `peer_groups.min_size` / `peer_groups.fallback_columns` | `Channel_Category`, `Branch_Name` / 10 / `Channel_Category` (story #72). A group below `min_size` falls back to the group made of `fallback_columns` (a subset of `columns`; empty = no fallback). Only the group definition is here; the whitespace thresholds are spec 03's |
| `product.code_column` / `name_column` / `brand_column` / `category_column` | `SCJ_CODE_1`, `Product_Decription`, `Actual_Brands_1`, `Internal_Category` (story #72). Confirmed from profiling by story #73 (see section 12); the maintainer can change them |

## 9. Edge cases
- Returns/negative values stay in net sales unless excluded by config.
- Free-goods lines (zero value with quantity) stay in the fact, flagged `f_zero_value_with_qty`.
- Blank Void rows stay in the fact with `void_flag = 0`.
- Customer with several branches: attributes taken from latest order;
  branch-level filters use the fact row branch.
- Product without category: category `Unknown`, flagged.
- Dates outside as-of range: kept, flagged `f_after_asof`.

## 10. Acceptance-level checks
- [ ] Config true: fact row count = silver row count - `count(silver_excluded_rows)`; no exact-duplicate extra copy and no stray row in `fact_sales`
- [ ] Config false: fact row count = silver row count - stray rows; no stray row in `fact_sales`
- [ ] Totals reconcile with and without exclusions (spec 01 R7, both forms): config true: SUM over `fact_sales` + SUM over `silver_excluded_rows` = SUM over `silver_sales`; config false: the same with only stray rows added back
- [ ] Switching the config from true to false raises fact totals by exactly the amount of the `exact_duplicate` rows in `silver_excluded_rows`
- [ ] SUM(net_sales) over fact = SUM(chosen silver column) for non-excluded rows
- [ ] Grep test: no SQL outside `v_net_sales` references an amount column
- [ ] Changing config field changes totals as expected (test)
- [ ] Each mart total equals fact total (per grain rollup)
- [ ] Unique surrogate keys; no orphan foreign keys
- [ ] sqlfluff passes; every business rule has a SQL comment
- [ ] Data dictionary lists every gold column

## 11. Dependencies
Spec 01 (silver), spec 10 (config). Feeds 03, 06, 08.

## 12. OPEN QUESTIONS
- OPEN QUESTION: Final net sales field. Default: `Net_Amount_2` (source
  column 46, before the 3% back margin), labelled "provisional" in UI. The
  alternative is `Net_AMOUNT_3` (column 48, after back margin). Why: stated in
  decisions.md.
- DECIDED (provisional, maintainer to confirm in the PR for story #73): Product hierarchy. `uv run python -m revint.product_profile` (counts only, `revint.product_profile`) profiled the six candidate columns on the real file: 662,128 rows, 181 product codes in `SCJ_CODE_1`, 1,107 rows with a blank code (none of them has a category, so they map to the unknown product).
  Brand is `Actual_Brands_1`: it and `Actual_Brands_2` are equal on every row, with 7 values and 4 to 91 products each. It crosses categories (6 of the 7 brands appear under more than one `Internal_Category`), as a brand should. 4 codes have two brand values, 4 have none.
  Category is `Internal_Category`: 40 values with 1 to 25 products each (median 3), 2 codes with two values, 4 codes with none. It nests inside `SCJ_SEGMENT` (17 values): all but one of the 40 categories sit in a single segment, so `SCJ_SEGMENT` is the coarser level and `Internal_Category` the finer one. The finer level gives the whitespace engine more categories per customer; the coarser one is a one-line change (`product.category_column`) if the client prefers it. `FRAGRANCES` (80 values) and `Size` (45 values) are attributes of a product, not categories.
  Code is `SCJ_CODE_1` (`SCJ_CODE_2` has the same 181 values). Name is `Product_Decription` (183 distinct values; 12 codes have more than one name).
  A product code with several values in a column takes the most frequent value; a tie goes to the value on the lowest _source_row.
  No candidate column had a tied value on any code. A code with no value in a column (4 for each candidate) gets category `Unknown` in `dim_product`.
- OPEN QUESTION: Customer identity beyond code (multi-spelling,
  multi-branch). Default: code is identity, variants surfaced as a
  flag. Why: decisions forbid merging near-duplicates.
- OPEN QUESTION: Fiscal calendar? Default: calendar year. Why: none
  stated in docs.
