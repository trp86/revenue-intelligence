-- The opportunity schema (spec 03 section 2, story #107). Every run rebuilds these tables in
-- full, so nothing from an earlier run is left over; the engines (later files) fill them.
--   opp_engines        the four engines and the algo_version each stores on its rows. A change to
--                      an engine's rule must raise its version, so a stored row says which rule
--                      made it.
--   opp_evaluations    one row per customer (and category, for the category engines) an engine
--                      looked at, with its outcome: 'triggered' or the reason it was not
--                      (for example insufficient_history). 90_run_summary.sql counts these.
--   opp_<engine>       the opportunities one engine found, with its measured gap. The identity
--                      columns are the same in every engine table; an engine adds its own.
--   opp_opportunities  every engine's opportunities in one ranked table, built by the scoring
--                      file (story E3-10). Empty until then.
-- opp_id(type, customer_key, category, as_of_date) is the opportunity's id: the md5 of a JSON
-- list of the four values, so the same opportunity on the same as-of date always has the same
-- id, a NULL category differs from an empty one, and a separator inside a value cannot make two
-- ids collide. The category is text (there is no category key in gold).

create or replace temp macro opp_id(type, customer_key, category, as_of_date) as
md5(
    to_json([
        cast(type as varchar),
        cast(customer_key as varchar),
        cast(category as varchar),
        cast(as_of_date as varchar)
    ])
);

create or replace table opp_engines as
select
    engine.type,
    engine.algo_version
from (
    values
    ('dormancy', 'dormancy-1'),
    ('recovery', 'recovery-1'),
    ('whitespace', 'whitespace-1'),
    ('crosssell', 'crosssell-1')
) as engine (type, algo_version);

create or replace table opp_evaluations (
    type varchar not null,
    as_of_date date not null,
    customer_key bigint not null,
    category varchar,
    outcome varchar not null
);

create or replace table opp_dormancy (
    opp_id varchar primary key,
    type varchar not null,
    customer_key bigint not null,
    category varchar,
    as_of_date date not null,
    algo_version varchar not null,
    gap decimal(38, 4),
    reason_codes varchar[]
);

create or replace table opp_recovery (
    opp_id varchar primary key,
    type varchar not null,
    customer_key bigint not null,
    category varchar,
    as_of_date date not null,
    algo_version varchar not null,
    gap decimal(38, 4),
    reason_codes varchar[]
);

create or replace table opp_whitespace (
    opp_id varchar primary key,
    type varchar not null,
    customer_key bigint not null,
    category varchar,
    as_of_date date not null,
    algo_version varchar not null,
    gap decimal(38, 4),
    reason_codes varchar[]
);

create or replace table opp_crosssell (
    opp_id varchar primary key,
    type varchar not null,
    customer_key bigint not null,
    category varchar,
    as_of_date date not null,
    algo_version varchar not null,
    gap decimal(38, 4),
    reason_codes varchar[]
);

create or replace table opp_opportunities (
    opp_id varchar primary key,
    type varchar not null,
    customer_key bigint not null,
    category varchar,
    as_of_date date not null,
    algo_version varchar not null,
    score decimal(9, 4),
    priority varchar,
    confidence varchar,
    value_low decimal(38, 4),
    value_high decimal(38, 4),
    value_level varchar,
    value_method varchar,
    rank bigint,
    reason_codes varchar[]
);
