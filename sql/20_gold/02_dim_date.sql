-- dim_date: one row per calendar day, plus an unknown member (spec 02 section 4, story #75).
-- Grain: one day. The days run from the first to the last date in silver_sales, with no gaps,
-- so a month with no sales still has its days. Dates silver could not type (NULL) add no day.
-- Parameters:
--   $calendar_date_column            the typed silver date column the range is taken from
--   $calendar_fiscal_year_start_month the month (1 to 12) the fiscal year starts in
--   $asof_date                       the as-of date of the data
-- The date column is picked by name, so the identifier rules are switched off for this file.
-- noqa: disable=RF04,RF05,RF06,AM04,ST07,RF02

create or replace table dim_date as
with bounds as (
    select
        min(columns(lambda c: c = $calendar_date_column)) as first_date,
        max(columns(lambda c: c = $calendar_date_column)) as last_date
    from silver_sales
),

days as (
    -- One row per calendar day. generate_series gives timestamps, so cast back to a date.
    select cast(unnest(generate_series(first_date, last_date, interval 1 day)) as date) as date
    from bounds
    where first_date is not null
),

calendar as (
    select
        date,
        -- The key is the day as yyyymmdd: deterministic and the same in every warehouse.
        cast(strftime(date, '%Y%m%d') as integer) as date_key,
        -- Weeks are ISO weeks (Monday first); iso_year is the year the ISO week belongs to,
        -- which differs from year around New Year (30 December 2019 is week 1 of 2020).
        week(date) as week,
        isoyear(date) as iso_year,
        cast(date_trunc('week', date) as date) as week_start,
        month(date) as month,
        quarter(date) as quarter,
        year(date) as year,
        cast(date_trunc('month', date) as date) as month_start
    from days
)

select
    date_key,
    date,
    week,
    iso_year,
    week_start,
    month,
    quarter,
    year,
    month_start,
    -- Fiscal year is named by the calendar year it starts in; with start month 1 it equals the
    -- calendar year. A date before the start month belongs to the fiscal year that began the
    -- year before.
    year - case when month < $calendar_fiscal_year_start_month then 1 else 0 end as fiscal_year,
    -- Fiscal quarters count three months from the start month.
    (month - $calendar_fiscal_year_start_month + 12) % 12 // 3 + 1 as fiscal_quarter,
    -- f_after_asof: the day is after the as-of date of the data (asof.date). The fact uses it
    -- to flag a line dated after the as-of date; the line is kept (spec 02 section 9).
    date > cast($asof_date as date) as f_after_asof
from calendar
union all
-- Unknown member: lines with no usable date join here instead of being dropped.
select
    -1 as date_key,
    cast(null as date) as date,
    cast(null as integer) as week,
    cast(null as integer) as iso_year,
    cast(null as date) as week_start,
    cast(null as integer) as month,
    cast(null as integer) as quarter,
    cast(null as integer) as year,
    cast(null as date) as month_start,
    cast(null as integer) as fiscal_year,
    cast(null as integer) as fiscal_quarter,
    false as f_after_asof
order by date_key;
