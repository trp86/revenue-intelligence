-- Silver helper macros (spec 01 S1, S2). Temporary: they live only for the stage run.

-- A cell is blank when it is NULL, empty, or only spaces, tabs, line breaks or
-- non-breaking spaces. Blank cells become NULL and are never flagged as bad.
create or replace temp macro silver_text(x) as
nullif(trim(x, ' ' || chr(9) || chr(10) || chr(13) || chr(160)), '');

-- Amounts and prices: decimal(18, 4). More than four decimals are rounded; text that is
-- not a number, or too large for the type, gives NULL.
create or replace temp macro silver_decimal(x) as
try_cast(silver_text(x) as decimal(18, 4));

-- Whole numbers. Text such as 2.5 or 1,000 gives NULL: DuckDB would round 2.5 to 3, so the
-- text is read as a decimal first and accepted only when it has no fractional part.
create or replace temp macro silver_integer(x) as
case
    when
        try_cast(silver_text(x) as decimal(38, 10))
        = floor(try_cast(silver_text(x) as decimal(38, 10)))
        then try_cast(try_cast(silver_text(x) as decimal(38, 10)) as bigint)
end;

-- Dates: ISO text (with or without a time of day) or an Excel serial number, both
-- accepted (spec 01, edge cases). Any other layout, such as 01/08/2019, is not guessed
-- and gives NULL. A serial must be between 1 and 2958465 (31 December 9999).
create or replace temp macro silver_date(x) as
coalesce(
    cast(try_strptime(
        silver_text(x),
        [
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M:%S.%g',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%d'
        ]
    ) as date),
    case
        when
            regexp_full_match(silver_text(x), '[0-9]{1,7}([.][0-9]+)?')
            and try_cast(silver_text(x) as double) between 1 and 2958465
            then
                date '1899-12-30'
                + cast(floor(try_cast(silver_text(x) as double)) as integer)
    end
);

-- S2: a value is bad when the cell is not blank but could not be typed. The typed value is
-- NULL and the flag is true; the original text stays in the _raw column.
create or replace temp macro silver_bad_decimal(x) as
silver_text(x) is not null and silver_decimal(x) is null;

create or replace temp macro silver_bad_integer(x) as
silver_text(x) is not null and silver_integer(x) is null;

create or replace temp macro silver_bad_date(x) as
silver_text(x) is not null and silver_date(x) is null;
