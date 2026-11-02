-- Scoring, priority, confidence and rank (spec 03 section 4, FR-O5; story #113). Builds the
-- unified opp_opportunities from the four engine tables and opp_value (07_value.sql). It runs
-- after them and before the run summary. Components, each 0 to 1 (approved on #113):
--   value          percent_rank of the gap within its engine (0 for an undefended gap)
--   evidence       per engine, capped at 1: dormancy days since the last order / its own
--                  median interval; recovery the decline share (decline_pct / 100); whitespace
--                  the peer penetration; cross-sell the confidence
--   urgency        dormancy 1 - min(1, days quiet / scoring.urgency_horizon_days); recovery 1
--                  (the decline is in the current window); whitespace and cross-sell
--                  scoring.urgency_neutral (no change event)
--   data quality   share of the customer's sales lines up to the as-of date with none of
--                  f_zero_value_with_qty, f_negative_qty, f_negative_value or an f_bad_ flag
-- score = 100 x (weight_value x value + weight_evidence x evidence + weight_urgency x urgency +
--   weight_data_quality x data quality), rounded to 2 decimals.
-- priority: High at or above scoring.priority_high, Medium at or above priority_medium, else Low.
-- confidence: the lower of evidence and data quality; High at or above confidence_high, Medium at
--   or above confidence_medium, else Low. Capped at Medium for a customer with f_multi_identity
--   or a whitespace row whose peer group is still below the minimum size.
-- rank: 1 is best; by score, then value_high, then customer_key, then opp_id (all descending
--   except the keys), so two runs give the same order.
-- Parameters: $asof_date, $scoring_*. The columns are picked by name and the type column is a
-- keyword, so the identifier rules are off for this file.
-- noqa: disable=RF04,RF02

-- One row per counted line and f_bad_ flag that is set (the f_bad_ columns are picked by name).
create or replace temp table scoring_bad_lines as
with flags as (
    unpivot (
        select
            sales_line_id,
            columns(lambda c: starts_with(c, 'f_bad_'))
        from fact_sales
    )
    on columns(lambda c: starts_with(c, 'f_bad_'))
    into name flag value is_set
)

select distinct flags.sales_line_id
from flags
where flags.is_set;

create or replace temp table scoring_quality as
with lines as (
    select
        fact_sales.customer_key,
        coalesce(fact_sales.f_zero_value_with_qty, false) = false
        and coalesce(fact_sales.f_negative_qty, false) = false
        and coalesce(fact_sales.f_negative_value, false) = false
        and bad.sales_line_id is null as clean
    from fact_sales
    inner join asof_lines on fact_sales.sales_line_id = asof_lines.sales_line_id
    left join scoring_bad_lines as bad on fact_sales.sales_line_id = bad.sales_line_id
)

select
    customer_key,
    cast(avg(cast(clean as integer)) as decimal(9, 4)) as data_quality
from lines
group by customer_key;

create or replace temp table scoring_rows as
with engine_rows as (
    select
        opp_id,
        type,
        customer_key,
        category,
        as_of_date,
        algo_version,
        reason_codes,
        least(
            1.0, coalesce(cast(days_since_last_order as double) / median_interval_days, 1.0)
        ) as evidence,
        1.0 - least(
            1.0, cast(days_since_last_order as double) / $scoring_urgency_horizon_days
        ) as urgency,
        false as f_small_group
    from opp_dormancy
    union all
    select
        opp_id,
        type,
        customer_key,
        category,
        as_of_date,
        algo_version,
        reason_codes,
        least(1.0, greatest(0.0, cast(decline_pct as double) / 100)) as evidence,
        1.0 as urgency,
        false as f_small_group
    from opp_recovery
    union all
    select
        opp_id,
        type,
        customer_key,
        category,
        as_of_date,
        algo_version,
        reason_codes,
        cast(peer_penetration as double) as evidence,
        cast($scoring_urgency_neutral as double) as urgency,
        f_below_min_size as f_small_group
    from opp_whitespace
    union all
    select
        opp_id,
        type,
        customer_key,
        category,
        as_of_date,
        algo_version,
        reason_codes,
        cast(confidence as double) as evidence,
        cast($scoring_urgency_neutral as double) as urgency,
        false as f_small_group
    from opp_crosssell
),

ranked_value as (
    select
        opp_id,
        case
            when f_defensible_gap
                then percent_rank() over (
                    partition by type, f_defensible_gap order by gap
                )
            else 0
        end as value_component
    from opp_value
)

select
    engine_rows.*,
    ranked_value.value_component,
    coalesce(cast(quality.data_quality as double), 0) as data_quality,
    coalesce(customer.f_multi_identity, false) as f_multi_identity,
    value.value_low,
    value.value_high,
    value.value_level,
    value.value_method
from engine_rows
inner join opp_value as value on engine_rows.opp_id = value.opp_id
inner join ranked_value on engine_rows.opp_id = ranked_value.opp_id
left join scoring_quality as quality on engine_rows.customer_key = quality.customer_key
left join dim_customer as customer on engine_rows.customer_key = customer.customer_key;

insert into opp_opportunities (
    opp_id,
    type,
    customer_key,
    category,
    as_of_date,
    algo_version,
    score,
    priority,
    confidence,
    value_low,
    value_high,
    value_level,
    value_method,
    rank,
    reason_codes
)
with scored as (
    select
        *,
        round(
            100 * (
                $scoring_weight_value * value_component
                + $scoring_weight_evidence * evidence
                + $scoring_weight_urgency * urgency
                + $scoring_weight_data_quality * data_quality
            ),
            2
        ) as score_value,
        least(evidence, data_quality) as confidence_value
    from scoring_rows
),

labelled as (
    select
        *,
        case
            when score_value >= $scoring_priority_high then 'High'
            when score_value >= $scoring_priority_medium then 'Medium'
            else 'Low'
        end as priority_label,
        case
            when
                confidence_value >= $scoring_confidence_high
                and not (f_multi_identity or f_small_group)
                then 'High'
            when confidence_value >= $scoring_confidence_medium then 'Medium'
            else 'Low'
        end as confidence_label
    from scored
)

select
    opp_id,
    type,
    customer_key,
    category,
    as_of_date,
    algo_version,
    cast(score_value as decimal(9, 4)) as score,
    priority_label as priority,
    confidence_label as confidence,
    value_low,
    value_high,
    value_level,
    value_method,
    row_number() over (
        order by
            score_value desc,
            value_high desc nulls last,
            customer_key asc,
            opp_id asc
    ) as rank,
    list_concat(
        reason_codes,
        case
            when f_multi_identity or f_small_group then ['confidence_capped'] else []
        end
    ) as reason_codes
from labelled
order by rank;
