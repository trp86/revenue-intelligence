-- mart_customer_profile: one profile row per customer (spec 02 section 6, story #82).
-- Grain: one row per customer (the fact's customer_key; -1, the unknown customer, is kept).
-- Used by recovery, dormancy and whitespace (spec 03). The row says when the customer last
-- ordered, how many orders it has, how often it orders, and which peer group it belongs to.
-- Definitions:
--   order      one distinct customer and date. A date with several lines is ONE order, and the
--              order reference is not used: on the real file one reference is shared by several
--              customers and seen on several dates, so it cannot say what an order is.
--   n_orders   the number of orders. last_order_date is the date of the latest one.
--   interval   the days between a customer's consecutive order dates. median_interval_days and
--              mean_interval_days are over those gaps; both are NULL with fewer than two
--              orders (there is no gap), never an error and never 0.
--   peer_keys  the customer's peer group, one value per peer_groups.columns column in that
--              order, taken from the latest order that has a value (latest date first, then the
--              lowest sales_line_id), as dim_customer takes channel and branch. A blank shows
--              Unknown. The label maps are applied (the normalised twins are read).
--   f_last_order_after_asof  the last order date is after asof.date. The row is kept.
-- Only lines that count are used: a line with included = false (net_sales.exclude_flags)
-- contributes no order, so the customers and their order dates match mart_customer_month.
-- A customer with no dated line keeps a row with no dates and n_orders 0.
-- Parameters: $peer_groups_columns (the source columns), $labels_channel_columns and
-- $labels_branch_columns (their normalised twins), $asof_date.
-- The columns are picked by name, so the identifier rules are switched off for this file.
-- noqa: disable=RF04,RF05,RF06,AM04,ST07,RF02

-- Blank means NULL, empty, or only spaces, tabs, line breaks and non-breaking spaces (the
-- rule silver uses).
create or replace temp macro gold_text(x) as
nullif(trim(x, ' ' || chr(9) || chr(10) || chr(13) || chr(160)), '');

-- The dated lines that count, with the date of each.
create or replace temp table gold_profile_lines as
select
    fact_sales.sales_line_id,
    fact_sales.customer_key,
    dim_date.date as order_date
from fact_sales
inner join v_net_sales on fact_sales.sales_line_id = v_net_sales.sales_line_id
inner join dim_date on fact_sales.date_key = dim_date.date_key
where v_net_sales.included;

-- One row per order: a customer and a date.
create or replace temp table gold_profile_orders as
select
    customer_key,
    order_date
from gold_profile_lines
where order_date is not null
group by customer_key, order_date;

-- The days between consecutive order dates of a customer.
create or replace temp table gold_profile_gaps as
select
    customer_key,
    date_diff(
        'day',
        lag(order_date) over (partition by customer_key order by order_date),
        order_date
    ) as gap_days
from gold_profile_orders;

create or replace temp table gold_profile_intervals as
select
    customer_key,
    median(gap_days) as median_interval_days,
    avg(gap_days) as mean_interval_days
from gold_profile_gaps
where gap_days is not null
group by customer_key;

-- The values of the peer group columns on every counted line, one row per line and column.
-- Each peer_groups.columns name is read through its normalised twin when it is a label column.
create or replace temp table gold_profile_values as
with wanted as (
    select
        unnest(range(1, len($peer_groups_columns) + 1)) as position,
        unnest(cast($peer_groups_columns as varchar[])) as source_column
),

twins as (
    select
        position,
        case
            when
                list_contains($labels_channel_columns, source_column)
                or list_contains($labels_branch_columns, source_column)
                then source_column || '_normalised'
            else source_column
        end as column_name
    from wanted
),

values_long as (
    select
        _source_row as sales_line_id,
        column_name,
        gold_text(value) as value
    from (
        unpivot silver_sales
        on columns(
            lambda c: list_contains(
                list_concat(
                    list_transform($labels_channel_columns, lambda x: x || '_normalised'),
                    list_transform($labels_branch_columns, lambda x: x || '_normalised'),
                    $peer_groups_columns
                ),
                c
            )
        )
        into name column_name value value
    )
)

select
    values_long.sales_line_id,
    twins.position,
    values_long.value
from values_long
inner join twins on values_long.column_name = twins.column_name
where values_long.value is not null;

-- The latest value of each peer column per customer: latest date first, then the lowest
-- sales_line_id; a line with no date comes last.
create or replace temp table gold_profile_peer as
with latest as (
    select
        gold_profile_lines.customer_key,
        gold_profile_values.position,
        gold_profile_values.value,
        row_number() over (
            partition by gold_profile_lines.customer_key, gold_profile_values.position
            order by
                gold_profile_lines.order_date desc nulls last,
                gold_profile_lines.sales_line_id asc
        ) as rank
    from gold_profile_lines
    inner join gold_profile_values
        on gold_profile_lines.sales_line_id = gold_profile_values.sales_line_id
),

customers as (
    select distinct customer_key
    from gold_profile_lines
),

positions as (
    select unnest(range(1, len($peer_groups_columns) + 1)) as position
),

grid as (
    select
        customers.customer_key,
        positions.position
    from customers
    cross join positions
)

select
    grid.customer_key,
    list(coalesce(latest.value, 'Unknown') order by grid.position) as peer_keys
from grid
left join latest
    on
        grid.customer_key = latest.customer_key
        and grid.position = latest.position
        and latest.rank = 1
group by grid.customer_key;

create or replace table mart_customer_profile as
with orders as (
    select
        customer_key,
        count(*) as n_orders,
        max(order_date) as last_order_date
    from gold_profile_orders
    group by customer_key
),

customers as (
    select distinct customer_key
    from gold_profile_lines
)

select
    customers.customer_key,
    orders.last_order_date,
    cast(coalesce(orders.n_orders, 0) as bigint) as n_orders,
    cast(intervals.median_interval_days as decimal(18, 4)) as median_interval_days,
    cast(intervals.mean_interval_days as decimal(18, 4)) as mean_interval_days,
    peer.peer_keys,
    coalesce(orders.last_order_date > cast($asof_date as date), false)
        as f_last_order_after_asof
from customers
left join orders on customers.customer_key = orders.customer_key
left join gold_profile_intervals as intervals on customers.customer_key = intervals.customer_key
left join gold_profile_peer as peer on customers.customer_key = peer.customer_key
order by customers.customer_key;
