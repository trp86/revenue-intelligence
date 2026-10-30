-- Customer codes (spec 01 S4). Customer identity is an open business question, so this
-- table only makes the problem visible. It does not decide anything:
--
--   the code is the key        one row per distinct customer code, taken exactly as it is
--                              written in the sheet (case and spaces included).
--   spellings and branches     name_count and branch_count are the numbers of distinct
--                              non-blank names and branches seen for the code. A name that
--                              differs by case or a space is another spelling.
--   near-duplicate codes       near_duplicate_count is how many OTHER codes in the table equal
--                              this one once spaces at both ends are trimmed and the case is
--                              ignored. They are counted and never merged: each keeps its own
--                              row and its own counts.
--
-- The code, name and branch columns are config (customers.code_column, name_column and
-- branch_column), passed as $customers_code_column, $customers_name_column and
-- $customers_branch_column. Their bronze names are mixed case, so they are picked by name.
--
-- Counts are over the order lines that silver keeps (is_excluded is false): an excluded
-- duplicate or the stray row adds nothing. A row with a blank code gets no row here.
-- The table holds counts only. It has the customer code, which is already in silver and the
-- warehouse; it is never printed to issues, PRs or logs.

create or replace temp table customer_lines as
select
    _source_row,
    columns(lambda c: c = $customers_code_column) as customer_code,
    columns(lambda c: c = $customers_name_column) as customer_name,
    columns(lambda c: c = $customers_branch_column) as branch_name
from silver_sales
where not is_excluded;

create or replace table silver_customer_codes as
with per_code as (
    select
        customer_code,
        count(*) as order_lines,
        count(distinct customer_name) filter (where silver_text(customer_name) is not null)
            as name_count,
        count(distinct branch_name) filter (where silver_text(branch_name) is not null)
            as branch_count
    from customer_lines
    where silver_text(customer_code) is not null
    group by customer_code
),

folded as (
    select
        customer_code,
        upper(trim(customer_code)) as folded_code
    from per_code
),

near as (
    select
        customer_code,
        count(*) over (partition by folded_code) - 1 as near_duplicate_count
    from folded
)

select
    per_code.customer_code,
    per_code.order_lines,
    per_code.name_count,
    per_code.branch_count,
    near.near_duplicate_count,
    per_code.name_count > 1 as f_multiple_names,
    per_code.branch_count > 1 as f_multiple_branches
from per_code
inner join near on per_code.customer_code = near.customer_code
order by per_code.customer_code;
