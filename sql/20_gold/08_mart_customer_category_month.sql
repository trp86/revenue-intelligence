-- mart_customer_category_month: net sales per customer, product category and month (spec 02
-- section 6, story #81).
-- Grain: one row per customer x category x month. Month is dim_date.month_start, the category
-- is dim_product.category through the fact (a line with no product, or a product with no
-- category, falls in the category Unknown), and the customer is the fact's customer_key (-1,
-- the unknown customer, is kept). Used by whitespace, cross-sell and Explore (spec 03).
-- Definition: net_sales is the sum of net sales over the lines of that customer, category and
-- month, and n_lines is how many lines that is. Net sales and the included flag come from
-- v_net_sales only (spec 02 N1); the fact supplies each line's customer, product and date. A
-- line with included = false adds nothing, so the mart total equals the fact total of included
-- rows whichever way duplicates.exclude_from_net_sales is set, and summing the mart over
-- category gives mart_customer_month. A line with no usable date has no month and keeps a row
-- with a NULL month.
-- f_unknown_category marks the rows of the category Unknown: they are kept, not dropped, so the
-- totals stay whole.
-- Zero fill (marts.zero_fill, $marts_zero_fill): when true, every month between the first and
-- the last month with sales of a customer AND category that has none is present with net_sales
-- 0, n_lines 0 and f_zero_filled true, so an engine can see how long a customer has not bought
-- a category; when false such months are absent. The fill is per customer and category, not
-- per customer, so it never adds months in categories the customer has not bought.

create or replace table mart_customer_category_month as
with lines as (
    select
        fact_sales.customer_key,
        coalesce(dim_product.category, 'Unknown') as category,
        dim_date.month_start,
        v_net_sales.net_sales
    from fact_sales
    inner join v_net_sales on fact_sales.sales_line_id = v_net_sales.sales_line_id
    inner join dim_date on fact_sales.date_key = dim_date.date_key
    inner join dim_product on fact_sales.product_key = dim_product.product_key
    where v_net_sales.included
),

monthly as (
    select
        customer_key,
        category,
        month_start,
        sum(net_sales) as net_sales,
        count(*) as n_lines
    from lines
    group by customer_key, category, month_start
),

span as (
    -- The first and last month with sales of each customer and category; undated lines do not
    -- count.
    select
        customer_key,
        category,
        min(month_start) as first_month,
        max(month_start) as last_month
    from monthly
    where month_start is not null
    group by customer_key, category
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
    -- Months inside a customer-and-category span; empty when zero fill is off.
    select
        span.customer_key,
        span.category,
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
        monthly.category,
        monthly.month_start
    from monthly
    union
    select
        filled.customer_key,
        filled.category,
        filled.month_start
    from filled
)

select
    grid.customer_key,
    grid.category,
    grid.month_start,
    cast(coalesce(monthly.net_sales, 0) as decimal(38, 4)) as net_sales,
    cast(coalesce(monthly.n_lines, 0) as bigint) as n_lines,
    monthly.n_lines is null as f_zero_filled,
    grid.category = 'Unknown' as f_unknown_category
from grid
left join monthly
    on
        grid.customer_key = monthly.customer_key
        and grid.category = monthly.category
        and grid.month_start is not distinct from monthly.month_start
order by grid.customer_key, grid.category, grid.month_start;
