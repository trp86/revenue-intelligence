"""Profile the opportunity engine thresholds on the built gold layer (spec 03 section 10).

Story #105 chooses the open defaults (`recovery.min_prior_sales`, `opportunities.top_n_per_type`)
from evidence. For each engine this counts the customers (or customer and category pairs, or
category pairs) evaluated and how many each default threshold of `config/settings.yaml` would
flag, at the configured as-of date. Run it with `uv run python -m revint.threshold_profile`.

It reads what the engines will read: the as-of inputs (story #106), built from gold. They are
built on a temporary copy of the warehouse, so the warehouse itself is never written. Output is
counts and percentiles only: no customer code, name or the amount of one customer is printed,
logged or returned. Percentiles are left out when fewer than `MIN_CUSTOMERS_FOR_PERCENTILES`
customers are evaluated, so a percentile cannot be one customer's amount.

The engines (stories E3-5 to E3-8) are not built yet, so a few readings here are the profile's
own, stated in `READINGS` and printed with the result. The unknown customer (key -1) and the
'Unknown' category are left out, as nothing can be recommended to them.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date as Date
from pathlib import Path
from typing import Any

import duckdb

from revint.config import ConfigError, Settings, load_settings
from revint.opportunities import OpportunitiesError, run_opportunities

logger = logging.getLogger(__name__)

EXIT_PROFILE_FAILED = 4
MIN_CUSTOMERS_FOR_PERCENTILES = 10
PERCENTILES = (0.10, 0.25, 0.50, 0.75, 0.90)

READINGS = (
    "Recovery: the current window is the last window_months months ending at the as-of date "
    "(from the first day of the first month); the prior window is the same dates one year "
    "earlier. A customer is evaluated when it has an order in the prior window.",
    "Dormancy: 'sales in the lookback before going quiet' is read as positive net sales in the "
    "lookback_months months ending with the month of the last order.",
    "Whitespace: a customer is evaluated when its peer group (after the fallback) has at least "
    "peer_groups.min_size customers; 'bought' means positive net sales in the window.",
    "Cross-sell: pairs are ordered category pairs A -> B among the categories bought in the "
    "lookback; a candidate bought A in the lookback and never bought B up to the as-of date.",
)


class ProfileError(Exception):
    """The threshold profile could not be made."""


@dataclass(frozen=True)
class RecoveryProfile:
    evaluated: int
    prior_sales_percentiles: dict[str, float] | None
    pass_min_decline_pct: int
    pass_min_prior_orders: int
    pass_min_prior_sales: int
    flagged: int
    flagged_not_dormant: int
    flagged_at_prior_sales_percentile: dict[str, int] | None


@dataclass(frozen=True)
class DormancyProfile:
    evaluated: int
    insufficient_history: int
    pass_interval_multiple: int
    pass_min_days: int
    pass_lookback_sales: int
    flagged: int


@dataclass(frozen=True)
class WhitespaceProfile:
    customers: int
    small_peer_group: int
    evaluated: int
    eligible_pairs: int
    flagged_pairs: int
    flagged_customers: int


@dataclass(frozen=True)
class CrosssellProfile:
    buying_customers: int
    categories: int
    evaluated_pairs: int
    pass_min_support: int
    pass_min_confidence: int
    pass_min_lift: int
    flagged_pairs: int
    candidates: int
    candidate_customers: int


@dataclass(frozen=True)
class ThresholdProfile:
    as_of_date: Date
    thresholds: dict[str, dict[str, Any]]
    recovery: RecoveryProfile
    dormancy: DormancyProfile
    whitespace: WhitespaceProfile
    crosssell: CrosssellProfile

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["as_of_date"] = self.as_of_date.isoformat()
        data["readings"] = list(READINGS)
        return data


def _thresholds(settings: Settings) -> dict[str, dict[str, Any]]:
    return {
        "recovery": settings.recovery.model_dump(),
        "dormancy": settings.dormancy.model_dump(),
        "whitespace": {
            **settings.whitespace.model_dump(),
            "peer_groups_min_size": settings.peer_groups.min_size,
        },
        "crosssell": settings.crosssell.model_dump(),
        "opportunities": settings.opportunities.model_dump(),
    }


def _params(settings: Settings) -> dict[str, Any]:
    return {
        "asof": settings.asof.date,
        "r_window": settings.recovery.window_months,
        "r_decline": settings.recovery.min_decline_pct,
        "r_prior_sales": settings.recovery.min_prior_sales,
        "r_prior_orders": settings.recovery.min_prior_orders,
        "d_min_orders": settings.dormancy.min_orders,
        "d_multiple": settings.dormancy.interval_multiple,
        "d_min_days": settings.dormancy.min_days,
        "d_lookback": settings.dormancy.lookback_months,
        "w_penetration": settings.whitespace.min_peer_penetration,
        "w_lookback": settings.whitespace.lookback_months,
        "pg_min_size": settings.peer_groups.min_size,
        "pg_columns": list(settings.peer_groups.columns),
        "pg_fallback": list(settings.peer_groups.fallback_columns),
        "c_support": settings.crosssell.min_support,
        "c_confidence": settings.crosssell.min_confidence,
        "c_lift": settings.crosssell.min_lift,
        "c_lookback": settings.crosssell.lookback_months,
    }


def _run(con: duckdb.DuckDBPyConnection, sql: str, params: dict[str, Any]) -> Any:
    """Run `sql` with only the parameters it names."""
    used = {name: value for name, value in params.items() if f"${name}" in sql}
    return con.execute(sql, used)


_DORMANCY = """
create or replace temp table prof_dormancy as
with profile as (
    select
        customer_key,
        n_orders,
        median_interval_days,
        last_order_date,
        date_diff('day', last_order_date, cast($asof as date)) as days_quiet
    from asof_customer_profile
    where customer_key <> -1
),

lookback as (
    select
        profile.customer_key,
        sum(month.net_sales) as lookback_sales
    from profile
    inner join asof_customer_month as month
        on
            profile.customer_key = month.customer_key
            and month.month_start between
            cast(date_trunc('month', profile.last_order_date) - to_months($d_lookback - 1) as date)
            and cast(date_trunc('month', profile.last_order_date) as date)
    group by profile.customer_key
)

select
    profile.customer_key,
    profile.n_orders >= $d_min_orders as enough_history,
    coalesce(profile.days_quiet > $d_multiple * profile.median_interval_days, false)
        as past_interval,
    profile.days_quiet > $d_min_days as past_min_days,
    coalesce(lookback.lookback_sales, 0) > 0 as had_sales
from profile
left join lookback on profile.customer_key = lookback.customer_key
"""

_DORMANCY_COUNTS = """
select
    count(*),
    count(*) filter (where not enough_history),
    count(*) filter (where enough_history and past_interval),
    count(*) filter (where enough_history and past_min_days),
    count(*) filter (where enough_history and had_sales),
    count(*) filter (where enough_history and past_interval and past_min_days and had_sales)
from prof_dormancy
"""

_RECOVERY = """
create or replace temp table prof_recovery as
with window_dates as (
    select
        cast(
            date_trunc('month', cast($asof as date)) - to_months($r_window - 1) as date
        ) as current_start,
        cast($asof as date) as current_end
),

bounds as (
    select
        current_start,
        current_end,
        cast(current_start - to_months(12) as date) as prior_start,
        cast(current_end - to_months(12) as date) as prior_end
    from window_dates
),

per_customer as (
    select
        orders.customer_key,
        sum(orders.net_sales) filter (
            where orders.order_date between bounds.current_start and bounds.current_end
        ) as current_sales,
        sum(orders.net_sales) filter (
            where orders.order_date between bounds.prior_start and bounds.prior_end
        ) as prior_sales,
        count(*) filter (
            where orders.order_date between bounds.prior_start and bounds.prior_end
        ) as prior_orders
    from asof_orders as orders
    cross join bounds
    where orders.customer_key <> -1
    group by orders.customer_key
)

select
    per_customer.customer_key,
    per_customer.prior_sales,
    per_customer.prior_orders,
    case
        when per_customer.prior_sales > 0
            then (per_customer.prior_sales - coalesce(per_customer.current_sales, 0))
            / per_customer.prior_sales * 100
    end as decline_pct,
    coalesce(dormancy.enough_history and dormancy.past_interval and dormancy.past_min_days
        and dormancy.had_sales, false) as dormant
from per_customer
left join prof_dormancy as dormancy on per_customer.customer_key = dormancy.customer_key
where per_customer.prior_orders > 0
"""

_RECOVERY_COUNTS = """
select
    count(*),
    count(*) filter (where decline_pct >= $r_decline),
    count(*) filter (where prior_orders >= $r_prior_orders),
    count(*) filter (where prior_sales >= $r_prior_sales),
    count(*) filter (
        where decline_pct >= $r_decline
        and prior_orders >= $r_prior_orders
        and prior_sales >= $r_prior_sales
    ),
    count(*) filter (
        where decline_pct >= $r_decline
        and prior_orders >= $r_prior_orders
        and prior_sales >= $r_prior_sales
        and not dormant
    )
from prof_recovery
"""

_WHITESPACE = """
create or replace temp table prof_whitespace as
with plan as (
    select
        cast($pg_min_size as bigint) as min_size,
        cast($pg_columns as varchar[]) as group_columns,
        cast($pg_fallback as varchar[]) as fallback_columns
),

plan_positions as (
    select
        min_size,
        group_columns,
        fallback_columns,
        len(fallback_columns) > 0 and len(fallback_columns) < len(group_columns) as use_fallback,
        list_transform(fallback_columns, lambda c: list_position(group_columns, c))
            as fallback_positions
    from plan
),

peers as (
    select customer_key, peer_keys
    from asof_customer_profile
    where customer_key <> -1
),

sizes as (
    select peer_keys, count(*) as full_size
    from peers
    group by peer_keys
),

assigned as (
    select
        peers.customer_key,
        case
            when plan_positions.use_fallback and sizes.full_size < plan_positions.min_size
                then plan_positions.fallback_columns
            else plan_positions.group_columns
        end as peer_columns,
        case
            when plan_positions.use_fallback and sizes.full_size < plan_positions.min_size
                then list_transform(
                    plan_positions.fallback_positions, lambda p: list_extract(peers.peer_keys, p)
                )
            else peers.peer_keys
        end as peer_keys
    from peers
    inner join sizes on peers.peer_keys = sizes.peer_keys
    cross join plan_positions
),

group_sizes as (
    select peer_columns, peer_keys, count(*) as n_peers
    from assigned
    group by peer_columns, peer_keys
),

recent as (
    select customer_key, category
    from asof_customer_category_month
    where
        month_start between
        cast(date_trunc('month', cast($asof as date)) - to_months($w_lookback - 1) as date)
        and cast(date_trunc('month', cast($asof as date)) as date)
    group by customer_key, category
    having sum(net_sales) > 0
)

select
    assigned.customer_key,
    group_sizes.n_peers < (select min_size from plan) as small_group,
    share.category,
    share.penetration >= $w_penetration and share.category <> 'Unknown' as eligible,
    recent.customer_key is not null as bought_recent
from assigned
inner join group_sizes
    on
        assigned.peer_columns = group_sizes.peer_columns
        and assigned.peer_keys = group_sizes.peer_keys
left join asof_peer_category_share as share
    on
        assigned.peer_columns = share.peer_columns
        and assigned.peer_keys = share.peer_keys
left join recent
    on
        assigned.customer_key = recent.customer_key
        and share.category = recent.category
"""

_WHITESPACE_COUNTS = """
select
    count(distinct customer_key),
    count(distinct customer_key) filter (where small_group),
    count(distinct customer_key) filter (where not small_group),
    count(*) filter (where not small_group and eligible),
    count(*) filter (where not small_group and eligible and not bought_recent),
    count(distinct customer_key) filter (where not small_group and eligible and not bought_recent)
from prof_whitespace
"""

_CROSSSELL = """
create or replace temp table prof_buys as
select customer_key, category
from asof_customer_category_month
where
    customer_key <> -1
    and category <> 'Unknown'
    and month_start between
    cast(date_trunc('month', cast($asof as date)) - to_months($c_lookback - 1) as date)
    and cast(date_trunc('month', cast($asof as date)) as date)
group by customer_key, category
having sum(net_sales) > 0;

create or replace temp table prof_ever as
select customer_key, category
from asof_customer_category_month
where customer_key <> -1 and category <> 'Unknown'
group by customer_key, category
having sum(net_sales) > 0;

create or replace temp table prof_pairs as
with buyers as (
    select category, count(*) as n_buyers
    from prof_buys
    group by category
),

total as (
    select count(distinct customer_key) as n_customers
    from prof_buys
),

support as (
    select a.category as category_a, b.category as category_b, count(*) as n_both
    from prof_buys as a
    inner join prof_buys as b on a.customer_key = b.customer_key and a.category <> b.category
    group by a.category, b.category
),

pairs as (
    select a.category as category_a, b.category as category_b, a.n_buyers as buyers_a,
        b.n_buyers as buyers_b
    from buyers as a
    inner join buyers as b on a.category <> b.category
)

select
    pairs.category_a,
    pairs.category_b,
    coalesce(support.n_both, 0) as support,
    coalesce(support.n_both, 0) / pairs.buyers_a as confidence,
    (coalesce(support.n_both, 0) / pairs.buyers_a)
    / (pairs.buyers_b / total.n_customers) as lift
from pairs
cross join total
left join support
    on pairs.category_a = support.category_a and pairs.category_b = support.category_b;

create or replace temp table prof_candidates as
select prof_buys.customer_key, prof_pairs.category_a, prof_pairs.category_b
from prof_pairs
inner join prof_buys on prof_pairs.category_a = prof_buys.category
left join prof_ever
    on
        prof_buys.customer_key = prof_ever.customer_key
        and prof_pairs.category_b = prof_ever.category
where
    prof_pairs.support >= $c_support
    and prof_pairs.confidence >= $c_confidence
    and prof_pairs.lift >= $c_lift
    and prof_ever.customer_key is null
"""

_CROSSSELL_COUNTS = """
select
    (select count(distinct customer_key) from prof_buys),
    (select count(distinct category) from prof_buys),
    count(*),
    count(*) filter (where support >= $c_support),
    count(*) filter (where confidence >= $c_confidence),
    count(*) filter (where lift >= $c_lift),
    count(*) filter (
        where support >= $c_support and confidence >= $c_confidence and lift >= $c_lift
    ),
    (select count(*) from prof_candidates),
    (select count(distinct customer_key) from prof_candidates)
from prof_pairs
"""


def _label(fraction: float) -> str:
    return f"p{round(fraction * 100)}"


def _recovery(con: duckdb.DuckDBPyConnection, params: dict[str, Any]) -> RecoveryProfile:
    _run(con, _RECOVERY, params)
    row = [int(v) for v in _run(con, _RECOVERY_COUNTS, params).fetchone()]
    evaluated = row[0]
    percentiles: dict[str, float] | None = None
    at_percentile: dict[str, int] | None = None
    if evaluated >= MIN_CUSTOMERS_FOR_PERCENTILES:
        values = con.execute(
            "select quantile_cont(cast(prior_sales as double), ?) from prof_recovery",
            [list(PERCENTILES)],
        ).fetchone()[0]
        percentiles = {
            _label(f): round(float(v), 2) for f, v in zip(PERCENTILES, values, strict=True)
        }
        at_percentile = {}
        for label, value in percentiles.items():
            at_percentile[label] = int(
                _run(
                    con,
                    "select count(*) from prof_recovery where decline_pct >= $r_decline "
                    "and prior_orders >= $r_prior_orders and prior_sales >= $cut",
                    {**params, "cut": value},
                ).fetchone()[0]
            )
    return RecoveryProfile(
        evaluated=evaluated,
        prior_sales_percentiles=percentiles,
        pass_min_decline_pct=row[1],
        pass_min_prior_orders=row[2],
        pass_min_prior_sales=row[3],
        flagged=row[4],
        flagged_not_dormant=row[5],
        flagged_at_prior_sales_percentile=at_percentile,
    )


def _dormancy(con: duckdb.DuckDBPyConnection, params: dict[str, Any]) -> DormancyProfile:
    _run(con, _DORMANCY, params)
    row = [int(v) for v in _run(con, _DORMANCY_COUNTS, params).fetchone()]
    return DormancyProfile(*row)


def _whitespace(con: duckdb.DuckDBPyConnection, params: dict[str, Any]) -> WhitespaceProfile:
    _run(con, _WHITESPACE, params)
    row = [int(v) for v in _run(con, _WHITESPACE_COUNTS, params).fetchone()]
    return WhitespaceProfile(*row)


def _crosssell(con: duckdb.DuckDBPyConnection, params: dict[str, Any]) -> CrosssellProfile:
    for statement in _CROSSSELL.split(";"):
        if statement.strip():
            _run(con, statement, params)
    row = [int(v or 0) for v in _run(con, _CROSSSELL_COUNTS, params).fetchone()]
    return CrosssellProfile(*row)


def profile_thresholds(settings: Settings) -> ThresholdProfile:
    """Count what each engine's default thresholds would flag at `settings.asof.date`."""
    source = settings.paths.warehouse
    if not source.is_file():
        raise ProfileError(f"warehouse not found: {source}; run `uv run revint build gold` first")
    with tempfile.TemporaryDirectory(prefix="revint-thresholds-") as folder:
        copy = Path(folder) / "warehouse.duckdb"
        try:
            shutil.copyfile(source, copy)
        except OSError as exc:
            raise ProfileError(
                f"cannot copy the warehouse (is it open in another program?): "
                f"{exc.strerror or type(exc).__name__}"
            ) from exc
        local = settings.model_copy(
            update={"paths": settings.paths.model_copy(update={"warehouse": copy})}
        )
        try:
            run_opportunities(local)
        except OpportunitiesError as exc:
            raise ProfileError(str(exc)) from exc
        params = _params(settings)
        con = duckdb.connect(str(copy))
        try:
            dormancy = _dormancy(con, params)
            recovery = _recovery(con, params)
            whitespace = _whitespace(con, params)
            crosssell = _crosssell(con, params)
        except duckdb.Error as exc:
            raise ProfileError(f"the profile query failed: {type(exc).__name__}") from exc
        finally:
            con.close()
    logger.info(
        "threshold profile as of %s: recovery %d, dormancy %d, whitespace %d, crosssell %d flagged",
        settings.asof.date.isoformat(),
        recovery.flagged,
        dormancy.flagged,
        whitespace.flagged_pairs,
        crosssell.candidates,
    )
    return ThresholdProfile(
        as_of_date=settings.asof.date,
        thresholds=_thresholds(settings),
        recovery=recovery,
        dormancy=dormancy,
        whitespace=whitespace,
        crosssell=crosssell,
    )


def _percentile_text(values: dict[str, float] | None) -> str:
    if values is None:
        return f"not shown (fewer than {MIN_CUSTOMERS_FOR_PERCENTILES} customers)"
    return ", ".join(f"{label} {value:,.2f}" for label, value in values.items())


def format_profile(profile: ThresholdProfile) -> str:
    """The profile as plain text: thresholds, counts and percentiles only."""
    r, d, w, c = profile.recovery, profile.dormancy, profile.whitespace, profile.crosssell
    t = profile.thresholds
    lines = [
        f"Threshold profile as of {profile.as_of_date.isoformat()}",
        "",
        f"Recovery {t['recovery']}",
        f"  evaluated (orders in the prior window): {r.evaluated:,}",
        f"  prior-window net sales per customer: {_percentile_text(r.prior_sales_percentiles)}",
        f"  pass min_decline_pct {r.pass_min_decline_pct:,}, min_prior_orders "
        f"{r.pass_min_prior_orders:,}, min_prior_sales {r.pass_min_prior_sales:,}",
        f"  flagged (all three): {r.flagged:,}; not dormant: {r.flagged_not_dormant:,}",
    ]
    if r.flagged_at_prior_sales_percentile is not None:
        at = ", ".join(f"{k} {v:,}" for k, v in r.flagged_at_prior_sales_percentile.items())
        lines.append(f"  flagged if min_prior_sales were the percentile: {at}")
    lines += [
        "",
        f"Dormancy {t['dormancy']}",
        f"  evaluated: {d.evaluated:,}; insufficient_history: {d.insufficient_history:,}",
        f"  pass interval_multiple {d.pass_interval_multiple:,}, min_days {d.pass_min_days:,}, "
        f"lookback sales {d.pass_lookback_sales:,}",
        f"  flagged (all): {d.flagged:,}",
        "",
        f"Whitespace {t['whitespace']}",
        f"  customers: {w.customers:,}; small_peer_group: {w.small_peer_group:,}; "
        f"evaluated: {w.evaluated:,}",
        f"  eligible customer-category pairs: {w.eligible_pairs:,}; flagged pairs: "
        f"{w.flagged_pairs:,}; customers with a flag: {w.flagged_customers:,}",
        "",
        f"Cross-sell {t['crosssell']}",
        f"  customers buying in the lookback: {c.buying_customers:,}; categories: "
        f"{c.categories:,}; ordered pairs: {c.evaluated_pairs:,}",
        f"  pass min_support {c.pass_min_support:,}, min_confidence {c.pass_min_confidence:,}, "
        f"min_lift {c.pass_min_lift:,}; pairs passing all: {c.flagged_pairs:,}",
        f"  candidates (customer and pair): {c.candidates:,}; customers: {c.candidate_customers:,}",
        "",
        f"opportunities {t['opportunities']}",
        "",
        "Readings (the engines are not built yet):",
        *(f"- {reading}" for reading in READINGS),
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m revint.threshold_profile",
        description="Profile the opportunity engine thresholds (counts and percentiles only).",
    )
    parser.add_argument("--json", action="store_true", help="print the counts as JSON")
    parser.add_argument("--as-of", type=Date.fromisoformat, help="as-of date for this run")
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"threshold profile: {exc}", file=sys.stderr)
        return 1
    if args.as_of is not None:
        from revint.opportunities import with_asof

        settings = with_asof(settings, args.as_of)
    try:
        profile = profile_thresholds(settings)
    except ProfileError as exc:
        print(f"threshold profile failed: {exc}", file=sys.stderr)
        return EXIT_PROFILE_FAILED
    print(json.dumps(profile.as_dict(), indent=2) if args.json else format_profile(profile))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
