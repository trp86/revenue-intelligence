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
| N2 | Net sales column = `config.net_sales.field` (default `Net AMOUNT`, provisional). Must be one of the six candidate columns, else the build fails |
| N3 | Row inclusion driven by config: `net_sales.exclude_flags` (default empty list). Rows excluded in silver (`is_excluded`: the stray row, and exact-duplicate extra copies while `duplicates.exclude_from_net_sales` is true) never reach `fact_sales`, so the view needs no extra filter for them |
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
Silver rows with `is_excluded = true` are omitted: the stray row always, exact-duplicate extra copies when `duplicates.exclude_from_net_sales` is true. When it is false, copies stay in the fact with `is_duplicate = true`. The fact keeps `void_flag`, `is_duplicate` and the other flags.
Check: fact row count = silver row count - `count(silver.excluded_rows)` (duplicates counted only when the config is true).

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
| `net_sales.field` | `Net AMOUNT` |
| `net_sales.exclude_flags` | `[]` |
| `duplicates.exclude_from_net_sales` | `true` (provisional, owned by spec 01) |
| `marts.zero_fill` | true |
| `calendar.fiscal_year_start_month` | 1 [x] |
| `regions.branch_to_region` | empty, from profiling |

## 9. Edge cases
- Returns/negative values stay in net sales unless excluded by config.
- Free-goods lines (zero value with quantity) stay in the fact, flagged `f_zero_value_with_qty`.
- Blank Void rows stay in the fact with `void_flag = 0`.
- Customer with several branches: attributes taken from latest order;
  branch-level filters use the fact row branch.
- Product without category: category `Unknown`, flagged.
- Dates outside as-of range: kept, flagged `f_after_asof`.

## 10. Acceptance-level checks
- [ ] Fact row count = silver row count - `count(silver.excluded_rows)`; no exact-duplicate extra copy and no stray row in `fact_sales`
- [ ] Totals reconcile with and without exclusions: SUM over `fact_sales` + SUM over `silver.excluded_rows` = SUM over `silver_sales`
- [ ] With `duplicates.exclude_from_net_sales = false`, the fact includes the copies and totals rise by exactly the excluded duplicate amount
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
- OPEN QUESTION: Final net sales field. Default: Net AMOUNT, labelled
  "provisional" in UI. Why: stated in decisions.md.
- OPEN QUESTION: Product hierarchy: which source columns give brand
  and category? Default: derive from profiling, record in config.
  Why: whitespace needs a category level.
- OPEN QUESTION: Customer identity beyond code (multi-spelling,
  multi-branch). Default: code is identity, variants surfaced as a
  flag. Why: decisions forbid merging near-duplicates.
- OPEN QUESTION: Fiscal calendar? Default: calendar year. Why: none
  stated in docs.
