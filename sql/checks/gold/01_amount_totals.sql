-- Gold reconciliation, part 1: amounts (spec 02 section 10, story #85). These checks run only
-- when the gold layer is built (revint.recon). They add rows to recon_results; a rerun first
-- removes the gold rows it wrote before, so results are replaced, never appended.
--   R7 (gold form)  for every candidate amount column, sum(fact_sales) plus the sum of the rows
--                   gold leaves out (from silver_excluded_rows) equals sum(silver_sales),
--                   within recon.tolerance_amount.
--                   duplicates.exclude_from_net_sales = true:  gold leaves out every excluded row
--                     (stray row and copies).
--                   duplicates.exclude_from_net_sales = false: gold leaves out the stray row only.
--   G1              sum(net_sales) over the fact equals the net sales column of silver
--                   (net_sales.field) over the rows gold loads. A row with included = false is
--                   still in the fact, so it is still in both sums.
-- The columns are net_sales.candidate_columns and net_sales.field, picked by name, so the
-- identifier rules are switched off. Only counts and sums are stored, never a row.
-- noqa: disable=RF05,RF06,AM04,ST07,RF02

create table if not exists recon_results (
    check_id varchar,
    subject varchar,
    description varchar,
    status varchar,
    expected decimal(38, 4),
    actual decimal(38, 4),
    difference decimal(38, 4),
    tolerance double,
    detail varchar,
    checked_at timestamp
);

delete from recon_results
where check_id like 'G%' or (check_id = 'R7' and subject like 'gold:%');

create or replace temp table recon_gold_silver_sums as
with sums as (
    select coalesce(sum(columns(lambda c: list_contains($net_sales_candidate_columns, c))), 0)
    from silver_sales
)

select
    lower(subject) as subject,
    cast(total as decimal(38, 4)) as total
from (unpivot sums on columns(*) into name subject value total);

-- The fact keeps each candidate column as amount_<column>; the prefix is seven characters.
create or replace temp table recon_gold_fact_sums as
with sums as (
    select
        coalesce(
            sum(
                columns(
                    lambda c: list_contains(
                        list_transform($net_sales_candidate_columns, lambda x: 'amount_' || x), c
                    )
                )
            ),
            0
        )
    from fact_sales
)

select
    lower(substr(subject, 8)) as subject,
    cast(total as decimal(38, 4)) as total
from (unpivot sums on columns(*) into name subject value total);

create or replace temp table recon_gold_left_out_sums as
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
        silver_sums.total as expected,
        fact_sums.total + left_out_sums.total as actual,
        fact_sums.total + left_out_sums.total - silver_sums.total as difference,
        cast($recon_tolerance_amount as decimal(18, 4)) as allowed
    from (select unnest($net_sales_candidate_columns) as candidate) as candidates
    inner join recon_gold_silver_sums as silver_sums
        on lower(candidates.candidate) = silver_sums.subject
    inner join recon_gold_fact_sums as fact_sums
        on silver_sums.subject = fact_sums.subject
    inner join recon_gold_left_out_sums as left_out_sums
        on silver_sums.subject = left_out_sums.subject
)

select
    'R7' as check_id,
    'gold:' || compared.subject as subject,
    'Sum of ' || compared.subject
    || ': fact plus left-out rows equals silver (duplicates.exclude_from_net_sales = '
    || cast($duplicates_exclude_from_net_sales as varchar) || ')' as description,
    case when abs(compared.difference) <= compared.allowed then 'pass' else 'fail' end as status,
    compared.expected,
    compared.actual,
    compared.difference,
    $recon_tolerance_amount as tolerance,
    null as detail,
    cast(now() at time zone 'UTC' as timestamp) as checked_at
from compared;

-- Every candidate column must have been checked; a name that is missing from the fact or from
-- silver_excluded_rows would otherwise be skipped without a word.
select
    case
        when
            count(*) <> len($net_sales_candidate_columns)
            then error(
                'R7 (gold) checked ' || cast(count(*) as varchar) || ' of '
                || cast(len($net_sales_candidate_columns) as varchar)
                || ' net_sales.candidate_columns; a column is missing from the fact'
            )
    end as every_column_checked
from recon_results
where check_id = 'R7' and subject like 'gold:%';

insert into recon_results
with silver as (
    select coalesce(sum(columns(lambda c: c = $net_sales_field)), 0) as total
    from silver_sales
    where
        not is_excluded
        or (not $duplicates_exclude_from_net_sales and exclusion_reason = 'exact_duplicate')
),

fact as (
    select coalesce(sum(net_sales), 0) as total
    from fact_sales
),

compared as (
    select
        cast(silver.total as decimal(38, 4)) as expected,
        cast(fact.total as decimal(38, 4)) as actual,
        cast(fact.total - silver.total as decimal(38, 4)) as difference,
        cast($recon_tolerance_amount as decimal(18, 4)) as allowed
    from silver
    cross join fact
)

select
    'G1' as check_id,
    'fact_net_sales' as subject,
    'Sum of net_sales in the fact equals the net sales column of silver over the rows gold loads'
        as description,
    case when abs(compared.difference) <= compared.allowed then 'pass' else 'fail' end as status,
    compared.expected,
    compared.actual,
    compared.difference,
    $recon_tolerance_amount as tolerance,
    $net_sales_field as detail,
    cast(now() at time zone 'UTC' as timestamp) as checked_at
from compared;
