-- Value flags: free goods and returns (spec 01 S7, S8). Flags only: nothing is excluded or
-- changed, and every row stays in silver_sales (S10).
--
-- The value and quantity columns are the ones in config, not hard-coded:
--   $net_sales_field          the net sales column (net_sales.field)
--   $net_sales_quantity_field the quantity column (net_sales.quantity_field)
-- Both are typed columns, so the tests below read the typed values (decimal and whole
-- number), which already are NULL where the cell was blank or could not be typed (S2).
-- A NULL value or quantity is unknown, never zero and never negative, so it sets no flag.
-- coalesce(..., false) keeps every flag true or false, never NULL.

alter table silver_sales add column f_zero_value_with_qty boolean default false;
alter table silver_sales add column f_negative_qty boolean default false;
alter table silver_sales add column f_negative_value boolean default false;

create or replace temp table value_flags as
select
    _source_row,
    columns(lambda c: c = $net_sales_field) as net_value,
    columns(lambda c: c = $net_sales_quantity_field) as quantity
from silver_sales;

-- S7: net sales is 0 and quantity is above 0: possible free goods. Flagged only.
update silver_sales
set f_zero_value_with_qty = true
from value_flags
where
    silver_sales._source_row = value_flags._source_row
    and coalesce(value_flags.net_value = 0 and value_flags.quantity > 0, false);

-- S8: returns and credits are data, not errors. A negative quantity or a negative value is
-- flagged and kept.
update silver_sales
set f_negative_qty = coalesce(value_flags.quantity < 0, false)
from value_flags
where silver_sales._source_row = value_flags._source_row;

update silver_sales
set f_negative_value = coalesce(value_flags.net_value < 0, false)
from value_flags
where silver_sales._source_row = value_flags._source_row;
