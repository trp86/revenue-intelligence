-- Gold reconciliation, part 3: fact rows and keys (spec 02 section 10, story #85).
--   G5  fact row count: with duplicates.exclude_from_net_sales = true it equals the number of
--       silver rows minus the rows in silver_excluded_rows; with false, silver rows minus the
--       stray rows (the exact-duplicate copies stay in the fact).
--   G3  surrogate keys are unique: each dimension key, and the fact's sales_line_id.
--   G4  no orphan foreign keys: every key in the fact and in the marts is a row of its
--       dimension (the unknown member -1 is a row).
-- Counts are compared exactly. Only counts are stored.

insert into recon_results
with silver as (
    select count(*) as n
    from silver_sales
),

left_out as (
    select
        count(*) filter (where exclusion_reason = 'stray_row') as strays,
        count(*) as excluded
    from silver_excluded_rows
),

fact as (
    select count(*) as n
    from fact_sales
),

setting as (
    select cast($duplicates_exclude_from_net_sales as boolean) as exclude_copies
),

compared as (
    select
        silver.n
        - case when setting.exclude_copies then left_out.excluded else left_out.strays end
            as expected,
        fact.n as actual
    from silver
    cross join left_out
    cross join fact
    cross join setting
)

select
    'G5' as check_id,
    'fact_rows' as subject,
    'Fact rows equal silver rows minus the rows gold leaves out '
    || '(duplicates.exclude_from_net_sales = '
    || cast($duplicates_exclude_from_net_sales as varchar) || ')' as description,
    case when compared.actual = compared.expected then 'pass' else 'fail' end as status,
    cast(compared.expected as decimal(38, 4)) as expected,
    cast(compared.actual as decimal(38, 4)) as actual,
    cast(compared.actual - compared.expected as decimal(38, 4)) as difference,
    0.0 as tolerance,
    null as detail,
    cast(now() at time zone 'UTC' as timestamp) as checked_at
from compared;

insert into recon_results
with keys as (
    select
        'dim_date.date_key' as subject,
        count(*) as n,
        count(distinct date_key) as n_distinct
    from dim_date
    union all
    select
        'dim_customer.customer_key' as subject,
        count(*) as n,
        count(distinct customer_key) as n_distinct
    from dim_customer
    union all
    select
        'dim_product.product_key' as subject,
        count(*) as n,
        count(distinct product_key) as n_distinct
    from dim_product
    union all
    select
        'dim_branch.branch_key' as subject,
        count(*) as n,
        count(distinct branch_key) as n_distinct
    from dim_branch
    union all
    select
        'fact_sales.sales_line_id' as subject,
        count(*) as n,
        count(distinct sales_line_id) as n_distinct
    from fact_sales
)

select
    'G3' as check_id,
    keys.subject,
    'The key has no repeated value: distinct values equal rows' as description,
    case when keys.n_distinct = keys.n then 'pass' else 'fail' end as status,
    cast(keys.n as decimal(38, 4)) as expected,
    cast(keys.n_distinct as decimal(38, 4)) as actual,
    cast(keys.n_distinct - keys.n as decimal(38, 4)) as difference,
    0.0 as tolerance,
    null as detail,
    cast(now() at time zone 'UTC' as timestamp) as checked_at
from keys;

insert into recon_results
with orphans as (
    select
        'fact_sales.date_key' as subject,
        count(*) as n
    from fact_sales as f
    left join dim_date as d on f.date_key = d.date_key
    where d.date_key is null
    union all
    select
        'fact_sales.customer_key' as subject,
        count(*) as n
    from fact_sales as f
    left join dim_customer as d on f.customer_key = d.customer_key
    where d.customer_key is null
    union all
    select
        'fact_sales.product_key' as subject,
        count(*) as n
    from fact_sales as f
    left join dim_product as d on f.product_key = d.product_key
    where d.product_key is null
    union all
    select
        'fact_sales.branch_key' as subject,
        count(*) as n
    from fact_sales as f
    left join dim_branch as d on f.branch_key = d.branch_key
    where d.branch_key is null
    union all
    select
        'mart_customer_month.customer_key' as subject,
        count(*) as n
    from mart_customer_month as m
    left join dim_customer as d on m.customer_key = d.customer_key
    where d.customer_key is null
    union all
    select
        'mart_customer_category_month.customer_key' as subject,
        count(*) as n
    from mart_customer_category_month as m
    left join dim_customer as d on m.customer_key = d.customer_key
    where d.customer_key is null
    union all
    select
        'mart_customer_profile.customer_key' as subject,
        count(*) as n
    from mart_customer_profile as m
    left join dim_customer as d on m.customer_key = d.customer_key
    where d.customer_key is null
    union all
    select
        'mart_branch_month.branch_key' as subject,
        count(*) as n
    from mart_branch_month as m
    left join dim_branch as d on m.branch_key = d.branch_key
    where d.branch_key is null
)

select
    'G4' as check_id,
    orphans.subject,
    'Rows whose key is not a row of its dimension' as description,
    case when orphans.n = 0 then 'pass' else 'fail' end as status,
    cast(0 as decimal(38, 4)) as expected,
    cast(orphans.n as decimal(38, 4)) as actual,
    cast(orphans.n as decimal(38, 4)) as difference,
    0.0 as tolerance,
    null as detail,
    cast(now() at time zone 'UTC' as timestamp) as checked_at
from orphans;
