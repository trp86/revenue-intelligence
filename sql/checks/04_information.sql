-- R4: distinct customers, distinct products and the date range, reported as information
-- (spec 01 section 6). They never fail the run: the docs figures (about 12 thousand
-- customers, 181 products, 2017-07-02 to 2020-02-29) are approximate, and the allowed
-- distance from them is an open question (recon.tolerance_report_pct is still [x]), so a
-- person compares the numbers. All silver rows count, excluded rows included; blank values
-- are not counted.
-- The columns are customers.code_column, recon.product_column and recon.date_column, picked
-- by name, so the identifier rules are switched off.
-- noqa: disable=RF05,RF06,AM04,ST07,RF02

insert into recon_results
with customers as (
    select count(distinct columns(lambda c: c = $customers_code_column)) as n
    from silver_sales
),

products as (
    select count(distinct columns(lambda c: c = $recon_product_column)) as n
    from silver_sales
),

dates as (
    select
        min(columns(lambda c: c = $recon_date_column)) as first_date,
        max(columns(lambda c: c = $recon_date_column)) as last_date
    from silver_sales
),

counts as (
    select
        'customers' as subject,
        'Distinct customer codes (' || $customers_code_column || ')' as description,
        customers.n as actual,
        null as detail
    from customers
    union all
    select
        'products' as subject,
        'Distinct products (' || $recon_product_column || ')' as description,
        products.n as actual,
        null as detail
    from products
    union all
    select
        'date_min' as subject,
        'First date (' || $recon_date_column || ')' as description,
        null as actual,
        cast(dates.first_date as varchar) as detail
    from dates
    union all
    select
        'date_max' as subject,
        'Last date (' || $recon_date_column || ')' as description,
        null as actual,
        cast(dates.last_date as varchar) as detail
    from dates
)

select
    'R4' as check_id,
    counts.subject,
    counts.description,
    'info' as status,
    null as expected,
    counts.actual,
    null as difference,
    null as tolerance,
    counts.detail,
    cast(now() at time zone 'UTC' as timestamp) as checked_at
from counts;
