-- R1 and R2: no row is lost between the Excel sheet, bronze and silver (spec 01 section 6).
-- Every comparison is exact (tolerance 0). now() is the start of the transaction, so every
-- result of one run has the same checked_at.

-- R1: bronze rows equal the Excel data rows. $excel_rows is counted from the workbook itself
-- by revint.recon, not from bronze.
insert into recon_results
with bronze as (
    select count(*) as n from read_parquet($bronze_file)
)

select
    'R1' as check_id,
    'bronze_rows' as subject,
    'Bronze rows equal Excel data rows' as description,
    case when bronze.n = $excel_rows then 'pass' else 'fail' end as status,
    $excel_rows as expected,
    bronze.n as actual,
    bronze.n - $excel_rows as difference,
    0.0 as tolerance,
    null as detail,
    cast(now() at time zone 'UTC' as timestamp) as checked_at
from bronze;

-- R2: silver keeps every bronze row (S10).
insert into recon_results
with bronze as (
    select count(*) as n from read_parquet($bronze_file)
),

silver as (
    select count(*) as n from silver_sales
)

select
    'R2' as check_id,
    'silver_rows' as subject,
    'Silver rows equal bronze rows' as description,
    case when silver.n = bronze.n then 'pass' else 'fail' end as status,
    bronze.n as expected,
    silver.n as actual,
    silver.n - bronze.n as difference,
    0.0 as tolerance,
    null as detail,
    cast(now() at time zone 'UTC' as timestamp) as checked_at
from bronze
cross join silver;

-- R2: the audit table lists exactly the rows silver marks as excluded (S12).
insert into recon_results
with silver as (
    select count(*) filter (where is_excluded) as n from silver_sales
),

audit as (
    select count(*) as n from silver_excluded_rows
)

select
    'R2' as check_id,
    'excluded_rows' as subject,
    'Rows in silver_excluded_rows equal rows with is_excluded' as description,
    case when audit.n = silver.n then 'pass' else 'fail' end as status,
    silver.n as expected,
    audit.n as actual,
    audit.n - silver.n as difference,
    0.0 as tolerance,
    null as detail,
    cast(now() at time zone 'UTC' as timestamp) as checked_at
from silver
cross join audit;

-- R2: the stray rows silver flags (S9, D1) are the ones the audit table records as stray.
-- Silver already fails its own build when more than one row matches the rule.
insert into recon_results
with silver as (
    select count(*) filter (where f_stray_row) as n from silver_sales
),

audit as (
    select count(*) filter (where exclusion_reason = 'stray_row') as n
    from silver_excluded_rows
)

select
    'R2' as check_id,
    'stray_rows' as subject,
    'Stray rows flagged in silver equal stray rows in silver_excluded_rows' as description,
    case when audit.n = silver.n then 'pass' else 'fail' end as status,
    silver.n as expected,
    audit.n as actual,
    audit.n - silver.n as difference,
    0.0 as tolerance,
    null as detail,
    cast(now() at time zone 'UTC' as timestamp) as checked_at
from silver
cross join audit;
