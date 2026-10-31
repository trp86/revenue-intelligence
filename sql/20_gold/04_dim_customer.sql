-- dim_customer: one row per customer code, plus an unknown member (spec 02 section 4,
-- story #77). The code is the identity (an open business question): near-duplicate codes stay
-- separate rows, are counted and are never merged. The silver table silver_customer_codes
-- (rule S4) gives the codes and the counts; this file adds the most frequent name and the
-- attributes of the latest order.
-- Like silver_customer_codes, everything is counted over the lines silver keeps
-- (is_excluded is false): an excluded duplicate or the stray row adds nothing.
-- Parameters:
--   $customers_code_column, $customers_name_column   the code and name source columns
--   $labels_channel_columns, $labels_branch_columns  the label columns; the normalised twins
--                                                    (<column>_normalised, rule S3) are read
--   $calendar_date_column                            the typed date column
-- The columns are picked by name, so the identifier rules are switched off for this file.
-- noqa: disable=RF04,RF05,RF06,AM04,ST07,RF02

-- Blank means NULL, empty, or only spaces, tabs, line breaks and non-breaking spaces (the
-- rule silver uses).
create or replace temp macro gold_text(x) as
nullif(trim(x, ' ' || chr(9) || chr(10) || chr(13) || chr(160)), '');

create or replace temp table gold_customer_lines as
with codes as (
    select
        _source_row,
        columns(lambda c: c = $customers_code_column) as customer_code
    from silver_sales
    where not is_excluded
),

names as (
    select
        _source_row,
        gold_text(columns(lambda c: c = $customers_name_column)) as customer_name
    from silver_sales
),

channels as (
    select
        _source_row,
        gold_text(
            columns(
                lambda c: list_contains(
                    list_transform($labels_channel_columns, lambda x: x || '_normalised'), c
                )
            )
        ) as channel
    from silver_sales
),

branches as (
    select
        _source_row,
        gold_text(
            columns(
                lambda c: list_contains(
                    list_transform($labels_branch_columns, lambda x: x || '_normalised'), c
                )
            )
        ) as branch
    from silver_sales
),

dates as (
    select
        _source_row,
        columns(lambda c: c = $calendar_date_column) as order_date
    from silver_sales
)

select
    codes._source_row,
    codes.customer_code,
    names.customer_name,
    channels.channel,
    branches.branch,
    dates.order_date
from codes
inner join names on codes._source_row = names._source_row
inner join channels on codes._source_row = channels._source_row
inner join branches on codes._source_row = branches._source_row
inner join dates on codes._source_row = dates._source_row
where gold_text(codes.customer_code) is not null;

-- The name: the most frequent spelling. A tie goes to the spelling on the later order, then to
-- the lowest _source_row, so the dimension is deterministic.
create or replace temp table gold_customer_name as
with counted as (
    select
        customer_code,
        customer_name,
        count(*) as n,
        max(order_date) as last_date,
        min(_source_row) as first_row
    from gold_customer_lines
    where customer_name is not null
    group by customer_code, customer_name
),

ranked as (
    select
        customer_code,
        customer_name,
        row_number() over (
            partition by customer_code
            order by n desc, last_date desc nulls last, first_row asc
        ) as rank
    from counted
)

select
    customer_code,
    customer_name
from ranked
where rank = 1;

-- Channel and branch come from the latest order that has one: the latest date first, then the
-- lowest _source_row. A line with no date comes last. A blank value on the latest order does
-- not hide an earlier one.
create or replace temp table gold_customer_channel as
select
    customer_code,
    channel
from (
    select
        customer_code,
        channel,
        row_number() over (
            partition by customer_code order by order_date desc nulls last, _source_row asc
        ) as rank
    from gold_customer_lines
    where channel is not null
) as ranked
where rank = 1;

create or replace temp table gold_customer_branch as
select
    customer_code,
    branch
from (
    select
        customer_code,
        branch,
        row_number() over (
            partition by customer_code order by order_date desc nulls last, _source_row asc
        ) as rank
    from gold_customer_lines
    where branch is not null
) as ranked
where rank = 1;

create or replace temp table gold_customer_dates as
select
    customer_code,
    min(order_date) as first_order_date,
    max(order_date) as last_order_date
from gold_customer_lines
group by customer_code;

create or replace table dim_customer as
select
    -- A deterministic key: the first 60 bits of the md5 of the code as written (case and
    -- spaces included, so near-duplicate codes get different keys). It is positive, so it
    -- never clashes with the unknown member (-1).
    cast(cast('0x' || left(md5(codes.customer_code), 15) as hugeint) as bigint) as customer_key,
    codes.customer_code,
    coalesce(names.customer_name, 'Unknown') as customer_name,
    -- The counts come from silver_customer_codes (rule S4): distinct non-blank names and
    -- branches, and how many other codes equal this one ignoring case and padding.
    codes.name_count as n_name_variants,
    codes.branch_count as n_branches,
    codes.near_duplicate_count as n_near_duplicate_codes,
    -- f_multi_identity: the code may stand for more than one customer, or the customer may
    -- have more than one code. Any of: several names, several branches, a near-duplicate code.
    -- Nothing is merged; the flag only makes the question visible.
    codes.f_multiple_names or codes.f_multiple_branches or codes.near_duplicate_count > 0
        as f_multi_identity,
    coalesce(channels.channel, 'Unknown') as channel,
    coalesce(branches.branch, 'Unknown') as branch,
    dates.first_order_date,
    dates.last_order_date,
    codes.order_lines
from silver_customer_codes as codes
left join gold_customer_name as names on codes.customer_code = names.customer_code
left join gold_customer_channel as channels on codes.customer_code = channels.customer_code
left join gold_customer_branch as branches on codes.customer_code = branches.customer_code
left join gold_customer_dates as dates on codes.customer_code = dates.customer_code
union all
-- Unknown member: a line with a blank customer code joins here instead of being dropped.
select
    -1 as customer_key,
    cast(null as varchar) as customer_code,
    'Unknown' as customer_name,
    0 as n_name_variants,
    0 as n_branches,
    0 as n_near_duplicate_codes,
    false as f_multi_identity,
    'Unknown' as channel,
    'Unknown' as branch,
    cast(null as date) as first_order_date,
    cast(null as date) as last_order_date,
    0 as order_lines
order by customer_key;
