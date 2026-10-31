-- mart_peer_category_share: category penetration by peer group (spec 02 section 6, story #83).
-- Grain: one row per peer group x product category. Used by the whitespace engine (spec 03) to
-- see which categories a customer's peers buy that the customer does not.
-- Peer group: the customer's peer_keys from mart_customer_profile, one value per
-- peer_groups.columns column (default channel and branch). Only real customers are peers: the
-- unknown customer (-1) never is one.
-- Fallback: a group with fewer than peer_groups.min_size customers is too small to compare
-- with. Its customers move into the group made of peer_groups.fallback_columns (default the
-- channel alone) and the row says so (f_fallback). Every real customer is in exactly ONE
-- group, so the rows add up to mart_customer_category_month: a customer in a full-size group
-- stays there, it is not also counted in the wider group. A fallback group that is still below
-- min_size is kept and flagged f_below_min_size, as is a small group when there are no fallback
-- columns. If the fallback columns are all of the group columns there is no fallback.
-- Buyer: a customer who bought the category with positive net sales over all months (a return
-- that cancels the sales is not a buyer).
-- Measures: n_peers is the group size, n_buying the buyers, penetration = n_buying / n_peers,
-- median_buyer_net_sales the median of the buyers' net sales in the category (NULL with no
-- buyer), total_net_sales and n_lines the sums over the group's customers. A category nobody
-- in the group has a line in has no row. The category Unknown is kept and flagged.
-- Net sales come from mart_customer_category_month, which reads v_net_sales only (spec 02 N1).
-- Parameters: $peer_groups_columns, $peer_groups_fallback_columns, $peer_groups_min_size.
-- The list lambda below names its variable without a table, which the reference rule cannot see.
-- noqa: disable=RF02

create or replace table mart_peer_category_share as
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
    from mart_customer_profile
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
    -- The fallback group of each customer: the values at the fallback columns' positions.
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
    from mart_customer_category_month
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
    groups.peer_columns,
    groups.peer_keys,
    groups.f_fallback,
    groups.n_peers < plan.min_size as f_below_min_size,
    per_group_category.category,
    groups.n_peers,
    per_group_category.n_buying,
    cast(
        cast(per_group_category.n_buying as decimal(18, 4)) / cast(groups.n_peers as decimal(18, 4))
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
