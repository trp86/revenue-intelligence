-- The dormancy engine (spec 03 section 3.2, FR-O2; story #108). A customer is dormant when it
-- has gone quiet compared with its own buying pattern, not a fixed day count. It reads only the
-- as-of inputs (01_asof_inputs.sql), so only data on or before the as-of date is used.
-- Rules, all from config (dormancy.*):
--   evaluated: every customer in asof_customer_profile except the unknown customer (-1), who is
--              never flagged.
--   insufficient_history: fewer than min_orders orders; not scored.
--   dormant when all three hold (each strict, so a customer exactly at a limit does not trigger):
--     beyond_own_interval  days since the last order > interval_multiple x median interval
--     beyond_min_days      days since the last order > min_days
--     sales_in_lookback    positive net sales in the lookback_months months ending with the
--                          month of the last order (the months before it went quiet)
--   gap: the net sales of those lookback months (approved definition).
-- A customer that is not dormant is suppressed with the first test it fails, in the order above.
-- reason_codes on a dormant row list the three tests it met.
-- Parameters: $asof_date, $dormancy_min_orders, $dormancy_interval_multiple, $dormancy_min_days,
-- $dormancy_lookback_months. The column month is a keyword, so RF04 is off for this file.
-- noqa: disable=RF04

alter table opp_dormancy add column last_order_date date;
alter table opp_dormancy add column days_since_last_order bigint;
alter table opp_dormancy add column median_interval_days decimal(18, 4);
alter table opp_dormancy add column n_orders bigint;

create or replace temp table dormancy_tests as
with profile as (
    select
        customer_key,
        last_order_date,
        n_orders,
        median_interval_days,
        date_diff('day', last_order_date, cast($asof_date as date)) as days_since_last_order
    from asof_customer_profile
    where customer_key <> -1
),

lookback as (
    select
        profile.customer_key,
        sum(month.net_sales) as lookback_sales
    from profile
    inner join asof_customer_month as month
        on
            profile.customer_key = month.customer_key
            and month.month_start
            >= cast(
                date_trunc('month', profile.last_order_date)
                - to_months(cast($dormancy_lookback_months as integer) - 1) as date
            )
            and month.month_start <= cast(date_trunc('month', profile.last_order_date) as date)
    group by profile.customer_key
)

select
    profile.customer_key,
    profile.last_order_date,
    profile.days_since_last_order,
    profile.median_interval_days,
    profile.n_orders,
    cast(coalesce(lookback.lookback_sales, 0) as decimal(38, 4)) as lookback_sales,
    profile.n_orders >= $dormancy_min_orders as enough_history,
    coalesce(
        profile.days_since_last_order
        > $dormancy_interval_multiple * profile.median_interval_days,
        false
    ) as beyond_own_interval,
    profile.days_since_last_order > $dormancy_min_days as beyond_min_days,
    coalesce(lookback.lookback_sales, 0) > 0 as sales_in_lookback
from profile
left join lookback on profile.customer_key = lookback.customer_key;

insert into opp_evaluations (type, as_of_date, customer_key, category, outcome)
select
    'dormancy' as type,
    cast($asof_date as date) as as_of_date,
    customer_key,
    null as category,
    case
        when not enough_history then 'insufficient_history'
        when not beyond_own_interval then 'within_own_interval'
        when not beyond_min_days then 'within_min_days'
        when not sales_in_lookback then 'no_sales_in_lookback'
        else 'triggered'
    end as outcome
from dormancy_tests;

insert into opp_dormancy (
    opp_id,
    type,
    customer_key,
    category,
    as_of_date,
    algo_version,
    gap,
    reason_codes,
    last_order_date,
    days_since_last_order,
    median_interval_days,
    n_orders
)
select
    opp_id('dormancy', tests.customer_key, null, cast($asof_date as date)) as opp_id,
    'dormancy' as type,
    tests.customer_key,
    null as category,
    cast($asof_date as date) as as_of_date,
    engine.algo_version,
    tests.lookback_sales as gap,
    ['beyond_own_interval', 'beyond_min_days', 'sales_in_lookback'] as reason_codes,
    tests.last_order_date,
    tests.days_since_last_order,
    tests.median_interval_days,
    tests.n_orders
from dormancy_tests as tests
inner join opp_engines as engine on engine.type = 'dormancy'
where
    tests.enough_history
    and tests.beyond_own_interval
    and tests.beyond_min_days
    and tests.sales_in_lookback;
