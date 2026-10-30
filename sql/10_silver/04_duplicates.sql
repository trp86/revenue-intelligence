-- Exact duplicates (spec 01 S5, decision D4, provisional: client to confirm).
--
-- Two rows are exact duplicates when every column in $duplicates_key_columns has the same
-- bronze text. By default that is every source column except _source_row; the lineage
-- columns (_source_file, _sheet, _ingested_at, _file_hash) are never compared, and
-- _source_row never is (it is what makes the rows different).
--
-- Comparison is on the text in bronze, not on the typed value: NULL, the empty string and
-- text of only spaces, tabs, line breaks or non-breaking spaces are all blank and equal each
-- other; any other text is compared exactly, with no trimming and no case folding. So 'A',
-- 'a' and 'A ' are three different values, and so are '10' and '10.0'.
--
-- In each group of identical rows the first occurrence (lowest _source_row) stays as it is.
-- Every other copy gets is_duplicate = true, is_excluded = true and the reason
-- exact_duplicate. Silver marks them whatever duplicates.exclude_from_net_sales says: that
-- setting is not read here. It only decides, in gold, whether the copies are omitted.
-- Nothing is deleted: the copy stays in silver_sales (S10).
--
-- The stray row can also be a member of a group only if another stray row exists, and two
-- stray rows already fail the build (06_checks.sql), so a stray row is never a copy.

create or replace temp macro silver_blank_to_null(x) as
case when silver_text(x) is null then null else x end;

create or replace temp table duplicate_copies as
with keyed as (
    select
        cast(_source_row as bigint) as _source_row,
        silver_blank_to_null(columns(lambda c: list_contains($duplicates_key_columns, c)))
    from read_parquet($bronze_file)
),

grouped as (
    select
        min(_source_row) as first_row,
        list(_source_row order by _source_row) as source_rows,
        columns(* exclude (_source_row))
    from keyed
    group by all
    having count(*) > 1
)

select
    first_row,
    unnest(source_rows[2:]) as _source_row
from grouped;

alter table silver_sales add column duplicate_of_source_row bigint;

update silver_sales
set
    is_duplicate = true,
    is_excluded = true,
    exclusion_reason = 'exact_duplicate',
    duplicate_of_source_row = duplicate_copies.first_row
from duplicate_copies
where silver_sales._source_row = duplicate_copies._source_row;
