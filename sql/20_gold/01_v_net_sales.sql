-- v_net_sales: the ONE place net sales is defined (spec 02 N1 to N5, story #74).
-- Every later gold file and every query reads net sales from this view and never names a
-- source amount column. This is the only gold file that does, and only through parameters:
--   $net_sales_field            the column that is net sales (N2; one of the candidates)
--   $net_sales_candidate_columns the six candidate amount columns
--   $net_sales_quantity_field   the quantity column
--   $net_sales_exclude_flags    silver flag columns that make a row "not included" (N3)
--   $duplicates_exclude_from_net_sales  whether the extra copies of exact duplicates are loaded
-- Switching net_sales.field changes the view after a gold rebuild, with no edit here (N5).
-- A view cannot take bound parameters, so the parameterised result is a table
-- (gold_net_sales_lines, rebuilt in full on every run) and v_net_sales is a view over it.
-- The columns are picked by name, so the identifier rules are switched off for this file.
-- noqa: disable=RF05,RF06,AM04,ST07,RF02

-- Rows gold loads. The stray row is never loaded. The extra copies of exact duplicates are
-- loaded only when duplicates.exclude_from_net_sales is false (they keep is_duplicate = true).
-- Silver marks both for either setting; this is where the setting takes effect. The constant
-- column no_flag keeps the flag list from being empty when no flag is configured.
create or replace table gold_net_sales_lines as
with loaded as (
    select
        *,
        false as no_flag
    from silver_sales
    where
        not is_excluded
        or (not $duplicates_exclude_from_net_sales and exclusion_reason = 'exact_duplicate')
),

net as (
    -- N2: net sales is the configured column.
    select
        _source_row,
        columns(lambda c: c = $net_sales_field) as net_sales
    from loaded
),

quantity as (
    select
        _source_row,
        columns(lambda c: c = $net_sales_quantity_field) as quantity
    from loaded
),

amounts as (
    -- AC5: every candidate amount column under a stable name, amount_<column>, so later SQL
    -- selects columns('^amount_') and never names a source amount column.
    select
        _source_row,
        columns(lambda c: list_contains($net_sales_candidate_columns, c)) as "amount_\0"
    from loaded
),

flagged as (
    -- N3: a row with any listed flag is not included. It stays in the view (and the fact).
    select
        _source_row,
        coalesce(
            list_bool_or(
                list_value(
                    *columns(
                        lambda c: c = 'no_flag' or list_contains($net_sales_exclude_flags, c)
                    )
                )
            ),
            false
        ) as any_flag
    from loaded
)

select
    net._source_row as sales_line_id,
    net.net_sales,
    $net_sales_field as net_sales_field_used,
    not flagged.any_flag as included,
    quantity.quantity,
    amounts.* exclude (_source_row)
from net
inner join quantity on net._source_row = quantity._source_row
inner join amounts on net._source_row = amounts._source_row
inner join flagged on net._source_row = flagged._source_row;

-- N4: the definition other SQL reads. net_sales_field_used says which column it is, so the
-- screens can label the definition.
create or replace view v_net_sales as
select *
from gold_net_sales_lines;
