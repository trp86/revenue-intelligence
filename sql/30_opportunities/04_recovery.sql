-- The recovery engine (spec 03 section 3.1, FR-O1; story #109). A customer whose net sales fell
-- against the same months one year earlier, so a seasonal dip is not a decline. It reads only
-- the as-of inputs, so only data on or before the as-of date is used, and runs after
-- 03_dormancy.sql: a dormant customer is left to dormancy (no customer is in both).
-- Windows, from config (recovery.*):
--   current  from the first day of the month window_months - 1 months before the as-of month,
--            to the as-of date
--   prior    the same dates one year earlier
-- Rules: decline_pct = (prior - current) / prior x 100. A customer triggers when
--   decline_pct >= min_decline_pct AND prior net sales >= min_prior_sales AND prior orders >=
--   min_prior_orders (all "at least", so a customer just below a limit does not trigger).
--   gap: prior - current net sales.
-- Evaluated: every customer in asof_customer_profile except the unknown customer (-1). One that
-- does not trigger is suppressed with the first reason that applies, in this order:
--   dormant                 it is in opp_dormancy for this as-of date
--   no_prior_sales          no positive net sales in the prior window (no defensible prior)
--   below_min_prior_orders  fewer than min_prior_orders orders in the prior window
--   below_min_prior_sales   prior net sales below min_prior_sales
--   below_min_decline       decline below min_decline_pct
-- reason_codes on a triggered row list the three tests it met, plus negative_current_period when
-- the current window's net sales are below zero (returns exceeding sales).
-- Parameters: $asof_date, $recovery_window_months, $recovery_min_decline_pct,
-- $recovery_min_prior_sales, $recovery_min_prior_orders. The column type is a keyword, so RF04
-- is off for this file.
-- noqa: disable=RF04

alter table opp_recovery add column current_sales decimal(38, 4);
alter table opp_recovery add column prior_sales decimal(38, 4);
alter table opp_recovery add column prior_orders bigint;
alter table opp_recovery add column decline_pct decimal(18, 4);

create or replace temp table recovery_tests as
with bounds as (
    select
        cast(
            date_trunc('month', cast($asof_date as date))
            - to_months(cast($recovery_window_months as integer) - 1) as date
        ) as current_start,
        cast($asof_date as date) as current_end
),

windows as (
    select
        current_start,
        current_end,
        cast(current_start - to_months(12) as date) as prior_start,
        cast(current_end - to_months(12) as date) as prior_end
    from bounds
),

customers as (
    select customer_key
    from asof_customer_profile
    where customer_key <> -1
),

per_customer as (
    select
        customers.customer_key,
        coalesce(sum(orders.net_sales) filter (
            where orders.order_date between windows.current_start and windows.current_end
        ), 0) as current_sales,
        coalesce(sum(orders.net_sales) filter (
            where orders.order_date between windows.prior_start and windows.prior_end
        ), 0) as prior_sales,
        count(orders.order_date) filter (
            where orders.order_date between windows.prior_start and windows.prior_end
        ) as prior_orders
    from customers
    cross join windows
    left join asof_orders as orders on customers.customer_key = orders.customer_key
    group by customers.customer_key
)

select
    per_customer.customer_key,
    cast(per_customer.current_sales as decimal(38, 4)) as current_sales,
    cast(per_customer.prior_sales as decimal(38, 4)) as prior_sales,
    cast(per_customer.prior_orders as bigint) as prior_orders,
    case
        when per_customer.prior_sales > 0
            then cast(
                (per_customer.prior_sales - per_customer.current_sales)
                / per_customer.prior_sales * 100 as decimal(18, 4)
            )
    end as decline_pct,
    dormancy.customer_key is not null as dormant
from per_customer
left join opp_dormancy as dormancy on per_customer.customer_key = dormancy.customer_key;

insert into opp_evaluations (type, as_of_date, customer_key, category, outcome)
select
    'recovery' as type,
    cast($asof_date as date) as as_of_date,
    customer_key,
    null as category,
    case
        when dormant then 'dormant'
        when prior_sales <= 0 then 'no_prior_sales'
        when prior_orders < $recovery_min_prior_orders then 'below_min_prior_orders'
        when prior_sales < $recovery_min_prior_sales then 'below_min_prior_sales'
        when decline_pct < $recovery_min_decline_pct then 'below_min_decline'
        else 'triggered'
    end as outcome
from recovery_tests;

insert into opp_recovery (
    opp_id,
    type,
    customer_key,
    category,
    as_of_date,
    algo_version,
    gap,
    reason_codes,
    current_sales,
    prior_sales,
    prior_orders,
    decline_pct
)
select
    opp_id('recovery', tests.customer_key, null, cast($asof_date as date)) as opp_id,
    'recovery' as type,
    tests.customer_key,
    null as category,
    cast($asof_date as date) as as_of_date,
    engine.algo_version,
    tests.prior_sales - tests.current_sales as gap,
    list_concat(
        ['decline_at_least_min', 'prior_sales_at_least_min', 'prior_orders_at_least_min'],
        case when tests.current_sales < 0 then ['negative_current_period'] else [] end
    ) as reason_codes,
    tests.current_sales,
    tests.prior_sales,
    tests.prior_orders,
    tests.decline_pct
from recovery_tests as tests
inner join opp_engines as engine on engine.type = 'recovery'
where
    not tests.dormant
    and tests.prior_sales > 0
    and tests.prior_orders >= $recovery_min_prior_orders
    and tests.prior_sales >= $recovery_min_prior_sales
    and tests.decline_pct >= $recovery_min_decline_pct;
