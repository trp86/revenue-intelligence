-- Value ranges of the opportunities (spec 03 section 5; story #112). Runs after the four
-- engines and before the run summary. opp_opportunities is built by the scoring story (E3-10),
-- which takes the value columns from opp_value: one row per opportunity of every engine.
-- Rules:
--   a gap is defensible when it is not NULL and above zero (each engine's gap is a measured
--   net sales amount: dormancy the lookback sales, recovery prior - current, whitespace the
--   median per buying peer, cross-sell the median B sales of customers who bought both)
--   value_low = value.low_factor x gap, value_high = value.high_factor x gap, for a defensible gap
--   only; otherwise both are NULL (no invented number)
--   value_level is set on every row from the gap's percentile within its engine (percent_rank
--   over the defensible gaps of that engine, ties share a rank): at least 2/3 High, at least 1/3
--   Medium, else Low. A gap that cannot be defended is Low. So a row always has a level, and a
--   range whenever the gap can be defended.
--   value_method states in text how the range (or the level alone) was made.
-- Value is an estimate, never a measured outcome; margin is out of scope (no cost data).
-- Parameters: $value_low_factor, $value_high_factor. The column type is a keyword, so RF04 is off
-- for this file.
-- noqa: disable=RF04

create or replace table opp_value as
with gaps as (
    select
        opp_id,
        type,
        gap,
        'the net sales in the lookback months before the last order' as gap_text
    from opp_dormancy
    union all
    select
        opp_id,
        type,
        gap,
        'prior minus current net sales (the same months one year earlier)' as gap_text
    from opp_recovery
    union all
    select
        opp_id,
        type,
        gap,
        'the median net sales in the category per buying peer' as gap_text
    from opp_whitespace
    union all
    select
        opp_id,
        type,
        gap,
        'the median net sales in B of customers who bought both A and B' as gap_text
    from opp_crosssell
),

marked as (
    select
        opp_id,
        type,
        gap,
        gap_text,
        coalesce(gap > 0, false) as defensible
    from gaps
),

ranked as (
    select
        opp_id,
        percent_rank() over (partition by type order by gap) as gap_rank
    from marked
    where defensible
)

select
    marked.opp_id,
    marked.type,
    marked.gap,
    marked.defensible as f_defensible_gap,
    case
        when marked.defensible
            then cast(cast($value_low_factor as decimal(9, 4)) * marked.gap as decimal(38, 4))
    end as value_low,
    case
        when marked.defensible
            then cast(cast($value_high_factor as decimal(9, 4)) * marked.gap as decimal(38, 4))
    end as value_high,
    case
        when not marked.defensible then 'Low'
        when ranked.gap_rank >= 2.0 / 3 then 'High'
        when ranked.gap_rank >= 1.0 / 3 then 'Medium'
        else 'Low'
    end as value_level,
    case
        when marked.defensible
            then
                'Estimate: ' || cast($value_low_factor as varchar) || ' to '
                || cast($value_high_factor as varchar) || ' x the gap, where the gap is '
                || marked.gap_text || '. Level from the gap''s percentile within '
                || marked.type || '.'
        else
            'No range: the gap (' || marked.gap_text
            || ') is missing or not above zero, so only the level Low is given.'
    end as value_method
from marked
left join ranked on marked.opp_id = ranked.opp_id
order by marked.type, marked.opp_id;
