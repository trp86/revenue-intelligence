-- Label normalisation (spec 01 S3). A map turns a source label into its canonical name; a
-- label that has no entry is kept as it is and flagged. Nothing is excluded and no original
-- value is changed: every listed column keeps its value and gets a twin, <column>_normalised,
-- next to it. One row-level flag, f_unmapped_label, says that at least one listed column holds
-- a non-blank label with no map entry.
--
-- The columns and the maps are config, not code:
--   $labels_channel_columns / $labels_branch_columns        the columns whose values are labels
--   $labels_channel_map_keys / $labels_channel_map_values    source label -> canonical, two
--   $labels_branch_map_keys  / $labels_branch_map_values     lists in the same order
-- so a label with a quote or any other character is data, never SQL.
--
-- A label matches a key when the text is equal after trimming spaces, tabs, line breaks and
-- non-breaking spaces at both ends. Matching is case-sensitive. A blank label stays blank and
-- is not unmapped. A label with no entry is never guessed (silver_label returns it unchanged).
--
-- silver_sales is rebuilt from itself with the twins added, so every row and every column
-- written by the earlier files is kept; those files must run before this one.
-- The twin columns are named after the source column, so the identifier rules that forbid
-- special characters and mixed case are switched off for this file.
-- noqa: disable=RF05,RF06,AM04,ST07,RF02

create or replace temp macro silver_label(x, keys, vals) as
case
    when silver_text(x) is null then x
    else
        coalesce(
            vals[list_position(list_transform(keys, lambda k: silver_text(k)), silver_text(x))],
            x
        )
end;

create or replace temp macro silver_label_unmapped(x, keys) as
silver_text(x) is not null
and list_position(list_transform(keys, lambda k: silver_text(k)), silver_text(x)) is null;

create or replace temp table label_channel as
select
    _source_row,
    silver_label(
        columns(lambda c: list_contains($labels_channel_columns, c)),
        $labels_channel_map_keys,
        $labels_channel_map_values
    ) as "\0_normalised"
from silver_sales;

create or replace temp table label_branch as
select
    _source_row,
    silver_label(
        columns(lambda c: list_contains($labels_branch_columns, c)),
        $labels_branch_map_keys,
        $labels_branch_map_values
    ) as "\0_normalised"
from silver_sales;

create or replace temp table label_channel_unmapped as
select
    _source_row,
    silver_label_unmapped(
        columns(lambda c: list_contains($labels_channel_columns, c)), $labels_channel_map_keys
    ) as "\0_unmapped"
from silver_sales;

create or replace temp table label_branch_unmapped as
select
    _source_row,
    silver_label_unmapped(
        columns(lambda c: list_contains($labels_branch_columns, c)), $labels_branch_map_keys
    ) as "\0_unmapped"
from silver_sales;

-- One row-level flag: true when any listed channel or branch column is unmapped.
create or replace temp table label_unmapped_rows as
with both_kinds as (
    select *
    from label_channel_unmapped
    inner join label_branch_unmapped using (_source_row)
),

cells as (
    unpivot both_kinds
    on columns(* exclude (_source_row))
    into name column_name value is_unmapped
)

select
    _source_row,
    bool_or(is_unmapped) as f_unmapped_label
from cells
group by _source_row;

create or replace table silver_sales as
select
    s.*,
    channel.* exclude (_source_row),
    branch.* exclude (_source_row),
    coalesce(flags.f_unmapped_label, false) as f_unmapped_label
from silver_sales as s
inner join label_channel as channel using (_source_row)
inner join label_branch as branch using (_source_row)
left join label_unmapped_rows as flags using (_source_row)
order by s._source_row;
