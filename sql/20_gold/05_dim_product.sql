-- dim_product: one row per product code, plus an unknown member (spec 02 section 4, story #78).
-- The columns were chosen from profiling (story #73, spec 02 section 12) and are config:
--   $product_code_column, $product_name_column, $product_brand_column, $product_category_column
-- The code is the identity, taken as written (trimmed): near-duplicate codes would stay
-- separate rows. Everything is counted over the lines silver keeps (is_excluded is false), so
-- an excluded duplicate or the stray row adds nothing.
-- A product code with several values in a column takes the most frequent value; a tie goes to
-- the value on the lowest _source_row (the rule recorded in spec 02 section 12). Values are
-- compared as trimmed text with the case kept; a blank beside a value is not a conflict.
-- The columns are picked by name, so the identifier rules are switched off for this file.
-- noqa: disable=RF04,RF05,RF06,AM04,ST07,RF02

-- Blank means NULL, empty, or only spaces, tabs, line breaks and non-breaking spaces (the
-- rule silver uses). The text is trimmed at both ends.
create or replace temp macro gold_text(x) as
nullif(trim(x, ' ' || chr(9) || chr(10) || chr(13) || chr(160)), '');

create or replace temp table gold_product_lines as
with codes as (
    select
        _source_row,
        gold_text(columns(lambda c: c = $product_code_column)) as product_code
    from silver_sales
    where not is_excluded
),

names as (
    select
        _source_row,
        gold_text(columns(lambda c: c = $product_name_column)) as product_name
    from silver_sales
),

brands as (
    select
        _source_row,
        gold_text(columns(lambda c: c = $product_brand_column)) as brand
    from silver_sales
),

categories as (
    select
        _source_row,
        gold_text(columns(lambda c: c = $product_category_column)) as category
    from silver_sales
)

select
    codes._source_row,
    codes.product_code,
    names.product_name,
    brands.brand,
    categories.category
from codes
inner join names on codes._source_row = names._source_row
inner join brands on codes._source_row = brands._source_row
inner join categories on codes._source_row = categories._source_row
where codes.product_code is not null;

-- The most frequent value of each column per code, and how many different values it has. A
-- tie goes to the value on the lowest _source_row. The three queries differ only in the
-- column they read (name, brand, category).
create or replace temp table gold_product_name as
with counted as (
    select
        product_code,
        product_name as value,
        count(*) as n,
        min(_source_row) as first_row
    from gold_product_lines
    where product_name is not null
    group by product_code, product_name
)

select
    product_code,
    value,
    n_values
from (
    select
        product_code,
        value,
        count(*) over (partition by product_code) as n_values,
        row_number() over (partition by product_code order by n desc, first_row asc) as rank
    from counted
) as ranked
where rank = 1;

create or replace temp table gold_product_brand as
with counted as (
    select
        product_code,
        brand as value,
        count(*) as n,
        min(_source_row) as first_row
    from gold_product_lines
    where brand is not null
    group by product_code, brand
)

select
    product_code,
    value,
    n_values
from (
    select
        product_code,
        value,
        count(*) over (partition by product_code) as n_values,
        row_number() over (partition by product_code order by n desc, first_row asc) as rank
    from counted
) as ranked
where rank = 1;

create or replace temp table gold_product_category as
with counted as (
    select
        product_code,
        category as value,
        count(*) as n,
        min(_source_row) as first_row
    from gold_product_lines
    where category is not null
    group by product_code, category
)

select
    product_code,
    value,
    n_values
from (
    select
        product_code,
        value,
        count(*) over (partition by product_code) as n_values,
        row_number() over (partition by product_code order by n desc, first_row asc) as rank
    from counted
) as ranked
where rank = 1;

create or replace table dim_product as
with codes as (
    select
        product_code,
        count(*) as order_lines
    from gold_product_lines
    group by product_code
)

select
    -- A deterministic key: the first 60 bits of the md5 of the code as written. It is
    -- positive, so it never clashes with the unknown member (-1).
    cast(cast('0x' || left(md5(codes.product_code), 15) as hugeint) as bigint) as product_key,
    codes.product_code,
    coalesce(names.value, 'Unknown') as product_name,
    coalesce(brands.value, 'Unknown') as brand,
    -- A product with no category in the source gets category Unknown and f_no_category.
    coalesce(categories.value, 'Unknown') as category,
    coalesce(names.n_values, 0) as n_name_values,
    coalesce(brands.n_values, 0) as n_brand_values,
    coalesce(categories.n_values, 0) as n_category_values,
    -- f_value_conflict: the source gives the code several values in at least one column. The
    -- most frequent is used; the flag says the choice was a judgement.
    coalesce(names.n_values, 0) > 1
    or coalesce(brands.n_values, 0) > 1
    or coalesce(categories.n_values, 0) > 1 as f_value_conflict,
    categories.value is null as f_no_category,
    codes.order_lines
from codes
left join gold_product_name as names on codes.product_code = names.product_code
left join gold_product_brand as brands on codes.product_code = brands.product_code
left join gold_product_category as categories on codes.product_code = categories.product_code
union all
-- Unknown member: a line with a blank product code joins here instead of being dropped.
select
    -1 as product_key,
    cast(null as varchar) as product_code,
    'Unknown' as product_name,
    'Unknown' as brand,
    'Unknown' as category,
    0 as n_name_values,
    0 as n_brand_values,
    0 as n_category_values,
    false as f_value_conflict,
    true as f_no_category,
    0 as order_lines
order by product_key;
