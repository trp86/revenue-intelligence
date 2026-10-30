-- Silver checks that must hold for the stage to commit (spec 01 S9, S10, S12). A failed
-- check raises an error, which rolls back the whole stage: silver is never left half-built.
-- Messages hold counts and source row numbers only, never cell values.

-- S10: silver keeps every bronze row. count(silver_sales) = count(bronze).
with silver as (
    select count(*) as n from silver_sales
),

bronze as (
    select count(*) as n from read_parquet($bronze_file)
)

select
    case
        when silver.n <> bronze.n
            then error(
                'silver row count ' || silver.n::varchar
                || ' does not match bronze row count ' || bronze.n::varchar
            )
    end as row_count_check
from silver
cross join bronze;

-- S9, D1: at most one row may match the stray-row rule. More than one fails the build for
-- review; the source rows are listed so a person can look at them in the workbook.
with stray as (
    select
        count(*) as n,
        string_agg(_source_row::varchar, ', ' order by _source_row) as source_rows
    from stray_rows
)

select
    case
        when stray.n > 1
            then error(
                stray.n::varchar || ' rows match the stray-row rule (source rows '
                || stray.source_rows || '); expected at most one, review the workbook'
            )
    end as stray_row_check
from stray;

-- S10: the only exclusion reasons allowed are stray_row and exact_duplicate. No other rule
-- may set is_excluded.
with bad_reasons as (
    select
        count(*) as n,
        string_agg(distinct exclusion_reason, ', ' order by exclusion_reason) as reasons
    from silver_sales
    where is_excluded and exclusion_reason not in ('stray_row', 'exact_duplicate')
)

select
    case
        when bad_reasons.n > 0
            then error(
                'exclusion reason not allowed on ' || bad_reasons.n::varchar
                || ' rows: ' || bad_reasons.reasons
                || '; allowed: stray_row, exact_duplicate'
            )
    end as reason_check
from bad_reasons;

-- An excluded row always has a reason, and only an excluded row has one.
with unexplained as (
    select
        count(*) filter (where is_excluded and exclusion_reason is null) as without_reason,
        count(*) filter (where not is_excluded and exclusion_reason is not null) as not_excluded
    from silver_sales
)

select
    case
        when unexplained.without_reason > 0
            then error(
                unexplained.without_reason::varchar || ' excluded rows have no reason'
                || ' (excluded without a reason)'
            )
        when unexplained.not_excluded > 0
            then error(
                unexplained.not_excluded::varchar
                || ' rows have an exclusion reason but are not excluded'
            )
    end as reason_present_check
from unexplained;

-- S12: silver_excluded_rows holds exactly the excluded rows: same source rows, same reasons.
with in_silver as (
    select
        _source_row,
        exclusion_reason
    from silver_sales
    where is_excluded
),

in_audit as (
    select
        _source_row,
        exclusion_reason
    from silver_excluded_rows
),

only_in_silver as (
    select * from in_silver
    except
    select * from in_audit
),

only_in_audit as (
    select * from in_audit
    except
    select * from in_silver
),

differences as (
    select count(*) as n
    from (
        select * from only_in_silver
        union all
        select * from only_in_audit
    ) as differing
)

select
    case
        when differences.n > 0
            then error(
                'silver_excluded_rows and the excluded rows of silver_sales differ on '
                || differences.n::varchar || ' rows'
            )
    end as audit_table_check
from differences;
