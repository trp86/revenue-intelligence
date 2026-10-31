-- mart_branch_month: net sales per branch per month (spec 02 section 6, story #84).
-- Grain: one row per branch x month. Month is dim_date.month_start; branch is the fact's
-- branch_key (-1, the unknown branch, is kept). Used by the Overview screen and, later, to
-- reconcile with the July 2019 closing report (spec 01 R5, not part of this story).
-- Definition: net_sales is the sum of net sales over the lines of that branch and month, and
-- n_lines is how many lines that is. Net sales and the included flag come from v_net_sales only
-- (spec 02 N1); the fact supplies each line's branch and date. A line with included = false
-- (net_sales.exclude_flags) adds nothing, so the mart total equals the fact total of included
-- rows whichever way duplicates.exclude_from_net_sales is set. A line with no usable date has no
-- month: its branch keeps a row with a NULL month.
-- Zero fill (marts.zero_fill, $marts_zero_fill): when true, every month between a branch's first
-- and last month with sales that has no sales is present with net_sales 0, n_lines 0 and
-- f_zero_filled true; when false such months are absent. The fill never goes outside a branch's
-- own first and last month.

create or replace table mart_branch_month as
with lines as (
    select
        fact_sales.branch_key,
        dim_date.month_start,
        v_net_sales.net_sales
    from fact_sales
    inner join v_net_sales on fact_sales.sales_line_id = v_net_sales.sales_line_id
    inner join dim_date on fact_sales.date_key = dim_date.date_key
    where v_net_sales.included
),

monthly as (
    select
        branch_key,
        month_start,
        sum(net_sales) as net_sales,
        count(*) as n_lines
    from lines
    group by branch_key, month_start
),

span as (
    -- The first and last month with sales of each branch; undated lines do not count.
    select
        branch_key,
        min(month_start) as first_month,
        max(month_start) as last_month
    from monthly
    where month_start is not null
    group by branch_key
),

months as (
    select distinct month_start
    from dim_date
    where month_start is not null
),

setting as (
    select cast($marts_zero_fill as boolean) as zero_fill
),

filled as (
    -- Months inside a branch's span; empty when zero fill is off.
    select
        span.branch_key,
        months.month_start
    from span
    inner join months
        on months.month_start between span.first_month and span.last_month
    cross join setting
    where setting.zero_fill
),

grid as (
    select
        monthly.branch_key,
        monthly.month_start
    from monthly
    union
    select
        filled.branch_key,
        filled.month_start
    from filled
)

select
    grid.branch_key,
    grid.month_start,
    cast(coalesce(monthly.net_sales, 0) as decimal(38, 4)) as net_sales,
    cast(coalesce(monthly.n_lines, 0) as bigint) as n_lines,
    monthly.n_lines is null as f_zero_filled
from grid
left join monthly
    on
        grid.branch_key = monthly.branch_key
        and grid.month_start is not distinct from monthly.month_start
order by grid.branch_key, grid.month_start;
