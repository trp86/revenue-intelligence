-- dim_branch: one row per normalised branch, plus an unknown member (spec 02 section 4,
-- story #76).
-- Grain: one branch. The name is the normalised twin of the branch label column (silver
-- rule S3), so the variants the label map joins are one branch and labels it does not join
-- stay separate. Nothing is merged here beyond that map. Names are trimmed at both ends.
-- Parameters:
--   $labels_branch_columns             the branch label column (exactly one; gold checks it)
--   $regions_source_column             the source column a region defaults to
--   $regions_branch_to_region_keys / _values   branch name -> region, overrides the column
-- The columns are picked by name, so the identifier rules are switched off for this file.
-- noqa: disable=RF04,RF05,RF06,AM04,ST07,RF02

-- Blank means NULL, empty, or only spaces, tabs, line breaks and non-breaking spaces (the
-- rule silver uses). The text is trimmed at both ends.
create or replace temp macro gold_text(x) as
nullif(trim(x, ' ' || chr(9) || chr(10) || chr(13) || chr(160)), '');

create or replace temp table gold_branch_lines as
with names as (
    select
        _source_row,
        gold_text(
            columns(
                lambda c: list_contains(
                    list_transform($labels_branch_columns, lambda x: x || '_normalised'), c
                )
            )
        ) as branch_name
    from silver_sales
),

regions as (
    select
        _source_row,
        gold_text(columns(lambda c: c = $regions_source_column)) as region
    from silver_sales
)

select
    names._source_row,
    names.branch_name,
    regions.region
from names
inner join regions on names._source_row = regions._source_row
where names.branch_name is not null;

-- The region of a branch from the source column: the most frequent non-blank value. A tie goes
-- to the value on the lowest _source_row. The number of different values decides the flag.
create or replace temp table gold_branch_source_region as
with counted as (
    select
        branch_name,
        region,
        count(*) as n,
        min(_source_row) as first_row
    from gold_branch_lines
    where region is not null
    group by branch_name, region
),

ranked as (
    select
        branch_name,
        region,
        row_number() over (partition by branch_name order by n desc, first_row asc) as rank,
        count(*) over (partition by branch_name) as n_values
    from counted
)

select
    branch_name,
    region,
    n_values
from ranked
where rank = 1;

-- The config override: branch name -> region. A key matches after trimming both ends and is
-- case-sensitive, the way the label maps work.
create or replace temp table gold_branch_config_region as
select
    gold_text(key) as branch_name,
    gold_text(region) as region
from (
    select
        unnest(cast($regions_branch_to_region_keys as varchar[])) as key,
        unnest(cast($regions_branch_to_region_values as varchar[])) as region
) as pairs;

create or replace table dim_branch as
with branches as (
    select distinct branch_name
    from gold_branch_lines
)

select
    -- A deterministic key: the first 60 bits of the md5 of the name. It is positive, so it never
    -- clashes with the unknown member (-1), and it is the same in every warehouse.
    cast(cast('0x' || left(md5(branches.branch_name), 15) as hugeint) as bigint) as branch_key,
    branches.branch_name,
    -- Region: the config map first, then the source column, else Unknown.
    coalesce(config.region, source.region, 'Unknown') as region,
    case
        when config.region is not null then 'config'
        when source.region is not null then 'source'
        else 'unknown'
    end as region_source,
    -- f_region_conflict: the source column gives the branch several regions and the config does
    -- not settle it. The most frequent one is used; the flag says the choice was a judgement.
    config.region is null and coalesce(source.n_values, 0) > 1 as f_region_conflict
from branches
left join gold_branch_source_region as source on branches.branch_name = source.branch_name
left join gold_branch_config_region as config on branches.branch_name = config.branch_name
union all
-- Unknown member: a line with no branch joins here instead of being dropped.
select
    -1 as branch_key,
    'Unknown' as branch_name,
    'Unknown' as region,
    'unknown' as region_source,
    false as f_region_conflict
order by branch_key;
