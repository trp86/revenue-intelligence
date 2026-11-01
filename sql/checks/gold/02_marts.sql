-- Gold reconciliation, part 2: every mart equals the fact (spec 02 section 10, story #85).
--   G2  each mart's net sales total equals the fact total of included rows, and its line count
--       equals the number of included fact rows, within recon.tolerance_amount (lines exactly).
--       mart_peer_category_share holds real customers only (the unknown customer is never a
--       peer), so it is compared with the fact total of included rows of real customers.
--       mart_customer_profile has no amount: it must hold the same customers as
--       mart_customer_month.
-- A mart that adds, drops or doubles a line fails here. Only counts and sums are stored.

insert into recon_results
with fact as (
    select
        coalesce(sum(net_sales), 0) as total,
        count(*) as n,
        coalesce(sum(net_sales) filter (where customer_key <> -1), 0) as real_total,
        count(*) filter (where customer_key <> -1) as real_n
    from fact_sales
    where included
),

setting as (
    select cast($recon_tolerance_amount as decimal(18, 4)) as tolerance
),

marts as (
    select
        'mart_customer_month' as mart,
        coalesce(sum(net_sales), 0) as total,
        coalesce(sum(n_lines), 0) as n,
        false as real_only
    from mart_customer_month
    union all
    select
        'mart_customer_category_month' as mart,
        coalesce(sum(net_sales), 0) as total,
        coalesce(sum(n_lines), 0) as n,
        false as real_only
    from mart_customer_category_month
    union all
    select
        'mart_branch_month' as mart,
        coalesce(sum(net_sales), 0) as total,
        coalesce(sum(n_lines), 0) as n,
        false as real_only
    from mart_branch_month
    union all
    select
        'mart_peer_category_share' as mart,
        coalesce(sum(total_net_sales), 0) as total,
        coalesce(sum(n_lines), 0) as n,
        true as real_only
    from mart_peer_category_share
),

compared as (
    select
        marts.mart as subject,
        'Net sales total of the mart equals the fact total of included rows' as description,
        cast(case when marts.real_only then fact.real_total else fact.total end as decimal(38, 4))
            as expected,
        cast(marts.total as decimal(38, 4)) as actual,
        setting.tolerance as allowed
    from marts
    cross join fact
    cross join setting
    union all
    select
        marts.mart || ':n_lines' as subject,
        'Line count of the mart equals the number of included fact rows' as description,
        cast(case when marts.real_only then fact.real_n else fact.n end as decimal(38, 4))
            as expected,
        cast(marts.n as decimal(38, 4)) as actual,
        cast(0 as decimal(18, 4)) as allowed
    from marts
    cross join fact
)

select
    'G2' as check_id,
    compared.subject,
    compared.description,
    case
        when abs(compared.actual - compared.expected) <= compared.allowed then 'pass'
        else 'fail'
    end as status,
    compared.expected,
    compared.actual,
    compared.actual - compared.expected as difference,
    cast(compared.allowed as double) as tolerance,
    null as detail,
    cast(now() at time zone 'UTC' as timestamp) as checked_at
from compared;

insert into recon_results
with customers as (
    select
        (select count(distinct customer_key) from mart_customer_month) as expected,
        (select count(*) from mart_customer_profile) as actual
)

select
    'G2' as check_id,
    'mart_customer_profile:customers' as subject,
    'mart_customer_profile holds the same customers as mart_customer_month' as description,
    case when customers.actual = customers.expected then 'pass' else 'fail' end as status,
    cast(customers.expected as decimal(38, 4)) as expected,
    cast(customers.actual as decimal(38, 4)) as actual,
    cast(customers.actual - customers.expected as decimal(38, 4)) as difference,
    0.0 as tolerance,
    null as detail,
    cast(now() at time zone 'UTC' as timestamp) as checked_at
from customers;
