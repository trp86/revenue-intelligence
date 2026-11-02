-- The cross-sell engine (spec 03 section 3.4, FR-O4; story #111). Categories that customers who
-- bought A often add as B, at category level. It reads only the as-of inputs, so only data on
-- or before the as-of date is used. The unknown customer (-1) and the category 'Unknown' are
-- left out everywhere: 'Unknown' is neither A nor B.
-- Pair measures, over every known customer's purchases up to the as-of date (a customer buys a
-- category when its net sales in it are above zero):
--   support     customers who bought both A and B
--   confidence  support / customers who bought A
--   lift        confidence / (customers who bought B / customers who bought any category)
-- A pair passes when support >= crosssell.min_support AND confidence >= min_confidence AND
-- lift >= min_lift (all "at least"). Every ordered pair with support above zero is kept in
-- opp_crosssell_pairs with its outcome: passed, or the first threshold it fails in that order
-- (below_min_support, below_min_confidence, below_min_lift).
-- Candidate: a customer that bought A in the crosssell.lookback_months months ending with the
-- as-of month (net sales above zero there) and never bought B (no sales line in B up to the
-- as-of date). One evaluation, and at most one opportunity, per customer and category B: the
-- outcome is triggered when any of its pairs passes, otherwise the threshold its furthest pair
-- failed (lift is furthest, support nearest). A triggered row keeps the strongest passing pair:
-- highest lift, then confidence, then support, then the name of A.
-- gap: the median net sales in B among customers who bought both A and B (approved definition).
-- reason_codes on a triggered row: support_at_least_min, confidence_at_least_min,
-- lift_at_least_min, bought_a_in_lookback, never_bought_b.
-- Parameters: $asof_date, $crosssell_min_support, $crosssell_min_confidence, $crosssell_min_lift,
-- $crosssell_lookback_months. The column type is a keyword, so RF04 is off for this file.
-- noqa: disable=RF04

alter table opp_crosssell add column category_a varchar;
alter table opp_crosssell add column support bigint;
alter table opp_crosssell add column confidence decimal(9, 4);
alter table opp_crosssell add column lift decimal(18, 4);

-- Each known customer's net sales and lines per category up to the as-of date.
create or replace temp table crosssell_customer_category as
select
    customer_key,
    category,
    sum(net_sales) as net_sales,
    sum(n_lines) as n_lines
from asof_customer_category_month
where customer_key <> -1 and category <> 'Unknown'
group by customer_key, category
having sum(n_lines) > 0;

create or replace temp table crosssell_buys as
select
    customer_key,
    category,
    net_sales
from crosssell_customer_category
where net_sales > 0;

create or replace temp table crosssell_pair_stats as
with buyers as (
    select
        category,
        count(*) as n_buyers
    from crosssell_buys
    group by category
),

total as (
    select count(distinct customer_key) as n_customers
    from crosssell_buys
),

both_bought as (
    select
        a.category as category_a,
        b.category as category_b,
        count(*) as support,
        median(b.net_sales) as median_b_net_sales
    from crosssell_buys as a
    inner join crosssell_buys as b
        on a.customer_key = b.customer_key and a.category <> b.category
    group by a.category, b.category
)

select
    both_bought.category_a,
    both_bought.category_b,
    both_bought.support,
    both_bought.median_b_net_sales,
    cast(
        cast(both_bought.support as decimal(18, 4)) / cast(buyers_a.n_buyers as decimal(18, 4))
        as decimal(9, 4)
    ) as confidence,
    cast(
        (cast(both_bought.support as decimal(18, 4)) / cast(buyers_a.n_buyers as decimal(18, 4)))
        / (cast(buyers_b.n_buyers as decimal(18, 4)) / cast(total.n_customers as decimal(18, 4)))
        as decimal(18, 4)
    ) as lift
from both_bought
inner join buyers as buyers_a on both_bought.category_a = buyers_a.category
inner join buyers as buyers_b on both_bought.category_b = buyers_b.category
cross join total;

-- Every pair with its outcome: the first threshold it fails, or passed. stage orders the
-- outcomes by how far the pair got (1 support failed .. 4 passed).
create or replace table opp_crosssell_pairs as
select
    cast($asof_date as date) as as_of_date,
    category_a,
    category_b,
    support,
    confidence,
    lift,
    cast(median_b_net_sales as decimal(38, 4)) as median_b_net_sales,
    case
        when support < $crosssell_min_support then 'below_min_support'
        when confidence < $crosssell_min_confidence then 'below_min_confidence'
        when lift < $crosssell_min_lift then 'below_min_lift'
        else 'passed'
    end as outcome,
    case
        when support < $crosssell_min_support then 1
        when confidence < $crosssell_min_confidence then 2
        when lift < $crosssell_min_lift then 3
        else 4
    end as stage
from crosssell_pair_stats
order by category_a, category_b;

-- Customers that bought A in the lookback months.
create or replace temp table crosssell_recent_a as
select
    customer_key,
    category
from asof_customer_category_month
where
    customer_key <> -1
    and category <> 'Unknown'
    and month_start
    >= cast(
        date_trunc('month', cast($asof_date as date))
        - to_months(cast($crosssell_lookback_months as integer) - 1) as date
    )
    and month_start <= cast(date_trunc('month', cast($asof_date as date)) as date)
group by customer_key, category
having sum(net_sales) > 0;

-- Each candidate pair: bought A in the lookback, never a line in B.
create or replace temp table crosssell_candidates as
select
    recent.customer_key,
    pairs.category_a,
    pairs.category_b,
    pairs.support,
    pairs.confidence,
    pairs.lift,
    pairs.median_b_net_sales,
    pairs.stage,
    row_number() over (
        partition by recent.customer_key, pairs.category_b
        order by
            pairs.stage desc,
            pairs.lift desc,
            pairs.confidence desc,
            pairs.support desc,
            pairs.category_a asc
    ) as pick
from crosssell_recent_a as recent
inner join opp_crosssell_pairs as pairs on recent.category = pairs.category_a
left join crosssell_customer_category as ever_b
    on
        recent.customer_key = ever_b.customer_key
        and pairs.category_b = ever_b.category
where ever_b.customer_key is null;

insert into opp_evaluations (type, as_of_date, customer_key, category, outcome)
select
    'crosssell' as type,
    cast($asof_date as date) as as_of_date,
    customer_key,
    category_b as category,
    case stage
        when 4 then 'triggered'
        when 3 then 'below_min_lift'
        when 2 then 'below_min_confidence'
        else 'below_min_support'
    end as outcome
from crosssell_candidates
where pick = 1;

insert into opp_crosssell (
    opp_id,
    type,
    customer_key,
    category,
    as_of_date,
    algo_version,
    gap,
    reason_codes,
    category_a,
    support,
    confidence,
    lift
)
select
    opp_id(
        'crosssell', candidates.customer_key, candidates.category_b, cast($asof_date as date)
    ) as opp_id,
    'crosssell' as type,
    candidates.customer_key,
    candidates.category_b as category,
    cast($asof_date as date) as as_of_date,
    engine.algo_version,
    candidates.median_b_net_sales as gap,
    [
        'support_at_least_min',
        'confidence_at_least_min',
        'lift_at_least_min',
        'bought_a_in_lookback',
        'never_bought_b'
    ] as reason_codes,
    candidates.category_a,
    candidates.support,
    candidates.confidence,
    candidates.lift
from crosssell_candidates as candidates
inner join opp_engines as engine on engine.type = 'crosssell'
where candidates.pick = 1 and candidates.stage = 4;
