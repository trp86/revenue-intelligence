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

## 4. Dimensions
| Table | Key | Key attributes |
|---|---|---|
| dim_customer | `customer_key` (surrogate), `customer_code` | name (most frequent spelling), `n_name_variants`, `n_branches`, channel, first/last order date, `f_multi_identity` |
| dim_product | `product_key`, `product_code` | name, brand, category [x] (source columns TBD) |
| dim_branch | `branch_key` | normalised name, region (config mapping) |
| dim_date | `date_key` | date, week, month, quarter, year, month_start; fiscal fields if config enables |

Rules: surrogate keys deterministic (hash of natural key); unknown
members use key `-1` rather than dropping rows; near-duplicate
customer codes remain separate rows.

## 5. Fact
`fact_sales`: `sales_line_id` (from `_source_row`), `date_key`, `customer_key`,
`product_key`, `branch_key`, quantity, all six amount columns,
`net_sales` (from view), all silver flags.
Silver marks `is_excluded` the same way for both settings of the config (spec 01 S5). Gold omits the stray row always, and the exact-duplicate extra copies when `duplicates.exclude_from_net_sales` is true. When it is false, copies stay in the fact with `is_duplicate = true`. The fact keeps `void_flag`, `is_duplicate` and the other flags.
Check: with the config true, fact row count = silver row count - `count(silver_excluded_rows)`; with false, fact row count = silver row count - stray rows.

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
