"""Story #111: the cross-sell engine (spec 03 section 3.4, FR-O4).

Synthetic data only; customer codes and categories carry a SECRET- marker. Silver and gold are
built once per module; each test copies the warehouse and runs the opportunity stage on its own
copy. As of 2020-02-29, lookback 12 months (March 2019 to February 2020). Tests set min_support
3, min_confidence 0.3 and min_lift 1.0 unless they say otherwise.

10 customers buy something. A is bought by K1..K6; B by K1..K4 and K7; C by K7..K10.
- A -> B: support 4, confidence 4/6 = 0.6667, lift 0.6667 / (5/10) = 1.3333
- B -> A: support 4, confidence 4/5 = 0.8, lift 0.8 / (6/10) = 1.3333
- B -> C: support 1 (K7)
- K5 bought A in the lookback and never B: a candidate for B. K6 bought A only in 2018, outside
  the lookback, so it is not. K7 bought B and never A: a candidate for A.
- Gap for K5's B: median B net sales among K1..K4 (10, 20, 30, 40) = 25.
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
NAMES = {v: k for k, v in CAT.items() if v}


class Rows:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.n = 8

    def sale(self, customer: str, category: str, day: str = "2020-01-10", net: str = "10") -> None:
        self.rows.append(
            bronze_row(
                self.n,
                OrderReference=f"O{self.n}",
                CustomerCode=f"{S}{customer}",
                Customer=f"{S}name",
                SCJ_CODE_1=f"P{category}",
                Internal_Category=CAT[category],
                Branch_Name="Magway",
                Channel_Category="GT",
                Date=day,
                Net_Amount_2=net,
                **{"Quantity(PCS)": "1"},
            )
        )
        self.n += 1


DATA = Rows()
for i, net in zip(range(1, 5), ("10", "20", "30", "40"), strict=True):
    DATA.sale(f"K{i}", "A")
    DATA.sale(f"K{i}", "B", net=net)
DATA.sale("K5", "A")
DATA.sale("K6", "A", day="2018-06-10")
DATA.sale("K7", "B")
for i in range(7, 11):
    DATA.sale(f"K{i}", "C")
for i in range(1, 11):
    DATA.sale(f"K{i}", "U")  # every customer also buys the Unknown category
# K5 buys B on 2020-03-10, after the as-of date
DATA.sale("K5", "B", day="2020-03-10", net="99")


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("crosssell")
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    build(settings, DATA.rows)
    run_gold(settings)
    return settings


def run(built: Settings, tmp_path: Path, as_of: date = ASOF, **keys: object) -> Settings:
    tmp_path.mkdir(parents=True, exist_ok=True)
    shutil.copy(built.paths.warehouse, tmp_path / "warehouse.duckdb")
    source = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "warehouse.duckdb")})
    crosssell = {"min_support": 3, "min_confidence": 0.3, "min_lift": 1.0, **keys}
    settings = with_asof(variant(tmp_path, source, crosssell=crosssell), as_of)
    run_opportunities(settings)
    return settings


def key(settings: Settings, code: str) -> int:
    return query(
        settings, "select customer_key from dim_customer where customer_code = ?", f"{S}{code}"
    )[0][0]


def pair(settings: Settings, a: str, b: str) -> tuple:
    return query(
        settings,
        "select support, confidence, lift, outcome from opp_crosssell_pairs "
        "where category_a = ? and category_b = ?",
        CAT[a],
        CAT[b],
    )[0]


def flagged(settings: Settings) -> set[tuple[str, str, str]]:
    return {
        (code.removeprefix(S), NAMES[a], NAMES[b])
        for code, a, b in query(
            settings,
            "select customer_code, category_a, category from opp_crosssell "
            "join dim_customer using (customer_key)",
        )
    }


def outcome(settings: Settings, code: str, category: str) -> str | None:
    rows = query(
        settings,
        "select outcome from opp_evaluations where type = 'crosssell' "
        "and customer_key = ? and category = ?",
        key(settings, code),
        CAT[category],
    )
    return rows[0][0] if rows else None


@pytest.fixture
def result(built: Settings, tmp_path: Path) -> Settings:
    return run(built, tmp_path)


# AC1: support, confidence and lift ------


def test_ac1_the_pair_measures(result: Settings) -> None:
    assert pair(result, "A", "B") == (4, Decimal("0.6667"), Decimal("1.3333"), "passed")
    assert pair(result, "B", "A") == (4, Decimal("0.8000"), Decimal("1.3333"), "passed")


def test_ac1_min_support_is_applied(built: Settings, tmp_path: Path) -> None:
    got = run(built, tmp_path, min_support=5)
    assert pair(got, "A", "B")[3] == "below_min_support"


def test_ac1_min_confidence_is_applied(built: Settings, tmp_path: Path) -> None:
    got = run(built, tmp_path, min_confidence=0.7)
    assert pair(got, "A", "B")[3] == "below_min_confidence"
    assert pair(got, "B", "A")[3] == "passed"


def test_ac1_min_lift_is_applied(built: Settings, tmp_path: Path) -> None:
    got = run(built, tmp_path, min_lift=1.5)
    assert pair(got, "A", "B")[3] == "below_min_lift"


# AC2: bought A in the lookback, never bought B ------


def test_ac2_the_candidates(result: Settings) -> None:
    # K5 bought A, never B; K7 bought B, never A
    assert flagged(result) == {("K5", "A", "B"), ("K7", "B", "A")}


def test_ac2_a_purchase_of_a_outside_the_lookback_is_not_a_candidate(result: Settings) -> None:
    assert outcome(result, "K6", "B") is None  # K6 bought A in 2018 only


def test_ac2_the_lookback_is_applied(built: Settings, tmp_path: Path) -> None:
    got = run(built, tmp_path, lookback_months=24)
    assert ("K6", "A", "B") in flagged(got)


def test_ac2_a_buyer_of_b_is_never_a_candidate_for_b(result: Settings) -> None:
    for code in ("K1", "K2", "K3", "K4"):
        assert outcome(result, code, "B") is None


# AC3: pairs below a threshold are counted by the threshold that failed ------


def test_ac3_a_failing_pair_is_counted_by_its_threshold(built: Settings, tmp_path: Path) -> None:
    got = run(built, tmp_path, min_lift=1.5)
    rows = query(
        got,
        "select n_evaluated, n_triggered, suppressed_by_reason from opp_run_summary "
        "where type = 'crosssell'",
    )
    # K5 for B and K7 for A now fail on lift; the support-1 pairs still fail on support
    assert rows == [(9, 0, {"below_min_lift": 2, "below_min_support": 7})]


def test_ac3_pairs_are_kept_with_their_outcome(result: Settings) -> None:
    counts = dict(query(result, "select outcome, count(*) from opp_crosssell_pairs group by 1"))
    # A<->B pass; B->C and C->B have support 1
    assert counts == {"passed": 2, "below_min_support": 2}


def test_ac3_the_run_summary(result: Settings) -> None:
    rows = query(
        result,
        "select n_evaluated, n_triggered, n_suppressed, suppressed_by_reason "
        "from opp_run_summary where type = 'crosssell'",
    )
    # triggered: K5 for B, K7 for A. Support 1: K1..K4 for C (B -> C), K8..K10 for B (C -> B)
    assert rows == [(9, 2, 7, {"below_min_support": 7})]


# AC4: the gap and the stored measures ------


def test_ac4_the_gap_is_the_median_b_sales_of_customers_who_bought_both(result: Settings) -> None:
    rows = query(
        result,
        "select gap, support, confidence, lift, reason_codes from opp_crosssell "
        "where customer_key = ?",
        key(result, "K5"),
    )
    assert rows == [
        (
            Decimal("25.0000"),
            4,
            Decimal("0.6667"),
            Decimal("1.3333"),
            [
                "support_at_least_min",
                "confidence_at_least_min",
                "lift_at_least_min",
                "bought_a_in_lookback",
                "never_bought_b",
            ],
        )
    ]


# AC5: Unknown is neither A nor B ------


def test_ac5_unknown_is_never_in_a_pair(result: Settings) -> None:
    got = query(
        result,
        "select count(*) from opp_crosssell_pairs "
        "where category_a = 'Unknown' or category_b = 'Unknown'",
    )
    assert got == [(0,)]
    for table in ("opp_crosssell", "opp_evaluations"):
        assert query(result, f"select count(*) from {table} where category = 'Unknown'") == [(0,)]


def test_ac5_the_unknown_customer_is_left_out(result: Settings) -> None:
    for table in ("opp_crosssell", "opp_evaluations"):
        assert query(result, f"select count(*) from {table} where customer_key = -1") == [(0,)]


# AC6: near the thresholds ------


def test_ac6_just_below_the_confidence_does_not_pass(built: Settings, tmp_path: Path) -> None:
    got = run(built, tmp_path, min_confidence=0.6668)
    assert pair(got, "A", "B")[3] == "below_min_confidence"


def test_ac6_exactly_at_the_support_passes(built: Settings, tmp_path: Path) -> None:
    got = run(built, tmp_path, min_support=4)
    assert pair(got, "A", "B")[3] == "passed"


def test_ac6_just_below_the_lift_does_not_pass(built: Settings, tmp_path: Path) -> None:
    got = run(built, tmp_path, min_lift=1.3334)
    assert pair(got, "A", "B")[3] == "below_min_lift"


# AC7: only data on or before the as-of date ------


def test_ac7_a_later_sale_is_not_seen(result: Settings) -> None:
    assert outcome(result, "K5", "B") == "triggered"  # K5's 2020-03-10 B sale is not counted


def test_ac7_after_that_sale_it_is_not_a_candidate(built: Settings, tmp_path: Path) -> None:
    got = run(built, tmp_path, as_of=date(2020, 3, 31))
    assert outcome(got, "K5", "B") is None


# Identity, rerun and AC8 ------


def test_rows_carry_the_identity_columns(result: Settings) -> None:
    k = key(result, "K5")
    rows = query(
        result,
        "select opp_id, type, category, as_of_date, algo_version from opp_crosssell "
        "where customer_key = ?",
        k,
    )
    assert rows == [
        (opp_id("crosssell", k, CAT["B"], ASOF), "crosssell", CAT["B"], ASOF, "crosssell-1")
    ]


def test_a_rerun_gives_identical_rows(built: Settings, tmp_path: Path) -> None:
    first = run(built, tmp_path)
    sql = "select * from opp_crosssell order by opp_id"
    rows = query(first, sql)
    run_opportunities(first)
    assert query(first, sql) == rows


def test_ac8_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 8):
        assert f"def test_ac{ac}_" in text


@pytest.mark.realdata
def test_ac1_ac5_real_file_crosssell(tmp_path: Path) -> None:
    """Counts only, on a copy of the built warehouse."""
    real = load_settings()
    if not real.paths.warehouse.is_file():
        pytest.skip("warehouse not built: run `uv run revint build all` first")
    shutil.copy(real.paths.warehouse, tmp_path / "w.duckdb")
    copy = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    run_opportunities(copy)
    ((n,),) = query(copy, "select n_triggered from opp_run_summary where type = 'crosssell'")
    assert 0 < n == query(copy, "select count(*) from opp_crosssell")[0][0]
    unknown = (
        "select count(*) from opp_crosssell where category = 'Unknown' or category_a = 'Unknown'"
    )
    assert query(copy, unknown) == [(0,)]
