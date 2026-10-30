-- Exclusion marking and the audit table (spec 01 S9, S10, S12; decision D1).
--
-- Silver keeps every bronze row. A row is excluded by setting is_excluded = true and giving
-- the reason; it is never deleted. The only reasons allowed are stray_row and
-- exact_duplicate (S10); 06_checks.sql fails the stage if any other reason appears.
-- Whether gold omits the rows is decided in gold (spec 02). This file does not read
-- duplicates.exclude_from_net_sales, so is_excluded and silver_excluded_rows are the same
-- whichever way that setting is (S5).

alter table silver_sales add column is_excluded boolean default false;
alter table silver_sales add column exclusion_reason varchar;
alter table silver_sales add column f_stray_row boolean default false;
-- is_duplicate is set by the exact-duplicate rule (S5, story #39). It exists from here so
-- the table shape does not change when that rule arrives.
alter table silver_sales add column is_duplicate boolean default false;

-- S9, D1: the stray row is the row where "Change to Ctn" is 1 and every other source cell
-- is blank. Every source column is looked at, so a new column cannot hide a second value.
-- Blank means NULL, empty or only spaces (silver_text). The number of matching rows is
-- checked in 06_checks.sql: more than one matching row fails the build for review.
create or replace temp table stray_rows as
with candidates as (
    select * exclude (_source_file, _sheet, _ingested_at, _file_hash)
    from read_parquet($bronze_file)
    where silver_decimal(change_to_ctn) = 1
),

cells as (
    unpivot candidates
    on columns(* exclude (_source_row))
    into name column_name value cell_value
),

stray as (
    select cast(_source_row as bigint) as _source_row
    from cells
    group by _source_row
    having
        count(*) filter (
            where silver_text(cell_value) is not null and column_name <> 'Change_to_Ctn'
        ) = 0
)

select _source_row from stray;

update silver_sales
set
    is_excluded = true,
    exclusion_reason = 'stray_row',
    f_stray_row = true
where _source_row in (select _source_row from stray_rows);
