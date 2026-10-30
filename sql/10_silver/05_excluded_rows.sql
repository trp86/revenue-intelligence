-- S12: every excluded row is recorded here, with the six candidate amount columns so the
-- revenue effect of the exclusions can be reported without printing any row. Only counts
-- and sums leave the warehouse file. Written by the build; never edited by hand, and
-- rebuilt in full on every silver build.
--
-- It runs after every file that can exclude a row (03_exclusions.sql for the stray row,
-- 04_duplicates.sql for exact duplicates), so it holds all of them.
-- duplicate_of_source_row is the kept first occurrence for an exact duplicate and NULL for
-- a stray row. excluded_at is one UTC timestamp for the whole build.
create or replace table silver_excluded_rows as
select
    _source_row,
    exclusion_reason,
    duplicate_of_source_row,
    selling_amount,
    net_amount_1,
    amount_af_dis,
    net_amount_2,
    net_amount_3,
    tax_amount,
    cast(now() at time zone 'UTC' as timestamp) as excluded_at
from silver_sales
where is_excluded
order by _source_row;
