-- fact_sales: one row per sales line that gold loads (spec 02 section 5, story #79).
-- Grain: one silver order line. sales_line_id is the silver _source_row. The rows are exactly
-- the rows of v_net_sales: the stray row is never loaded, and the extra copies of exact
-- duplicates are loaded only when duplicates.exclude_from_net_sales is false (they keep
-- is_duplicate = true). A line with included = false (net_sales.exclude_flags) stays.
-- Net sales, quantity and every amount come from v_net_sales, so this file names no source
-- amount column. The keys come from the dimensions; a line whose date, customer, product or
-- branch is blank or not in its dimension gets the unknown member (-1), so no line is dropped.
-- Every silver flag is carried over unchanged, so a line keeps all it was marked with: the
-- rule flags, the f_bad_ flags, is_duplicate, is_excluded and void_flag. Silver marks
-- is_excluded the same way for either setting; a kept copy still shows is_excluded = true.
-- Parameters:
--   $customers_code_column, $product_code_column     the code columns the dimensions use
--   $labels_branch_columns                           the branch label column (normalised twin)
--   $calendar_date_column                            the typed date column
--   $silver_flag_columns                             the silver flag columns (a list)
-- The columns are picked by name, so the identifier rules are switched off for this file.
-- noqa: disable=RF04,RF05,RF06,AM04,ST07,RF02

-- Blank means NULL, empty, or only spaces, tabs, line breaks and non-breaking spaces (the
-- rule silver uses). The same text rule builds the dimensions, so the keys match.
create or replace temp macro gold_text(x) as
nullif(trim(x, ' ' || chr(9) || chr(10) || chr(13) || chr(160)), '');

-- The natural keys of each silver line: what the dimensions are looked up by.
create or replace temp table gold_fact_keys as
with customers as (
    select
        _source_row,
        gold_text(columns(lambda c: c = $customers_code_column)) as customer_code
    from silver_sales
),

products as (
    select
        _source_row,
        gold_text(columns(lambda c: c = $product_code_column)) as product_code
    from silver_sales
),

branches as (
    select
        _source_row,
        gold_text(
            columns(
                lambda c: list_contains(
                    list_transform($labels_branch_columns, lambda x: x || '_normalised'), c
                )
            )
        ) as branch_name
    from silver_sales
),

dates as (
    select
        _source_row,
        columns(lambda c: c = $calendar_date_column) as order_date
    from silver_sales
)

select
    customers._source_row,
    customers.customer_code,
    products.product_code,
    branches.branch_name,
    dates.order_date
from customers
inner join products on customers._source_row = products._source_row
inner join branches on customers._source_row = branches._source_row
inner join dates on customers._source_row = dates._source_row;

-- Every silver flag, by the list in revint.silver_schema, plus void_flag.
create or replace temp table gold_fact_flags as
select
    _source_row,
    void_flag,
    columns(lambda c: list_contains($silver_flag_columns, c))
from silver_sales;

-- A flag in the list that silver does not have would be skipped without a word, so the number
-- of flag columns found must equal the length of the list.
select
    case
        when
            count(*) - 2 <> len($silver_flag_columns)
            then error(
                'fact_sales found ' || cast(count(*) - 2 as varchar) || ' of '
                || cast(len($silver_flag_columns) as varchar)
                || ' silver flag columns; the list in revint.silver_schema is out of date'
            )
    end as every_flag_found
from information_schema.columns
where table_name = 'gold_fact_flags';

create or replace table fact_sales as
select
    lines.sales_line_id,
    coalesce(dim_date.date_key, -1) as date_key,
    coalesce(dim_customer.customer_key, -1) as customer_key,
    coalesce(dim_product.product_key, -1) as product_key,
    coalesce(dim_branch.branch_key, -1) as branch_key,
    lines.quantity,
    lines.net_sales,
    lines.included,
    -- The amount_ columns of v_net_sales, one per candidate column.
    lines.* exclude (sales_line_id, net_sales, net_sales_field_used, included, quantity),
    flags.void_flag,
    flags.* exclude (_source_row, void_flag),
    -- f_after_asof: the line is dated after asof.date (from dim_date). The line is kept.
    coalesce(dim_date.f_after_asof, false) as f_after_asof
from v_net_sales as lines
inner join gold_fact_keys as keys on lines.sales_line_id = keys._source_row
inner join gold_fact_flags as flags on lines.sales_line_id = flags._source_row
left join dim_date on keys.order_date = dim_date.date
left join dim_customer on keys.customer_code = dim_customer.customer_code
left join dim_product on keys.product_code = dim_product.product_code
left join dim_branch on keys.branch_name = dim_branch.branch_name
order by lines.sales_line_id;

-- The fact has one row per line of v_net_sales: a join that dropped or multiplied a line fails
-- the stage and rolls it back.
with fact as (
    select count(*) as n
    from fact_sales
),

lines as (
    select count(*) as n
    from v_net_sales
)

select
    case
        when
            fact.n <> lines.n
            then error(
                'fact_sales has ' || cast(fact.n as varchar) || ' rows but v_net_sales has '
                || cast(lines.n as varchar)
            )
    end as same_row_count
from fact
cross join lines;
