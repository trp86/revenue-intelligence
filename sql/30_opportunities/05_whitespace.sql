-- The whitespace engine (spec 03 section 3.3, FR-O3; story #110). Categories a customer's peers
-- buy and the customer does not. It reads only the as-of inputs, so only data on or before the
-- as-of date is used. The peer group is asof_peer_assigned (01_asof_inputs.sql): peer_groups
-- columns, with the fallback group when the full group is below peer_groups.min_size.
-- Measures, as in asof_peer_category_share (every sale up to the as-of date):
--   a peer buys a category when its net sales in it are above zero
--   peer penetration = buying peers / peers, judged for each customer WITHOUT the customer
--   itself (it is not counted among its own peers)
--   gap = the median net sales in the category per buying peer (again without the customer),
--   with no uplift
-- Whitespace when peer penetration >= whitespace.min_peer_penetration AND the customer has no
-- sales line in the category in the whitespace.lookback_months months ending with the as-of
-- month. The category 'Unknown' is never whitespace and is not evaluated, nor is the unknown
-- customer (-1).
-- Evaluated: each customer and each category bought by anyone in its peer group. One that does
-- not trigger is suppressed with the first reason that applies: no_peers (the customer is alone
-- in its group), below_min_penetration, bought_in_lookback.
-- reason_codes on a triggered row: peer_penetration_at_least_min, not_bought_in_lookback, plus
-- peer_fallback when the group fell back to the wider group, and peer_group_below_min_size when
-- the group used is still below peer_groups.min_size (E3-10 caps the confidence).
-- Parameters: $asof_date, $whitespace_min_peer_penetration, $whitespace_lookback_months,
-- $peer_groups_min_size. The column type is a keyword, so RF04 is off for this file;
-- AM04 too, for the select * of whitespace_triggered.
-- noqa: disable=RF04,AM04

alter table opp_whitespace add column peer_penetration decimal(9, 4);
alter table opp_whitespace add column n_peers bigint;
alter table opp_whitespace add column n_buying_peers bigint;
alter table opp_whitespace add column f_fallback boolean;
alter table opp_whitespace add column f_below_min_size boolean;

-- Each known customer's net sales and lines per category, over every month up to the as-of.
create or replace temp table whitespace_customer_category as
select
    customer_key,
    category,
    sum(net_sales) as net_sales,
    sum(n_lines) as n_lines
from asof_customer_category_month
where customer_key <> -1
group by customer_key, category
having sum(n_lines) > 0;

-- The categories each customer has a line in, in the lookback months.
create or replace temp table whitespace_recent as
select distinct
    customer_key,
    category
from asof_customer_category_month
where
    customer_key <> -1
    and n_lines > 0
    and month_start
    >= cast(
        date_trunc('month', cast($asof_date as date))
        - to_months(cast($whitespace_lookback_months as integer) - 1) as date
    )
    and month_start <= cast(date_trunc('month', cast($asof_date as date)) as date);

create or replace temp table whitespace_groups as
select
    peer_columns,
    peer_keys,
    count(*) as n_members
from asof_peer_assigned
group by peer_columns, peer_keys;

-- Buyers of each category per peer group, with the median net sales per buyer.
create or replace temp table whitespace_group_category as
select
    assigned.peer_columns,
    assigned.peer_keys,
    cc.category,
    count(*) filter (where cc.net_sales > 0) as n_buying,
    median(cc.net_sales) filter (where cc.net_sales > 0) as median_buyer_net_sales
from asof_peer_assigned as assigned
inner join whitespace_customer_category as cc on assigned.customer_key = cc.customer_key
where cc.category <> 'Unknown'
group by assigned.peer_columns, assigned.peer_keys, cc.category
having count(*) filter (where cc.net_sales > 0) > 0;

create or replace temp table whitespace_tests as
with pairs as (
    select
        assigned.customer_key,
        assigned.f_fallback,
        assigned.peer_columns,
        assigned.peer_keys,
        gc.category,
        groups.n_members,
        coalesce(own.net_sales > 0, false) as self_buys,
        gc.n_buying,
        gc.median_buyer_net_sales,
        recent.customer_key is not null as bought_in_lookback
    from asof_peer_assigned as assigned
    inner join whitespace_groups as groups
        on
            assigned.peer_columns = groups.peer_columns
            and assigned.peer_keys = groups.peer_keys
    inner join whitespace_group_category as gc
        on
            assigned.peer_columns = gc.peer_columns
            and assigned.peer_keys = gc.peer_keys
    left join whitespace_customer_category as own
        on
            assigned.customer_key = own.customer_key
            and gc.category = own.category
    left join whitespace_recent as recent
        on
            assigned.customer_key = recent.customer_key
            and gc.category = recent.category
)

select
    customer_key,
    category,
    f_fallback,
    peer_columns,
    peer_keys,
    n_members < $peer_groups_min_size as f_below_min_size,
    self_buys,
    median_buyer_net_sales,
    bought_in_lookback,
    n_members - 1 as n_peers,
    n_buying - cast(self_buys as bigint) as n_buying_peers,
    case
        when n_members > 1
            then cast(
                cast(n_buying - cast(self_buys as bigint) as decimal(18, 4))
                / cast(n_members - 1 as decimal(18, 4))
                as decimal(9, 4)
            )
    end as peer_penetration
from pairs;

insert into opp_evaluations (type, as_of_date, customer_key, category, outcome)
select
    'whitespace' as type,
    cast($asof_date as date) as as_of_date,
    customer_key,
    category,
    case
        when n_peers = 0 then 'no_peers'
        when peer_penetration < $whitespace_min_peer_penetration then 'below_min_penetration'
        when bought_in_lookback then 'bought_in_lookback'
        else 'triggered'
    end as outcome
from whitespace_tests;

-- The gap of a triggered pair, without the customer itself. A customer that bought the
-- category before the lookback is among the group's buyers, so its median is taken again
-- without it; otherwise the group median already leaves it out.
create or replace temp table whitespace_triggered as
select *
from whitespace_tests
where
    n_peers > 0
    and peer_penetration >= $whitespace_min_peer_penetration
    and not bought_in_lookback;

create or replace temp table whitespace_gap as
select
    triggered.customer_key,
    triggered.category,
    case
        when triggered.self_buys
            then (
                select median(cc.net_sales)
                from asof_peer_assigned as peer
                inner join whitespace_customer_category as cc
                    on peer.customer_key = cc.customer_key
                where
                    peer.peer_columns = triggered.peer_columns
                    and peer.peer_keys = triggered.peer_keys
                    and peer.customer_key <> triggered.customer_key
                    and cc.category = triggered.category
                    and cc.net_sales > 0
            )
        else triggered.median_buyer_net_sales
    end as gap
from whitespace_triggered as triggered;

insert into opp_whitespace (
    opp_id,
    type,
    customer_key,
    category,
    as_of_date,
    algo_version,
    gap,
    reason_codes,
    peer_penetration,
    n_peers,
    n_buying_peers,
    f_fallback,
    f_below_min_size
)
select
    opp_id(
        'whitespace', triggered.customer_key, triggered.category, cast($asof_date as date)
    ) as opp_id,
    'whitespace' as type,
    triggered.customer_key,
    triggered.category,
    cast($asof_date as date) as as_of_date,
    engine.algo_version,
    cast(gap.gap as decimal(38, 4)) as gap,
    list_concat(
        ['peer_penetration_at_least_min', 'not_bought_in_lookback'],
        case when triggered.f_fallback then ['peer_fallback'] else [] end,
        case when triggered.f_below_min_size then ['peer_group_below_min_size'] else [] end
    ) as reason_codes,
    triggered.peer_penetration,
    triggered.n_peers,
    triggered.n_buying_peers,
    triggered.f_fallback,
    triggered.f_below_min_size
from whitespace_triggered as triggered
inner join whitespace_gap as gap
    on
        triggered.customer_key = gap.customer_key
        and triggered.category = gap.category
inner join opp_engines as engine on engine.type = 'whitespace';
