-- Data quality results (spec 01 section 5). One row per silver rule S1 to S12 in
-- dq_rule_results, the effect of each exclusion on each candidate amount column in
-- dq_exclusion_effect, and the voided-line figures in dq_void_effect. These tables hold counts
-- and sums only: no row, customer, label or order value is ever written to them (S12, and
-- CLAUDE.md rule 4). They are rebuilt on every silver build, never appended.
--
-- rows_affected counts the PROBLEM rows of a rule (maintainer's decision on issue #41):
--   S1  rows where rounding a decimal to four places changed its value
--   S2  rows with at least one value that could not be typed (f_bad_<col>)
--   S3  rows whose channel or branch label the map changed
--   S4  kept order lines of customer codes with more than one name or branch, or a near-duplicate
--   S5  exact-duplicate copies          S6  rows with a blank Void (f_blank_void)
--   S7  possible free goods             S8  negative quantity or value
--   S9  the stray row                   S10 excluded rows (any reason)
--   S11 rows with a bad value in one of the candidate amount columns
--   S12 rows in silver_excluded_rows
-- net_sales_impact is the sum of net_sales.field over those rows. A row whose net sales value
-- is NULL contributes 0, so the impact undercounts where values are missing; the count of such
-- rows is stated in the description. It is NULL for S1 and S4, where it has no meaning.
-- severity and action_taken are a fixed value per rule from config (quality.severity and
-- quality.action), passed as parallel lists, never computed here.
-- The net sales and candidate columns are config, not code (net_sales.field and
-- net_sales.candidate_columns); the decimal columns come from revint.silver.COLUMN_TYPES.
-- Column names are picked by name, so the identifier rules are switched off for this file.
-- noqa: disable=RF05,RF06,AM04,ST07,RF02

-- One flag per rule and per row, kept in a temporary table so each rule is a plain count.
create or replace temp table dq_flags as
with net as (
    select
        _source_row,
        columns(lambda c: c = $net_sales_field) as net_value
    from silver_sales
),

decimals as (
    -- S1: the typed decimals and their raw texts, as two lists in the same column order.
    select
        _source_row,
        list_value(*columns(lambda c: list_contains($dq_decimal_columns, c))) as typed_values,
        list_value(*columns(lambda c: list_contains($dq_decimal_raw_columns, c))) as raw_values
    from silver_sales
),

rounded as (
    select
        _source_row,
        list_bool_or(
            list_transform(
                list_zip(typed_values, raw_values),
                lambda z: z[1] is not null
                and try_cast(silver_text(z[2]) as decimal(38, 18))
                is distinct from cast(z[1] as decimal(38, 18))
            )
        ) as rounded
    from decimals
),

bad_any as (
    -- S2: a row counts once however many of its values are bad.
    select
        _source_row,
        list_bool_or(list_value(*columns('^f_bad_'))) as bad_any
    from silver_sales
),

bad_candidate as (
    -- S11: a bad value in one of the candidate amount columns.
    select
        _source_row,
        list_bool_or(
            list_value(
                *columns(
                    lambda c: list_contains(
                        list_transform($net_sales_candidate_columns, lambda x: 'f_bad_' || x), c
                    )
                )
            )
        ) as bad_candidate
    from silver_sales
)

select
    silver_sales._source_row,
    net.net_value,
    coalesce(rounded.rounded, false) as s1,
    coalesce(bad_any.bad_any, false) as s2,
    silver_sales.is_duplicate as s5,
    silver_sales.f_blank_void as s6,
    silver_sales.f_zero_value_with_qty as s7,
    silver_sales.f_negative_qty or silver_sales.f_negative_value as s8,
    silver_sales.f_stray_row as s9,
    silver_sales.is_excluded as s10,
    silver_sales.is_excluded and excluded.exclusion_reason is not null as s12,
    coalesce(bad_candidate.bad_candidate, false) as s11,
    coalesce(silver_sales.void_flag = 1, false) as voided,
    silver_sales.f_unmapped_void as unmapped_void
from silver_sales
inner join net on silver_sales._source_row = net._source_row
inner join rounded on silver_sales._source_row = rounded._source_row
inner join bad_any on silver_sales._source_row = bad_any._source_row
inner join bad_candidate on silver_sales._source_row = bad_candidate._source_row
left join silver_excluded_rows as excluded on silver_sales._source_row = excluded._source_row;

-- S3: rows where a normalised twin differs from its original, for the listed label columns.
create or replace temp table dq_label_rows as
with originals as (
    select
        _source_row,
        columns(
            lambda c: list_contains($labels_channel_columns, c)
            or list_contains($labels_branch_columns, c)
        )
    from silver_sales
),

twins as (
    select
        _source_row,
        columns(
            lambda c: list_contains(
                list_transform($labels_channel_columns, lambda x: x || '_normalised'), c
            )
            or list_contains(
                list_transform($labels_branch_columns, lambda x: x || '_normalised'), c
            )
        )
    from silver_sales
),

original_cells as (
    unpivot originals
    on columns(* exclude (_source_row))
    into name column_name value label_value
),

twin_cells as (
    unpivot twins
    on columns(* exclude (_source_row))
    into name column_name value label_value
)

select original_cells._source_row
from original_cells
inner join twin_cells
    on
        original_cells._source_row = twin_cells._source_row
        and original_cells.column_name || '_normalised' = twin_cells.column_name
where original_cells.label_value is distinct from twin_cells.label_value
group by original_cells._source_row;

-- S4: the kept order lines of customer codes that need a person's look.
create or replace temp table dq_customer_lines as
select coalesce(sum(order_lines), 0) as flagged_lines
from silver_customer_codes
where f_multiple_names or f_multiple_branches or near_duplicate_count > 0;

-- The count and the net sales impact of every rule, one row each. Rows are listed by rule so
-- that each is a plain filter; S3 and S4 come from the tables built above.
create or replace temp table dq_counts as
with flagged as (
    select
        rule_id,
        count(*) as n,
        sum(net_value) as impact
    from (
        select
            'S1' as rule_id,
            net_value
        from dq_flags
        where s1
        union all
        select
            'S2' as rule_id,
            net_value
        from dq_flags
        where s2
        union all
        select
            'S5' as rule_id,
            net_value
        from dq_flags
        where s5
        union all
        select
            'S6' as rule_id,
            net_value
        from dq_flags
        where s6
        union all
        select
            'S7' as rule_id,
            net_value
        from dq_flags
        where s7
        union all
        select
            'S8' as rule_id,
            net_value
        from dq_flags
        where s8
        union all
        select
            'S9' as rule_id,
            net_value
        from dq_flags
        where s9
        union all
        select
            'S10' as rule_id,
            net_value
        from dq_flags
        where s10
        union all
        select
            'S11' as rule_id,
            net_value
        from dq_flags
        where s11
        union all
        select
            'S12' as rule_id,
            net_value
        from dq_flags
        where s12
        union all
        select
            'S3' as rule_id,
            net_value
        from dq_flags
        where _source_row in (select _source_row from dq_label_rows)
    ) as per_rule
    group by rule_id
),

rules as (
    select unnest(cast(
        ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7', 'S8', 'S9', 'S10', 'S11', 'S12']
        as varchar[]
    )) as rule_id
)

select
    rules.rule_id,
    case
        when rules.rule_id = 'S4' then (select flagged_lines from dq_customer_lines) else
            coalesce(flagged.n, 0)
    end as n,
    case when rules.rule_id in ('S1', 'S4') then null else coalesce(flagged.impact, 0) end as impact
from rules
left join flagged on rules.rule_id = flagged.rule_id;

-- The rows of each rule that have no net sales value (NULL), counted so the description can say
-- where the impact undercounts.
create or replace temp table dq_null_net as
with per_rule as (
    select
        'S2' as rule_id,
        count(*) as n
    from dq_flags
    where s2 and net_value is null
    union all
    select
        'S3' as rule_id,
        count(*) as n
    from dq_flags
    where net_value is null and _source_row in (select _source_row from dq_label_rows)
    union all
    select
        'S5' as rule_id,
        count(*) as n
    from dq_flags
    where s5 and net_value is null
    union all
    select
        'S6' as rule_id,
        count(*) as n
    from dq_flags
    where s6 and net_value is null
    union all
    select
        'S10' as rule_id,
        count(*) as n
    from dq_flags
    where s10 and net_value is null
    union all
    select
        'S11' as rule_id,
        count(*) as n
    from dq_flags
    where s11 and net_value is null
    union all
    select
        'S12' as rule_id,
        count(*) as n
    from dq_flags
    where s12 and net_value is null
)

select
    rule_id,
    n
from per_rule;

-- Voided lines (S6, AC3): the count and the net sales amount of void_flag = 1 lines, with the
-- blank and unmapped Void counts beside them. With an empty void.value_map nothing is voided.
create or replace table dq_void_effect as
select
    count(*) filter (where voided) as voided_lines,
    cast(coalesce(sum(net_value) filter (where voided), 0) as decimal(38, 4)) as voided_net_sales,
    count(*) filter (where s6) as blank_void_lines,
    count(*) filter (where unmapped_void) as unmapped_void_lines
from dq_flags;

-- The result of each rule, in rule order. pct_rows is rows_affected over all silver rows, NULL
-- when silver is empty. severity and action_taken come from config.
create or replace table dq_rule_results as
with totals as (
    select count(*) as total_rows
    from silver_sales
),

severity as (
    select
        unnest(cast($quality_severity_keys as varchar[])) as rule_id,
        unnest(cast($quality_severity_values as varchar[])) as severity
),

action as (
    select
        unnest(cast($quality_action_keys as varchar[])) as rule_id,
        unnest(cast($quality_action_values as varchar[])) as action_taken
),

descriptions as (
    select
        v.rule_id,
        v.description
    from (
        values
        ('S1', 'S1 Typing: decimal values changed by rounding to four places'),
        ('S2', 'S2 Typing: rows with a value that could not be typed (NULL, flagged f_bad)'),
        ('S3', 'S3 Labels: rows whose channel or branch label the map changed'),
        (
            'S4',
            'S4 Customers: order lines of codes with several names or branches or a near-duplicate'
        ),
        ('S5', 'S5 Exact duplicates: extra copies, first occurrence kept'),
        ('S6', 'S6 Void: rows with a blank Void, treated as not void'),
        ('S7', 'S7 Free goods: net sales 0 with a quantity above 0'),
        ('S8', 'S8 Returns: negative quantity or negative net sales'),
        ('S9', 'S9 Stray row: only Change to Ctn filled'),
        ('S10', 'S10 Excluded rows, all reasons (rows are kept in silver)'),
        ('S11', 'S11 Candidate amounts: rows with a bad value in one of the candidate columns'),
        ('S12', 'S12 Audit table: rows recorded in silver_excluded_rows')
    ) as v (rule_id, description)
)

select
    counts.rule_id,
    descriptions.description
    || case
        when counts.rule_id = 'S6'
            then
                '; voided lines (void_flag = 1): ' || cast(void.voided_lines as varchar)
                || '; unmapped Void values: ' || cast(void.unmapped_void_lines as varchar)
        else ''
    end
    || case
        when coalesce(null_net.n, 0) > 0
            then '; ' || cast(null_net.n as varchar) || ' of these rows have no net sales value'
        else ''
    end as description,
    cast(counts.n as bigint) as rows_affected,
    cast(
        case
            when totals.total_rows = 0 then null
            else round(counts.n * 100.0 / totals.total_rows, 4)
        end as decimal(9, 4)
    ) as pct_rows,
    cast(counts.impact as decimal(38, 4)) as net_sales_impact,
    action.action_taken,
    severity.severity
from dq_counts as counts
cross join totals
cross join dq_void_effect as void
inner join descriptions on counts.rule_id = descriptions.rule_id
inner join severity on counts.rule_id = severity.rule_id
inner join action on counts.rule_id = action.rule_id
left join dq_null_net as null_net on counts.rule_id = null_net.rule_id
order by cast(substr(counts.rule_id, 2) as integer);

-- Exclusions (AC4): for each reason and each candidate amount column, the rows excluded, the
-- amount they carry, the column total, and the shares. pct_of_column_total is the share of that
-- column's own total; pct_of_net_sales_total is the share of the net_sales.field total, so the
-- six columns can be read against the configured definition of net sales.
create or replace table dq_exclusion_effect as
with candidates as (
    select
        _source_row,
        exclusion_reason,
        columns(lambda c: list_contains($net_sales_candidate_columns, c))
    from silver_sales
),

cells as (
    unpivot candidates
    on columns(* exclude (_source_row, exclusion_reason))
    into name amount_column value amount
),

per_column as (
    select
        amount_column,
        sum(amount) as column_total
    from cells
    group by amount_column
),

-- unpivot drops NULL cells, so a row with no amount (the stray row) would not be counted here.
-- The number of excluded rows therefore comes from the audit table; the cells give the sums.
reason_counts as (
    select
        exclusion_reason,
        count(*) as rows_excluded
    from silver_excluded_rows
    group by exclusion_reason
),

per_reason as (
    select
        exclusion_reason,
        amount_column,
        coalesce(sum(amount), 0) as excluded_amount
    from cells
    where exclusion_reason is not null
    group by exclusion_reason, amount_column
),

reasons as (
    select unnest(cast(['exact_duplicate', 'stray_row'] as varchar[])) as exclusion_reason
),

every_pair as (
    select
        reasons.exclusion_reason,
        unnest(cast($net_sales_candidate_columns as varchar[])) as amount_column
    from reasons
),

net_total as (
    select sum(net_value) as net_sales_total
    from dq_flags
)

select
    every_pair.exclusion_reason,
    every_pair.amount_column,
    cast(coalesce(reason_counts.rows_excluded, 0) as bigint) as rows_excluded,
    cast(coalesce(per_reason.excluded_amount, 0) as decimal(38, 4)) as excluded_amount,
    cast(coalesce(per_column.column_total, 0) as decimal(38, 4)) as column_total,
    cast(
        round(
            coalesce(per_reason.excluded_amount, 0) * 100.0 / nullif(per_column.column_total, 0), 4
        ) as decimal(9, 4)
    ) as pct_of_column_total,
    cast(
        round(
            coalesce(per_reason.excluded_amount, 0) * 100.0 / nullif(net_total.net_sales_total, 0),
            4
        ) as decimal(9, 4)
    ) as pct_of_net_sales_total,
    every_pair.amount_column = $net_sales_field as is_net_sales_field
from every_pair
cross join net_total
left join per_reason
    on
        every_pair.exclusion_reason = per_reason.exclusion_reason
        and every_pair.amount_column = per_reason.amount_column
left join per_column on every_pair.amount_column = per_column.amount_column
left join reason_counts on every_pair.exclusion_reason = reason_counts.exclusion_reason
order by
    every_pair.exclusion_reason,
    list_position(
        cast($net_sales_candidate_columns as varchar[]), every_pair.amount_column
    );
