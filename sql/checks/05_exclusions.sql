-- R7 (silver side) and R8: the exclusions reconcile with silver (spec 01 section 6, story #44).
-- The gold form of R7, with sum(fact_sales), needs fact_sales from the gold layer (E2).
--
-- R7: for every candidate amount column, sum(silver_sales) equals the sum of the rows gold
-- keeps plus the sum of the rows silver_excluded_rows records for the rows gold leaves out,
-- within recon.tolerance_amount.
--   duplicates.exclude_from_net_sales = true: gold keeps the rows that are not excluded and
--     leaves out every excluded row (stray row and copies).
--   duplicates.exclude_from_net_sales = false: gold also keeps the exact-duplicate copies and
--     leaves out only the stray row.
-- The kept side comes from silver_sales and the left-out side from silver_excluded_rows, so
-- the identity fails if the audit table disagrees with silver on an amount or misses a row.
-- The audit table names its columns in lower case; the match ignores case. The columns are
-- net_sales.candidate_columns, picked by name, so the identifier rules are switched off.
-- noqa: disable=RF05,RF06,AM04,ST07,RF02

create or replace temp table recon_total_sums as
with sums as (
    select coalesce(sum(columns(lambda c: list_contains($net_sales_candidate_columns, c))), 0)
    from silver_sales
)

select
    lower(subject) as subject,
    cast(total as decimal(38, 4)) as total
from (unpivot sums on columns(*) into name subject value total);

create or replace temp table recon_kept_sums as
with sums as (
    select coalesce(sum(columns(lambda c: list_contains($net_sales_candidate_columns, c))), 0)
    from silver_sales
    where
        not is_excluded
        or (not $duplicates_exclude_from_net_sales and exclusion_reason = 'exact_duplicate')
)

select
    lower(subject) as subject,
    cast(total as decimal(38, 4)) as total
from (unpivot sums on columns(*) into name subject value total);

create or replace temp table recon_left_out_sums as
with sums as (
    select
        coalesce(
            sum(
                columns(
                    lambda c: list_contains(
                        list_transform($net_sales_candidate_columns, lambda x: lower(x)), lower(c)
                    )
                )
            ),
            0
        )
    from silver_excluded_rows
    where $duplicates_exclude_from_net_sales or exclusion_reason = 'stray_row'
)

select
    lower(subject) as subject,
    cast(total as decimal(38, 4)) as total
from (unpivot sums on columns(*) into name subject value total);

insert into recon_results
with compared as (
    select
        candidates.candidate as subject,
        total_sums.total as expected,
        kept_sums.total + left_out_sums.total as actual,
        kept_sums.total + left_out_sums.total - total_sums.total as difference,
        cast($recon_tolerance_amount as decimal(18, 4)) as allowed
    from (select unnest($net_sales_candidate_columns) as candidate) as candidates
    inner join recon_total_sums as total_sums on lower(candidates.candidate) = total_sums.subject
    inner join recon_kept_sums as kept_sums on total_sums.subject = kept_sums.subject
    inner join recon_left_out_sums as left_out_sums on total_sums.subject = left_out_sums.subject
)

select
    'R7' as check_id,
    compared.subject,
    'Sum of ' || compared.subject
    || ': silver equals kept rows plus excluded rows (duplicates.exclude_from_net_sales = '
    || cast($duplicates_exclude_from_net_sales as varchar) || ')' as description,
    case when abs(compared.difference) <= compared.allowed then 'pass' else 'fail' end as status,
    compared.expected,
    compared.actual,
    compared.difference,
    $recon_tolerance_amount as tolerance,
    null as detail,
    cast(now() at time zone 'UTC' as timestamp) as checked_at
from compared;

-- Every candidate column must have been checked. A candidate that is not an amount column of
-- silver_excluded_rows would otherwise be skipped without a word.
select
    case
        when
            count(*) <> len($net_sales_candidate_columns)
            then error(
                'R7 checked ' || cast(count(*) as varchar) || ' of '
                || cast(len($net_sales_candidate_columns) as varchar)
                || ' net_sales.candidate_columns; a column is missing from silver_excluded_rows'
            )
    end as every_column_checked
from recon_results
where check_id = 'R7';

-- R8: every exact_duplicate row in silver_excluded_rows has an identical twin at a lower
-- _source_row that silver does not exclude. Identical means every column in
-- duplicates.key_columns has the same bronze text, with blank cells equal to each other (the
-- rule 04_duplicates.sql applies). A copy fails when it has no recorded twin, the twin is not
-- in silver, is excluded, is not at a lower row, or differs in any compared column. The result
-- is the number of failing copies; the detail says how many copies were checked.
insert into recon_results
with raw_keys as (
    select
        cast(_source_row as bigint) as _source_row,
        list_value(*columns(lambda c: list_contains($duplicates_key_columns, c))) as raw_values
    from read_parquet($bronze_file)
),

keyed as (
    select
        _source_row,
        list_transform(
            raw_values,
            lambda v: case
                when
                    nullif(trim(v, ' ' || chr(9) || chr(10) || chr(13) || chr(160)), '') is null
                    then null
                else v
            end
        ) as key_values
    from raw_keys
),

copies as (
    select
        _source_row,
        duplicate_of_source_row
    from silver_excluded_rows
    where exclusion_reason = 'exact_duplicate'
),

checked as (
    select
        copies._source_row,
        coalesce(
            copies.duplicate_of_source_row is null
            or copies.duplicate_of_source_row >= copies._source_row
            or twin_silver._source_row is null
            or twin_silver.is_excluded
            or twin_bronze._source_row is null
            or copy_bronze.key_values is distinct from twin_bronze.key_values,
            true
        ) as is_failure
    from copies
    left join silver_sales as twin_silver
        on copies.duplicate_of_source_row = twin_silver._source_row
    left join keyed as twin_bronze on copies.duplicate_of_source_row = twin_bronze._source_row
    left join keyed as copy_bronze on copies._source_row = copy_bronze._source_row
),

totals as (
    select
        count(*) as copies_checked,
        count(*) filter (where is_failure) as failures
    from checked
)

select
    'R8' as check_id,
    'exact_duplicate_twins' as subject,
    'Every exact_duplicate row has an identical, non-excluded twin at a lower _source_row'
        as description,
    case when totals.failures = 0 then 'pass' else 'fail' end as status,
    0 as expected,
    totals.failures as actual,
    totals.failures as difference,
    0.0 as tolerance,
    cast(totals.copies_checked as varchar) || ' exact_duplicate rows checked' as detail,
    cast(now() at time zone 'UTC' as timestamp) as checked_at
from totals;
