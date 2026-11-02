-- As-of inputs of the opportunity engines (spec 03 section 1, spec 04 P1; story #106).
-- The engines read only these tables, never the all-data marts: mart_customer_profile and
-- mart_peer_category_share are computed over every sale, so an engine run for an earlier as-of
-- date would see the future through them. Each table here repeats the logic of the mart named
-- below with one difference: only sales lines dated on or before the as-of date count. At the
-- last day of the data the tables equal the marts (a test checks it).
--   asof_orders                   one row per customer and order date (an order is a distinct
--                                 customer and date, as in mart_customer_profile)
--   asof_customer_month           as mart_customer_month
--   asof_customer_category_month  as mart_customer_category_month
--   asof_customer_profile         as mart_customer_profile (last order, orders, intervals,
--                                 peer keys)
--   asof_peer_category_share      as mart_peer_category_share
-- Every table carries as_of_date, the date it was built for. A sales line with no date cannot be
-- placed before the as-of date, so it is left out (the marts keep it with a NULL month). Lines
-- with included = false (net_sales.exclude_flags) add nothing, as in the marts. Net sales come
-- from v_net_sales (spec 02 N1); the fact supplies customer, product and date.
-- Parameters: $asof_date, $marts_zero_fill, $peer_groups_columns, $peer_groups_min_size,
-- $peer_groups_fallback_columns, $labels_channel_columns, $labels_branch_columns.
-- The columns are picked by name and the list lambdas name their variable without a table, so
-- the identifier and reference rules are switched off for this file.
-- noqa: disable=RF04,RF05,RF06,AM04,ST07,RF02

-- Blank means NULL, empty, or only spaces, tabs, line breaks and non-breaking spaces (the rule
-- silver uses).
create or replace temp macro asof_text(x) as
nullif(trim(x, ' ' || chr(9) || chr(10) || chr(13) || chr(160)), '');

-- The sales lines that count: included, and dated on or before the as-of date.
create or replace temp table asof_lines as
select
    fact_sales.sales_line_id,
    fact_sales.customer_key,
    coalesce(dim_product.category, 'Unknown') as category,
    dim_date.date as order_date,
    dim_date.month_start,
    v_net_sales.net_sales
from fact_sales
inner join v_net_sales on fact_sales.sales_line_id = v_net_sales.sales_line_id
inner join dim_date on fact_sales.date_key = dim_date.date_key
inner join dim_product on fact_sales.product_key = dim_product.product_key
where
    v_net_sales.included
    and dim_date.date is not null
    and dim_date.date <= cast($asof_date as date);

-- One row per order: a customer and a date, with the net sales and lines of that day.
create or replace table asof_orders as
select
    cast($asof_date as date) as as_of_date,
    customer_key,
    order_date,
    cast(sum(net_sales) as decimal(38, 4)) as net_sales,
    cast(count(*) as bigint) as n_lines
from asof_lines
group by customer_key, order_date
order by customer_key, order_date;

-- The months of dim_date up to the month of the as-of date, for the zero fill.
create or replace temp table asof_months as
select distinct month_start
from dim_date
where
    month_start is not null
    and month_start <= cast(date_trunc('month', cast($asof_date as date)) as date);

-- As mart_customer_month: customer x month, zero filled inside each customer's own span.
create or replace table asof_customer_month as
with monthly as (
    select
        customer_key,
        month_start,
        sum(net_sales) as net_sales,
        count(*) as n_lines
    from asof_lines
    group by customer_key, month_start
),

span as (
    select
        customer_key,
        min(month_start) as first_month,
        max(month_start) as last_month
    from monthly
    group by customer_key
),

setting as (
    select cast($marts_zero_fill as boolean) as zero_fill
),

filled as (
    select
        span.customer_key,
        asof_months.month_start
    from span
    inner join asof_months
        on asof_months.month_start between span.first_month and span.last_month
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
    cast($asof_date as date) as as_of_date,
    grid.customer_key,
    grid.month_start,
    cast(coalesce(monthly.net_sales, 0) as decimal(38, 4)) as net_sales,
    cast(coalesce(monthly.n_lines, 0) as bigint) as n_lines,
    monthly.n_lines is null as f_zero_filled
from grid
left join monthly
    on
        grid.customer_key = monthly.customer_key
        and grid.month_start = monthly.month_start
order by grid.customer_key, grid.month_start;

-- As mart_customer_category_month: customer x category x month, zero filled per customer and
-- category.
create or replace table asof_customer_category_month as
with monthly as (
    select
        customer_key,
        category,
        month_start,
        sum(net_sales) as net_sales,
        count(*) as n_lines
    from asof_lines
    group by customer_key, category, month_start
),

span as (
    select
        customer_key,
        category,
        min(month_start) as first_month,
        max(month_start) as last_month
    from monthly
    group by customer_key, category
),

setting as (
    select cast($marts_zero_fill as boolean) as zero_fill
),

filled as (
    select
        span.customer_key,
        span.category,
        asof_months.month_start
    from span
    inner join asof_months
        on asof_months.month_start between span.first_month and span.last_month
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
    cast($asof_date as date) as as_of_date,
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
        and grid.month_start = monthly.month_start
order by grid.customer_key, grid.category, grid.month_start;

-- The peer column values of every counted line, one row per line and column (as in
-- mart_customer_profile). A label column is read through its normalised twin.
create or replace temp table asof_peer_values as
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
        asof_text(value) as value
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
inner join asof_lines on values_long.sales_line_id = asof_lines.sales_line_id
where values_long.value is not null;

-- As mart_customer_profile: last order, number of orders, intervals and peer keys.
create or replace table asof_customer_profile as
with gaps as (
    select
        customer_key,
        date_diff(
            'day',
            lag(order_date) over (partition by customer_key order by order_date),
            order_date
        ) as gap_days
    from asof_orders
),

intervals as (
    select
        customer_key,
        median(gap_days) as median_interval_days,
        avg(gap_days) as mean_interval_days
    from gaps
    where gap_days is not null
    group by customer_key
),

orders as (
    select
        customer_key,
        count(*) as n_orders,
        max(order_date) as last_order_date
    from asof_orders
    group by customer_key
),

latest as (
    select
        asof_lines.customer_key,
        asof_peer_values.position,
        asof_peer_values.value,
        row_number() over (
            partition by asof_lines.customer_key, asof_peer_values.position
            order by asof_lines.order_date desc, asof_lines.sales_line_id asc
        ) as rank
    from asof_lines
    inner join asof_peer_values on asof_lines.sales_line_id = asof_peer_values.sales_line_id
),

positions as (
    select unnest(range(1, len($peer_groups_columns) + 1)) as position
),

grid as (
    select
        orders.customer_key,
        positions.position
    from orders
    cross join positions
),

peer as (
    select
        grid.customer_key,
        list(coalesce(latest.value, 'Unknown') order by grid.position) as peer_keys
    from grid
    left join latest
        on
            grid.customer_key = latest.customer_key
            and grid.position = latest.position
            and latest.rank = 1
    group by grid.customer_key
)

select
    cast($asof_date as date) as as_of_date,
    orders.customer_key,
    orders.last_order_date,
    cast(orders.n_orders as bigint) as n_orders,
    cast(intervals.median_interval_days as decimal(18, 4)) as median_interval_days,
    cast(intervals.mean_interval_days as decimal(18, 4)) as mean_interval_days,
    peer.peer_keys
from orders
left join intervals on orders.customer_key = intervals.customer_key
left join peer on orders.customer_key = peer.customer_key
order by orders.customer_key;

-- The peer group of every known customer, with the same fallback as mart_peer_category_share
-- (temp: the share below and the whitespace engine read it, so the rule is written once).
create or replace temp table asof_peer_assigned as
with setting as (
    select
        cast($peer_groups_min_size as bigint) as min_size,
        cast($peer_groups_columns as varchar[]) as group_columns,
        cast($peer_groups_fallback_columns as varchar[]) as fallback_columns
),

plan as (
    select
        min_size,
        group_columns,
        fallback_columns,
        len(fallback_columns) > 0 and len(fallback_columns) < len(group_columns) as use_fallback,
        list_transform(fallback_columns, lambda c: list_position(group_columns, c))
            as fallback_positions
    from setting
),

peers as (
    select
        customer_key,
        peer_keys
    from asof_customer_profile
    where customer_key <> -1
),

sizes as (
    select
        peer_keys,
        count(*) as full_size
    from peers
    group by peer_keys
),

fallback_keys as (
    select
        peers.customer_key,
        list_transform(
            plan.fallback_positions, lambda p: list_extract(peers.peer_keys, p)
        ) as fallback_keys
    from peers
    cross join plan
),

assigned as (
    select
        peers.customer_key,
        plan.use_fallback and sizes.full_size < plan.min_size as f_fallback,
        case
            when plan.use_fallback and sizes.full_size < plan.min_size
                then plan.fallback_columns
            else plan.group_columns
        end as peer_columns,
        case
            when plan.use_fallback and sizes.full_size < plan.min_size
                then fallback_keys.fallback_keys
            else peers.peer_keys
        end as peer_keys
    from peers
    inner join sizes on peers.peer_keys = sizes.peer_keys
    inner join fallback_keys on peers.customer_key = fallback_keys.customer_key
    cross join plan
)

select
    customer_key,
    f_fallback,
    peer_columns,
    peer_keys
from assigned;

-- As mart_peer_category_share: category penetration by peer group, with the same fallback.
create or replace table asof_peer_category_share as
with plan as (
    select cast($peer_groups_min_size as bigint) as min_size
),

assigned as (
    select
        customer_key,
        f_fallback,
        peer_columns,
        peer_keys
    from asof_peer_assigned
),

groups as (
    select
        peer_columns,
        peer_keys,
        f_fallback,
        count(*) as n_peers
    from assigned
    group by peer_columns, peer_keys, f_fallback
),

customer_category as (
    select
        customer_key,
        category,
        sum(net_sales) as net_sales,
        sum(n_lines) as n_lines
    from asof_customer_category_month
    where customer_key <> -1
    group by customer_key, category
    having sum(n_lines) > 0
),

per_group_category as (
    select
        assigned.peer_columns,
        assigned.peer_keys,
        customer_category.category,
        count(*) filter (where customer_category.net_sales > 0) as n_buying,
        median(customer_category.net_sales) filter (where customer_category.net_sales > 0)
            as median_buyer_net_sales,
        sum(customer_category.net_sales) as total_net_sales,
        sum(customer_category.n_lines) as n_lines
    from assigned
    inner join customer_category on assigned.customer_key = customer_category.customer_key
    group by assigned.peer_columns, assigned.peer_keys, customer_category.category
)

select
    cast($asof_date as date) as as_of_date,
    groups.peer_columns,
    groups.peer_keys,
    groups.f_fallback,
    groups.n_peers < plan.min_size as f_below_min_size,
    per_group_category.category,
    groups.n_peers,
    per_group_category.n_buying,
    cast(
        cast(per_group_category.n_buying as decimal(18, 4))
        / cast(groups.n_peers as decimal(18, 4))
        as decimal(9, 4)
    ) as penetration,
    cast(per_group_category.median_buyer_net_sales as decimal(38, 4)) as median_buyer_net_sales,
    cast(per_group_category.total_net_sales as decimal(38, 4)) as total_net_sales,
    cast(per_group_category.n_lines as bigint) as n_lines,
    per_group_category.category = 'Unknown' as f_unknown_category
from groups
inner join per_group_category
    on
        groups.peer_columns = per_group_category.peer_columns
        and groups.peer_keys = per_group_category.peer_keys
cross join plan;
