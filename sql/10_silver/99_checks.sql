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

-- S4: silver_customer_codes accounts for every kept order line that has a customer code, and
-- holds one row per code. The lines in the table add up to the kept lines with a code; codes
-- are never merged, so the number of rows equals the number of distinct codes.
with expected as (
    select
        count(*) as kept_lines,
        count(distinct customer_code) as distinct_codes
    from customer_lines
    where silver_text(customer_code) is not null
),

actual as (
    select
        coalesce(sum(order_lines), 0) as table_lines,
        count(*) as table_codes,
        count(distinct customer_code) as table_distinct_codes
    from silver_customer_codes
)

select
    case
        when expected.kept_lines <> actual.table_lines
            then error(
                'silver_customer_codes covers ' || actual.table_lines::varchar
                || ' order lines but silver has ' || expected.kept_lines::varchar
                || ' kept lines with a customer code'
            )
        when expected.distinct_codes <> actual.table_codes
            then error(
                'silver_customer_codes has ' || actual.table_codes::varchar
                || ' rows but silver has ' || expected.distinct_codes::varchar
                || ' distinct customer codes'
            )
        when actual.table_codes <> actual.table_distinct_codes
            then error('silver_customer_codes has a customer code more than once')
    end as customer_table_check
from expected
cross join actual;

-- Spec 01 section 5: dq_rule_results has exactly one row per rule S1 to S12, the exclusion table
-- one row per allowed reason and candidate column, and the void table one row. Counts are never
-- negative and no count is larger than the silver table.
with results as (
    select
        count(*) as result_rows,
        count(distinct rule_id) as distinct_rules,
        count(*) filter (
            where rule_id in (
                'S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7', 'S8', 'S9', 'S10', 'S11', 'S12'
            )
        ) as known_rules,
        count(*) filter (where rows_affected < 0) as negative_counts
    from dq_rule_results
),

effect as (
    select count(*) as effect_rows
    from dq_exclusion_effect
),

void_rows as (
    select count(*) as void_row_count
    from dq_void_effect
),

silver as (
    select count(*) as silver_rows
    from silver_sales
),

too_large as (
    select count(*) as n
    from dq_rule_results
    cross join silver
    where
        dq_rule_results.rule_id not in ('S4', 'S12')
        and dq_rule_results.rows_affected > silver.silver_rows
),

expected_effect as (
    select 2 * count(*) as effect_rows
    from (
        select unnest(cast($net_sales_candidate_columns as varchar[])) as amount_column
    ) as candidate_columns
)

select
    case
        when results.result_rows <> 12 or results.distinct_rules <> 12 or results.known_rules <> 12
            then error(
                'dq_rule_results has ' || results.result_rows::varchar
                || ' rows but needs exactly one row for each of the rules S1 to S12'
            )
        when results.negative_counts > 0
            then error('dq_rule_results has a negative rows_affected')
        when too_large.n > 0
            then error('dq_rule_results has a rows_affected larger than the silver table')
        when effect.effect_rows <> expected_effect.effect_rows
            then error(
                'dq_exclusion_effect has ' || effect.effect_rows::varchar || ' rows but needs '
                || expected_effect.effect_rows::varchar
                || ' (one for each exclusion reason and candidate amount column)'
            )
        when void_rows.void_row_count <> 1
            then error('dq_void_effect must have exactly one row')
    end as quality_table_check
from results
cross join effect
cross join void_rows
cross join too_large
cross join expected_effect;

-- dq_rule_results agrees with the rule tables it summarises: S10 and S12 count the excluded rows
-- and S5 plus S9 are the two allowed reasons.
with checked as (
    select
        max(rows_affected) filter (where rule_id = 'S5') as s5,
        max(rows_affected) filter (where rule_id = 'S9') as s9,
        max(rows_affected) filter (where rule_id = 'S10') as s10,
        max(rows_affected) filter (where rule_id = 'S12') as s12
    from dq_rule_results
)

select
    case
        when checked.s10 <> checked.s12
            then error('dq_rule_results: S10 and S12 count a different number of excluded rows')
        when checked.s10 <> checked.s5 + checked.s9
            then error('dq_rule_results: S10 is not the sum of the duplicate and stray-row counts')
    end as quality_consistency_check
from checked;
