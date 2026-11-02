-- Evidence rows of the opportunities (spec 03 section 2; story #114). The measured facts behind
-- each opportunity, in long form, for the screens and for the AI evidence package (E5): the AI
-- may quote only these numbers. Runs after scoring, before the run summary.
-- One row per opportunity and fact: opp_id, fact (a name), value_number or value_date, unit,
-- kind and definition_id (an id in config/definitions.yaml: "ev_" and the fact name).
--   kind Measured  a fact taken from the data the rule used
--   kind Estimate  the value range (spec 03 section 5): an estimate, never a measured outcome
-- Facts per engine (the measures each rule used, AC3), listed in opp_evidence_facts below:
--   dormancy    days_since_last_order, median_interval_days, n_orders, last_order_date,
--               lookback_net_sales
--   recovery    prior_net_sales, current_net_sales, prior_orders, decline_pct
--   whitespace  n_peers, n_buying_peers, peer_penetration, peer_median_net_sales
--   crosssell   support, confidence, lift, median_b_net_sales
--   every row   value_low and value_high (Estimate), when the gap is defensible
-- Only numbers and dates of the opportunity: no customer name, code or free text. A fact with
-- no value (NULL) is left out.
-- The column type is a keyword, so RF04 is off for this file.
-- noqa: disable=RF04

-- The fact list: name, unit and kind of every fact.
create or replace table opp_evidence_facts as
select
    fact_list.type,
    fact_list.fact,
    fact_list.unit,
    fact_list.kind,
    'ev_' || fact_list.fact as definition_id
from (
    values
    ('dormancy', 'days_since_last_order', 'days', 'Measured'),
    ('dormancy', 'median_interval_days', 'days', 'Measured'),
    ('dormancy', 'n_orders', 'orders', 'Measured'),
    ('dormancy', 'last_order_date', 'date', 'Measured'),
    ('dormancy', 'lookback_net_sales', 'net sales', 'Measured'),
    ('recovery', 'prior_net_sales', 'net sales', 'Measured'),
    ('recovery', 'current_net_sales', 'net sales', 'Measured'),
    ('recovery', 'prior_orders', 'orders', 'Measured'),
    ('recovery', 'decline_pct', 'percent', 'Measured'),
    ('whitespace', 'n_peers', 'customers', 'Measured'),
    ('whitespace', 'n_buying_peers', 'customers', 'Measured'),
    ('whitespace', 'peer_penetration', 'share', 'Measured'),
    ('whitespace', 'peer_median_net_sales', 'net sales', 'Measured'),
    ('crosssell', 'support', 'customers', 'Measured'),
    ('crosssell', 'confidence', 'share', 'Measured'),
    ('crosssell', 'lift', 'ratio', 'Measured'),
    ('crosssell', 'median_b_net_sales', 'net sales', 'Measured'),
    ('*', 'value_low', 'net sales', 'Estimate'),
    ('*', 'value_high', 'net sales', 'Estimate')
) as fact_list (type, fact, unit, kind);

-- Every fact of every opportunity as a number (dates go to value_date).
create or replace temp table evidence_values as
with dormancy as (
    select
        opp_id,
        'dormancy' as type,
        cast(days_since_last_order as decimal(38, 4)) as days_since_last_order,
        cast(median_interval_days as decimal(38, 4)) as median_interval_days,
        cast(n_orders as decimal(38, 4)) as n_orders,
        cast(gap as decimal(38, 4)) as lookback_net_sales
    from opp_dormancy
),

recovery as (
    select
        opp_id,
        'recovery' as type,
        cast(prior_sales as decimal(38, 4)) as prior_net_sales,
        cast(current_sales as decimal(38, 4)) as current_net_sales,
        cast(prior_orders as decimal(38, 4)) as prior_orders,
        cast(decline_pct as decimal(38, 4)) as decline_pct
    from opp_recovery
),

whitespace as (
    select
        opp_id,
        'whitespace' as type,
        cast(n_peers as decimal(38, 4)) as n_peers,
        cast(n_buying_peers as decimal(38, 4)) as n_buying_peers,
        cast(peer_penetration as decimal(38, 4)) as peer_penetration,
        cast(gap as decimal(38, 4)) as peer_median_net_sales
    from opp_whitespace
),

crosssell as (
    select
        opp_id,
        'crosssell' as type,
        cast(support as decimal(38, 4)) as support,
        cast(confidence as decimal(38, 4)) as confidence,
        cast(lift as decimal(38, 4)) as lift,
        cast(gap as decimal(38, 4)) as median_b_net_sales
    from opp_crosssell
),

estimates as (
    select
        opp_id,
        '*' as type,
        value_low,
        value_high
    from opp_value
)

select
    opp_id,
    type,
    fact,
    value_number
from (
    unpivot dormancy
    on days_since_last_order, median_interval_days, n_orders, lookback_net_sales
    into name fact value value_number
)
union all
select
    opp_id,
    type,
    fact,
    value_number
from (
    unpivot recovery
    on prior_net_sales, current_net_sales, prior_orders, decline_pct
    into name fact value value_number
)
union all
select
    opp_id,
    type,
    fact,
    value_number
from (
    unpivot whitespace
    on n_peers, n_buying_peers, peer_penetration, peer_median_net_sales
    into name fact value value_number
)
union all
select
    opp_id,
    type,
    fact,
    value_number
from (
    unpivot crosssell
    on support, confidence, lift, median_b_net_sales
    into name fact value value_number
)
union all
select
    opp_id,
    type,
    fact,
    value_number
from (
    unpivot estimates
    on value_low, value_high
    into name fact value value_number
);

create or replace table opp_evidence as
with numbers as (
    select
        evidence_values.opp_id,
        evidence_values.type,
        evidence_values.fact,
        evidence_values.value_number,
        cast(null as date) as value_date
    from evidence_values
),

dates as (
    select
        opp_id,
        'dormancy' as type,
        'last_order_date' as fact,
        cast(null as decimal(38, 4)) as value_number,
        last_order_date as value_date
    from opp_dormancy
    where last_order_date is not null
),

all_facts as (
    select * from numbers
    union all
    select * from dates
)

select
    all_facts.opp_id,
    all_facts.fact,
    all_facts.value_number,
    all_facts.value_date,
    facts.unit,
    facts.kind,
    facts.definition_id
from all_facts
inner join opp_evidence_facts as facts
    on
        all_facts.type = facts.type
        and all_facts.fact = facts.fact
order by all_facts.opp_id, all_facts.fact;
