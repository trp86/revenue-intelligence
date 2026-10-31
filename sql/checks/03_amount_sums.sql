-- R3: for each candidate amount column, the sum of bronze (cast the way silver casts) equals
-- the sum of silver, within recon.tolerance_amount (spec 01 section 6).
--
-- Silver keeps every bronze row, excluded rows included, so the two sums cover the same rows.
-- Bronze text is cast with the same rule silver uses (trim, blank is NULL, decimal(18, 4)); a
-- text that cannot be cast adds nothing on either side. The columns are
-- net_sales.candidate_columns, picked by name, so the identifier rules are switched off.
-- noqa: disable=RF05,RF06,AM04,ST07,RF02

create or replace temp table recon_bronze_sums as
with sums as (
    select
        coalesce(
            sum(
                try_cast(
                    nullif(
                        trim(
                            columns(lambda c: list_contains($net_sales_candidate_columns, c)),
                            ' ' || chr(9) || chr(10) || chr(13) || chr(160)
                        ),
                        ''
                    ) as decimal(18, 4)
                )
            ),
            0
        )
    from read_parquet($bronze_file)
)

select
    subject,
    cast(total as decimal(38, 4)) as total
from (unpivot sums on columns(*) into name subject value total);

create or replace temp table recon_silver_sums as
with sums as (
    select coalesce(sum(columns(lambda c: list_contains($net_sales_candidate_columns, c))), 0)
    from silver_sales
)

select
    subject,
    cast(total as decimal(38, 4)) as total
from (unpivot sums on columns(*) into name subject value total);

insert into recon_results
with compared as (
    select
        bronze_sums.subject,
        bronze_sums.total as expected,
        silver_sums.total as actual,
        silver_sums.total - bronze_sums.total as difference,
        cast($recon_tolerance_amount as decimal(18, 4)) as allowed
    from recon_bronze_sums as bronze_sums
    inner join recon_silver_sums as silver_sums on bronze_sums.subject = silver_sums.subject
)

select
    'R3' as check_id,
    compared.subject,
    'Sum of ' || compared.subject || ': bronze (cast) equals silver' as description,
    case when abs(compared.difference) <= compared.allowed then 'pass' else 'fail' end as status,
    compared.expected,
    compared.actual,
    compared.difference,
    $recon_tolerance_amount as tolerance,
    null as detail,
    cast(now() at time zone 'UTC' as timestamp) as checked_at
from compared;

-- Every candidate column must have been checked. A name that is not a column of the bronze
-- or silver table would otherwise be skipped without a word.
select
    case
        when
            count(*) <> len($net_sales_candidate_columns)
            then error(
                'R3 checked ' || cast(count(*) as varchar) || ' of '
                || cast(len($net_sales_candidate_columns) as varchar)
                || ' net_sales.candidate_columns; a column is missing from bronze or silver'
            )
    end as every_column_checked
from recon_results
where check_id = 'R3';
