-- The run summary of the opportunity stage (spec 03 section 3, story #107). It runs after every
-- engine, so it sees all their evaluations.
-- opp_run_summary: one row per engine with the number of customers (or customer and category
-- pairs) evaluated, triggered and suppressed, and the suppressions by reason code. An engine with
-- no evaluation still has a row of zeros. Counts only, never a customer.
-- The checks below fail the whole stage (and roll it back) when an engine broke the contract:
-- an outcome for an engine that does not exist, a customer evaluated twice, a trigger with no
-- opportunity row or an opportunity row with no trigger, or a row with another engine's version.
-- The engine column is called type, as in spec 03, so the keyword rule is off for this file.
-- noqa: disable=RF04

select
    case
        when count(*) > 0
            then error(
                'opp_evaluations names engines that do not exist: '
                || string_agg(distinct evaluation.type, ', ' order by evaluation.type)
            )
    end as known_engines
from opp_evaluations as evaluation
left join opp_engines as engine on evaluation.type = engine.type
where engine.type is null;

select
    case
        when count(*) > 0
            then error(
                'opp_evaluations has a customer evaluated more than once by '
                || string_agg(distinct repeated.type, ', ' order by repeated.type)
            )
    end as one_evaluation_each
from (
    select evaluation.type
    from opp_evaluations as evaluation
    group by evaluation.type, evaluation.as_of_date, evaluation.customer_key, evaluation.category
    having count(*) > 1
) as repeated;

create or replace temp table opp_engine_rows as
select
    'dormancy' as type,
    opp_dormancy.customer_key,
    opp_dormancy.category,
    opp_dormancy.algo_version
from opp_dormancy
union all
select
    'recovery' as type,
    opp_recovery.customer_key,
    opp_recovery.category,
    opp_recovery.algo_version
from opp_recovery
union all
select
    'whitespace' as type,
    opp_whitespace.customer_key,
    opp_whitespace.category,
    opp_whitespace.algo_version
from opp_whitespace
union all
select
    'crosssell' as type,
    opp_crosssell.customer_key,
    opp_crosssell.category,
    opp_crosssell.algo_version
from opp_crosssell;

select
    case
        when count(*) > 0
            then error(
                'an engine row has the wrong algo_version: '
                || string_agg(distinct engine_rows.type, ', ' order by engine_rows.type)
            )
    end as right_version
from opp_engine_rows as engine_rows
inner join opp_engines as engine on engine_rows.type = engine.type
where engine_rows.algo_version is distinct from engine.algo_version;

-- Every 'triggered' evaluation has exactly one opportunity row, and every row a trigger.
select
    case
        when count(*) > 0
            then error(
                'triggers and opportunity rows do not match for '
                || string_agg(distinct coalesce(triggered.type, engine_rows.type), ', ')
            )
    end as triggers_match
from (
    select
        evaluation.type,
        evaluation.customer_key,
        evaluation.category
    from opp_evaluations as evaluation
    where evaluation.outcome = 'triggered'
) as triggered
full join opp_engine_rows as engine_rows
    on
        triggered.type = engine_rows.type
        and triggered.customer_key = engine_rows.customer_key
        and triggered.category is not distinct from engine_rows.category
where triggered.type is null or engine_rows.type is null;

create or replace table opp_run_summary as
with counted as (
    select
        evaluation.type,
        count(*) as n_evaluated,
        count(*) filter (where evaluation.outcome = 'triggered') as n_triggered,
        count(*) filter (where evaluation.outcome <> 'triggered') as n_suppressed
    from opp_evaluations as evaluation
    group by evaluation.type
),

reasons as (
    select
        per_reason.type,
        map(
            list(per_reason.outcome order by per_reason.outcome),
            list(per_reason.n order by per_reason.outcome)
        ) as suppressed_by_reason
    from (
        select
            evaluation.type,
            evaluation.outcome,
            count(*) as n
        from opp_evaluations as evaluation
        where evaluation.outcome <> 'triggered'
        group by evaluation.type, evaluation.outcome
    ) as per_reason
    group by per_reason.type
)

select
    engine.type,
    cast($asof_date as date) as as_of_date,
    engine.algo_version,
    cast(coalesce(counted.n_evaluated, 0) as bigint) as n_evaluated,
    cast(coalesce(counted.n_triggered, 0) as bigint) as n_triggered,
    cast(coalesce(counted.n_suppressed, 0) as bigint) as n_suppressed,
    coalesce(
        reasons.suppressed_by_reason,
        map(cast([] as varchar[]), cast([] as bigint[]))
    ) as suppressed_by_reason
from opp_engines as engine
left join counted on engine.type = counted.type
left join reasons on engine.type = reasons.type
order by engine.type;
