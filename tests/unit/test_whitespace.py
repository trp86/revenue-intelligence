"""Story #110: the whitespace engine (spec 03 section 3.3, FR-O3).

Synthetic data only; customer codes and categories carry a SECRET- marker. Silver and gold are
built once per module; each test copies the warehouse and runs the opportunity stage on its own
copy. As of 2020-02-29, lookback 12 months (March 2019 to February 2020), penetration 0.5.
Tests set peer_groups.min_size 3 unless they say otherwise.

Group GT/Magway has 5 customers, M1..M5, who all buy A. B is bought by M1, M2 and M3 (net 10, 20
and 30). M4 bought B once in 2018 (outside the lookback, net 40). M5 never bought B.
- Category C is bought by M1 and M2 only. Category 'Unknown' (no category) is bought by all.
Group MT/PYAY has 2 customers, P1 and P2: below min_size 3, it falls back to MT (channel only),
where it is still 2: marked and capped. P1 buys A and B, P2 buys A only.
"""

from __future__ import annotations

import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from gold_helpers import variant
from silver_helpers import bronze_row, build, query

from revint.config import Settings, load_settings
from revint.gold import run_gold
from revint.opportunities import opp_id, run_opportunities, with_asof

S = "SECRET-"
ASOF = date(2020, 2, 29)
CAT = {"A": f"{S}A", "B": f"{S}B", "C": f"{S}C", "U": None}


class Rows:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.n = 8

    def sale(
        self,
        customer: str,
        category: str,
        day: str = "2020-01-10",
        net: str = "10",
        channel: str = "GT",
        branch: str = "Magway",
    ) -> None:
        self.rows.append(
            bronze_row(
                self.n,
                OrderReference=f"O{self.n}",
                CustomerCode=f"{S}{customer}",
                Customer=f"{S}name",
                SCJ_CODE_1=f"P{category}",
                Internal_Category=CAT[category],
                Branch_Name=branch,
                Channel_Category=channel,
                Date=day,
                Net_Amount_2=net,
                **{"Quantity(PCS)": "1"},
            )
        )
        self.n += 1


DATA = Rows()
for m in ("M1", "M2", "M3", "M4", "M5"):
    DATA.sale(m, "A")
    DATA.sale(m, "U")
DATA.sale("M1", "B", net="10")
DATA.sale("M2", "B", net="20")
DATA.sale("M3", "B", net="30")
DATA.sale("M4", "B", day="2018-06-10", net="40")
DATA.sale("M1", "C")
DATA.sale("M2", "C")
DATA.sale("P1", "A", channel="MT", branch="PYAY")
DATA.sale("P1", "B", channel="MT", branch="PYAY", net="50")
DATA.sale("P2", "A", channel="MT", branch="PYAY")
# M5 buys B on 2020-03-10, after the as-of date
DATA.sale("M5", "B", day="2020-03-10", net="99")


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("whitespace")
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    build(settings, DATA.rows)
    run_gold(settings)
    return settings


def run(built: Settings, tmp_path: Path, as_of: date = ASOF, **sections: dict) -> Settings:
    tmp_path.mkdir(parents=True, exist_ok=True)
    shutil.copy(built.paths.warehouse, tmp_path / "warehouse.duckdb")
    source = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "warehouse.duckdb")})
    peer = {"min_size": 3, **sections.pop("peer_groups", {})}
    settings = with_asof(variant(tmp_path, source, peer_groups=peer, **sections), as_of)
    run_opportunities(settings)
    return settings


def key(settings: Settings, code: str) -> int:
    return query(
        settings, "select customer_key from dim_customer where customer_code = ?", f"{S}{code}"
    )[0][0]


def outcome(settings: Settings, code: str, category: str) -> str | None:
    rows = query(
        settings,
        "select outcome from opp_evaluations where type = 'whitespace' "
        "and customer_key = ? and category = ?",
        key(settings, code),
        CAT[category],
    )
    return rows[0][0] if rows else None


def flagged(settings: Settings) -> set[tuple[str, str]]:
    names = {v: k for k, v in CAT.items() if v}
    return {
        (code.removeprefix(S), names.get(category, category))
        for code, category in query(
            settings,
            "select customer_code, category from opp_whitespace "
            "join dim_customer using (customer_key)",
        )
    }


def row(settings: Settings, code: str, category: str) -> tuple:
    return query(
        settings,
        "select gap, peer_penetration, n_peers, n_buying_peers, f_fallback, f_below_min_size, "
        "reason_codes from opp_whitespace where customer_key = ? and category = ?",
        key(settings, code),
        CAT[category],
    )[0]


@pytest.fixture
def result(built: Settings, tmp_path: Path) -> Settings:
    return run(built, tmp_path)


# AC1: penetration at least the minimum and none bought in the lookback ------


def test_ac1_the_whitespace_pairs(result: Settings) -> None:
    # B: M4 (bought only in 2018) and M5; P2 lacks B in a fallback group
    # C: penetration for M3, M4, M5 is 2 of 4 = 0.5 (at least the minimum)
    assert flagged(result) == {
        ("M4", "B"),
        ("M5", "B"),
        ("M3", "C"),
        ("M4", "C"),
        ("M5", "C"),
        ("P2", "B"),
    }


def test_ac1_a_category_bought_in_the_lookback_is_not_whitespace(result: Settings) -> None:
    assert outcome(result, "M1", "B") == "bought_in_lookback"
    assert outcome(result, "M1", "A") == "bought_in_lookback"


def test_ac1_min_peer_penetration_is_applied(built: Settings, tmp_path: Path) -> None:
    got = run(built, tmp_path, whitespace={"min_peer_penetration": 0.6})
    assert outcome(got, "M5", "C") == "below_min_penetration"
    assert ("M5", "B") in flagged(got)  # 4 of 4


def test_ac1_lookback_months_is_applied(built: Settings, tmp_path: Path) -> None:
    # a 24-month lookback reaches June 2018, so M4 bought B in it
    got = run(built, tmp_path, whitespace={"lookback_months": 24})
    assert outcome(got, "M4", "B") == "bought_in_lookback"


# AC2: the gap is the median per buying peer, no uplift ------


def test_ac2_the_gap_is_the_median_net_sales_of_the_buying_peers(result: Settings) -> None:
    # for M5 the buying peers of B are M1..M4 (10, 20, 30, 40): median 25
    assert row(result, "M5", "B")[0] == Decimal("25.0000")


def test_ac2_the_customer_is_left_out_of_its_own_gap(result: Settings) -> None:
    # for M4, its own 2018 sale (40) is left out: M1..M3 (10, 20, 30), median 20
    assert row(result, "M4", "B")[0] == Decimal("20.0000")


# AC3: fallback groups are marked; a group below the minimum is noted ------


def test_ac3_a_fallback_row_is_marked_and_capped(result: Settings) -> None:
    gap, penetration, peers, buyers, fallback, below, reasons = row(result, "P2", "B")
    assert (fallback, below) == (True, True)
    assert "peer_fallback" in reasons and "peer_group_below_min_size" in reasons
    assert (peers, buyers, penetration) == (1, 1, Decimal("1.0000"))


def test_ac3_a_full_group_row_has_neither_mark(result: Settings) -> None:
    *_, fallback, below, reasons = row(result, "M5", "B")
    assert (fallback, below) == (False, False)
    assert reasons == ["peer_penetration_at_least_min", "not_bought_in_lookback"]


def test_ac3_a_fallback_group_at_the_minimum_is_not_below_it(
    built: Settings, tmp_path: Path
) -> None:
    got = run(built, tmp_path, peer_groups={"min_size": 2})
    # MT/PYAY has 2 members: no fallback is needed at min_size 2
    *_, fallback, below, _ = row(got, "P2", "B")
    assert (fallback, below) == (False, False)


# AC4: Unknown is never whitespace ------


def test_ac4_unknown_is_never_evaluated_or_flagged(result: Settings) -> None:
    for table in ("opp_whitespace", "opp_evaluations"):
        got = query(
            result,
            f"select count(*) from {table} where category = 'Unknown'",  # noqa: S608
        )
        assert got == [(0,)], table


# AC5: the customer is not one of its own peers ------


def test_ac5_the_customer_is_not_counted_among_its_peers(result: Settings) -> None:
    # M5 and its 4 peers: all 4 have bought B, so 4 of 4
    _, penetration, peers, buyers, *_ = row(result, "M5", "B")
    assert (peers, buyers, penetration) == (4, 4, Decimal("1.0000"))


def test_ac5_a_buyer_does_not_raise_its_own_penetration(result: Settings) -> None:
    # M3 judging C: M1 and M2 buy C, 2 of its 4 peers
    _, penetration, peers, buyers, *_ = row(result, "M3", "C")
    assert (peers, buyers, penetration) == (4, 2, Decimal("0.5000"))


def test_ac5_a_customer_alone_has_no_peers(built: Settings, tmp_path: Path) -> None:
    # min_size 1: MT/PYAY needs no fallback, and a group of one has no peers
    got = run(
        built, tmp_path, peer_groups={"min_size": 1, "columns": ["Channel_Category", "Branch_Name"]}
    )
    assert outcome(got, "P2", "B") == "triggered"  # P1 is its peer (1 of 1)


# AC6: near the threshold ------


def test_ac6_just_below_the_penetration_does_not_trigger(built: Settings, tmp_path: Path) -> None:
    got = run(built, tmp_path, whitespace={"min_peer_penetration": 0.5001})
    assert outcome(got, "M5", "C") == "below_min_penetration"  # 0.5 < 0.5001


def test_ac6_exactly_at_the_penetration_triggers(result: Settings) -> None:
    assert row(result, "M5", "C")[1] == Decimal("0.5000")


# AC7: only data on or before the as-of date ------


def test_ac7_a_later_sale_is_not_seen(result: Settings) -> None:
    assert outcome(result, "M5", "B") == "triggered"  # M5's 2020-03-10 B sale is not counted


def test_ac7_after_that_sale_it_is_bought(built: Settings, tmp_path: Path) -> None:
    got = run(built, tmp_path, as_of=date(2020, 3, 31))
    assert outcome(got, "M5", "B") == "bought_in_lookback"


# Summary, identity, rerun and AC8 ------


def test_the_run_summary(result: Settings) -> None:
    rows = query(
        result,
        "select n_evaluated, n_triggered, n_suppressed, suppressed_by_reason "
        "from opp_run_summary where type = 'whitespace'",
    )
    # GT/Magway: 5 customers x 3 categories (A, B, C) = 15; MT: 2 x 2 (A, B) = 4
    # M1 and M2 judging C see 1 of 4, and P1 judging B sees 0 of 1: penetration fails first
    assert rows == [(19, 6, 13, {"below_min_penetration": 3, "bought_in_lookback": 10})]


def test_the_unknown_customer_is_not_evaluated(result: Settings) -> None:
    assert query(result, "select count(*) from opp_evaluations where customer_key = -1") == [(0,)]


def test_rows_carry_the_identity_columns(result: Settings) -> None:
    k = key(result, "M5")
    rows = query(
        result,
        "select opp_id, type, as_of_date, algo_version from opp_whitespace "
        "where customer_key = ? and category = ?",
        k,
        CAT["B"],
    )
    assert rows == [(opp_id("whitespace", k, CAT["B"], ASOF), "whitespace", ASOF, "whitespace-1")]


def test_a_rerun_gives_identical_rows(built: Settings, tmp_path: Path) -> None:
    first = run(built, tmp_path)
    sql = "select * from opp_whitespace order by opp_id"
    rows = query(first, sql)
    run_opportunities(first)
    assert query(first, sql) == rows


def test_ac8_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 8):
        assert f"def test_ac{ac}_" in text


@pytest.mark.realdata
def test_ac1_ac4_real_file_whitespace(tmp_path: Path) -> None:
    """Counts only, on a copy of the built warehouse."""
    real = load_settings()
    if not real.paths.warehouse.is_file():
        pytest.skip("warehouse not built: run `uv run revint build all` first")
    shutil.copy(real.paths.warehouse, tmp_path / "w.duckdb")
    copy = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    run_opportunities(copy)
    ((n,),) = query(copy, "select n_triggered from opp_run_summary where type = 'whitespace'")
    assert 0 < n == query(copy, "select count(*) from opp_whitespace")[0][0]
    unknown = "select count(*) from opp_whitespace where category = 'Unknown'"
    assert query(copy, unknown) == [(0,)]
    assert query(copy, "select count(*) from opp_whitespace where gap <= 0") == [(0,)]
