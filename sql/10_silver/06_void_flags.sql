-- Void flags (spec 01 S6, decision D3, provisional: client to confirm).
--
-- void_flag is 1 (void), 0 (not void) or NULL (unknown). The original Void column is never
-- touched. Nothing is excluded: a voided line stays in silver and is not excluded here.
-- Whether voided lines count in net sales is an open question for gold (spec 01 section 12).
--
--   blank Void       void_flag follows $void_blank_means: not_void gives 0, void gives 1.
--                    f_blank_void is true, so the assumption stays visible and counted.
--   mapped value     void_flag comes from void.value_map. The map arrives as two lists in
--                    the same order, $void_value_map_keys and $void_value_map_values, so a
--                    value with a quote or any other character is data, never SQL.
--   unmapped value   void_flag is NULL and f_unmapped_void is true. It is reported and
--                    never guessed. With the default empty map every non-blank value is
--                    unmapped, until a person fills void.value_map from the profiling.
--
-- Blank means NULL, empty or only spaces, tabs, line breaks or non-breaking spaces. A mapped
-- value is matched exactly after trimming those at both ends, and is case-sensitive.
-- The Void column is quoted because its bronze name is mixed case.
-- noqa: disable=RF06

alter table silver_sales add column void_flag tinyint;
alter table silver_sales add column f_blank_void boolean default false;
alter table silver_sales add column f_unmapped_void boolean default false;

create or replace temp table void_map as
with pairs as (
    select
        unnest(cast($void_value_map_keys as varchar[])) as map_key,
        unnest(cast($void_value_map_values as integer[])) as map_flag
)

select
    silver_text(map_key) as void_value,
    cast(map_flag as tinyint) as flag
from pairs;

update silver_sales
set
    f_blank_void = true,
    void_flag = case when $void_blank_means = 'void' then 1 else 0 end
where silver_text("Void") is null;

update silver_sales
set void_flag = void_map.flag
from void_map
where silver_text(silver_sales."Void") = void_map.void_value;

update silver_sales
set f_unmapped_void = true
where silver_text("Void") is not null and void_flag is null;
