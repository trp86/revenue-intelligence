-- mart_customer_month: net sales per customer per month (spec 02 section 6, story #80).
-- Grain: one row per customer x month. Month is dim_date.month_start; customer is the
-- customer_key of the fact (-1 is the unknown customer, kept). Used by recovery, dormancy and
-- Customer 360 (spec 03).
-- Definition: net_sales is the sum of net sales over the lines of that customer and month, and
-- n_lines is how many lines that is. Net sales and the included flag come from v_net_sales
-- only (spec 02 N1); the fact supplies the customer and the date of each line. A line with
-- included = false (net_sales.exclude_flags) adds nothing to the mart, so the mart total
-- equals the fact total of included rows, whichever way duplicates.exclude_from_net_sales is
-- set. A line with no usable date has no month: its customer keeps a row with a NULL month.
-- Zero fill (marts.zero_fill, $marts_zero_fill): when true, every month between a customer's
-- first and last month with sales that has no sales is present with net_sales 0, n_lines 0 and
-- f_zero_filled true, so engines that need continuity can rely on it; when false such months
-- are absent. The fill never goes outside a customer's own first and last month.

create or replace table mart_customer_month as
with lines as (
    select
        fact_sales.customer_key,
        dim_date.month_start,
        v_net_sales.net_sales
    from fact_sales
    inner join v_net_sales on fact_sales.sales_line_id = v_net_sales.sales_line_id
    inner join dim_date on fact_sales.date_key = dim_date.date_key
    where v_net_sales.included
),

monthly as (
    select
        customer_key,
        month_start,
        sum(net_sales) as net_sales,
        count(*) as n_lines
    from lines
    group by customer_key, month_start
),

span as (
    -- The first and last month with sales of each customer; undated lines do not count.
    select
        customer_key,
        min(month_start) as first_month,
        max(month_start) as last_month
    from monthly
    where month_start is not null
    group by customer_key
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
    -- Months inside a customer's span; empty when zero fill is off.
    select
        span.customer_key,
        months.month_start
    from span
    inner join months
        on months.month_start between span.first_month and span.last_month
    cross join setting
    where setting.zero_fill
),

grid as (
    select
        monthly.customer_key,
        monthly.month_start
    from monthly
    union
    select
        filled.customer_key,
        filled.month_start
    from filled
)

select
    grid.customer_key,
    grid.month_start,
    cast(coalesce(monthly.net_sales, 0) as decimal(38, 4)) as net_sales,
    cast(coalesce(monthly.n_lines, 0) as bigint) as n_lines,
    monthly.n_lines is null as f_zero_filled
from grid
left join monthly
    on
        grid.customer_key = monthly.customer_key
        and grid.month_start is not distinct from monthly.month_start
order by grid.customer_key, grid.month_start;
