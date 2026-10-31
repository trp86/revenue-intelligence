"""Story #83: mart_peer_category_share (spec 02 section 6).

Synthetic data only; customer codes carry a SECRET- marker to prove none reaches logs. Silver is
built once per module, each test copies the warehouse and runs gold on its own copy. The
real-file test is marked `realdata` and asserts counts and sums only.

Peer groups in the fixture, with peer_groups.min_size = 2 (default columns channel + branch,
fallback channel):
    [GT, Magway]            C1, C2, C3   size 3, a full group
    [GT, Pyay]              C4           size 1, too small
    [GT, Dawei]             C5           size 1, too small
    [Modern Trade, Magway]  C6           size 1, too small
C4 and C5 are pooled in the fallback group [GT] (size 2); C6 alone in [Modern Trade] (size 1,
still below the minimum).
"""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

import pytest
from gold_helpers import gold, variant
from silver_helpers import bronze_row, build, query

from revint.config import Settings, load_settings
from revint.gold import GOLD_DIR, GoldError, run_gold

S = "SECRET-"
MIN2 = {"min_size": 2}
A, B = f"{S}A", f"{S}B"


def sale(
    row: int,
    customer: str | None,
    product: str,
    branch: str | None,
    channel: str | None,
    net: str,
    day: str = "2019-01-10",
    order: int | None = None,
) -> dict[str, str | None]:
    return bronze_row(
        row,
        OrderReference=f"O{order or row}",
        CustomerCode=customer,
        Customer=f"{S}name" if customer else None,
        SCJ_CODE_1=product,
        Internal_Category={"PA": A, "PB": B}.get(product),
        Branch_Name=branch,
        Channel_Category=channel,
        Date=day,
        Net_Amount_2=net,
        **{"Quantity(PCS)": "1"},
    )


ROWS = [
    sale(8, f"{S}C1", "PA", "Magway", "GT", "10"),
    sale(9, f"{S}C1", "PA", "Magway", "GT", "5", day="2019-02-10"),
    sale(10, f"{S}C1", "PB", "Magway", "GT", "3"),
    sale(11, f"{S}C2", "PA", "Magway", "GT", "20"),
    sale(12, f"{S}C2", "PA", "Magway", "GT", "20", order=11),  # an exact copy: silver excludes it
    sale(13, f"{S}C3", "PB", "Magway", "GT", "4"),
    sale(14, f"{S}C3", "PA", "Magway", "GT", "-1"),  # a return: C3 does not buy A
    sale(15, f"{S}C4", "PA", "PYAY", "GT", "8"),
    sale(16, f"{S}C4", "PX", "PYAY", "GT", "2"),  # a product with no category
    sale(17, f"{S}C5", "PB", "Dawei", "GT", "6"),
    sale(18, f"{S}C6", "PA", "Magway", "MT", "7"),
    sale(19, None, "PA", "Magway", "GT", "9"),  # the unknown customer: never a peer
    bronze_row(20, Change_to_Ctn="1"),
]
GT_MAGWAY = ["GT", "Magway"]
COLUMNS = (
    "peer_columns, peer_keys, f_fallback, f_below_min_size, category, n_peers, n_buying, "
    "penetration, median_buyer_net_sales, total_net_sales, n_lines, f_unknown_category"
)


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("martpeer")
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    build(settings, ROWS)
    return settings


def mart(settings: Settings) -> dict[tuple[tuple[str, ...], str], dict]:
    names = [c.strip() for c in COLUMNS.split(",")]
    rows = query(settings, f"select {COLUMNS} from mart_peer_category_share")
    out = {}
    for row in rows:
        record = dict(zip(names, row, strict=True))
        out[(tuple(record["peer_keys"]), record["category"])] = record
    return out


# AC1: grain peer group x category with peers, buyers, penetration and median ------


def test_ac1_the_table_has_the_documented_columns(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, peer_groups=MIN2)
    columns = [
        c
        for (c,) in query(
            settings,
            "select column_name from information_schema.columns "
            "where table_name = 'mart_peer_category_share' order by ordinal_position",
        )
    ]
    assert columns == [c.strip() for c in COLUMNS.split(",")]


def test_ac1_the_grain_is_peer_group_by_category(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, peer_groups=MIN2)
    assert query(
        settings,
        "select count(*) from (select peer_columns, peer_keys, category "
        "from mart_peer_category_share group by 1, 2, 3 having count(*) > 1)",
    ) == [(0,)]


def test_ac1_peers_buying_penetration_and_median_of_a_full_group(
    built: Settings, tmp_path: Path
) -> None:
    got = mart(gold(built, tmp_path, peer_groups=MIN2))[(("GT", "Magway"), A)]
    assert got["peer_columns"] == ["Channel_Category", "Branch_Name"]
    assert got["n_peers"] == 3
    assert got["n_buying"] == 2  # C1 (15) and C2 (20); C3's net sales are -1
    assert got["penetration"] == Decimal("0.6667")
    assert got["median_buyer_net_sales"] == Decimal("17.5000")  # median of 15 and 20
    assert got["total_net_sales"] == Decimal("34.0000")  # 15 + 20 - 1
    assert got["n_lines"] == 4
    assert (got["f_fallback"], got["f_below_min_size"], got["f_unknown_category"]) == (
        False,
        False,
        False,
    )


def test_ac1_a_second_category_in_the_same_group(built: Settings, tmp_path: Path) -> None:
    got = mart(gold(built, tmp_path, peer_groups=MIN2))[(("GT", "Magway"), B)]
    assert (got["n_peers"], got["n_buying"], got["median_buyer_net_sales"]) == (
        3,
        2,
        Decimal("3.5000"),
    )


def test_ac1_a_buyer_needs_positive_net_sales_in_the_category(
    built: Settings, tmp_path: Path
) -> None:
    got = mart(gold(built, tmp_path, peer_groups=MIN2))[(("GT", "Magway"), A)]
    assert got["n_buying"] == 2 and got["n_peers"] == 3  # C3 has a line but net sales < 0


def test_ac1_a_category_nobody_bought_has_no_row(built: Settings, tmp_path: Path) -> None:
    got = mart(gold(built, tmp_path, peer_groups=MIN2))
    assert (("GT", "Magway"), "Unknown") not in got


def test_ac1_the_group_size_is_the_same_on_every_row_of_the_group(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path, peer_groups=MIN2)
    assert query(
        settings,
        "select count(*) from (select peer_columns, peer_keys from mart_peer_category_share "
        "group by 1, 2 having count(distinct n_peers) > 1)",
    ) == [(0,)]


def test_ac1_the_unknown_customer_is_never_a_peer(built: Settings, tmp_path: Path) -> None:
    got = mart(gold(built, tmp_path, peer_groups=MIN2))
    assert got[(("GT", "Magway"), A)]["n_peers"] == 3  # the blank-code line is not counted
    assert sum(r["n_peers"] for k, r in got.items() if k[1] == B) >= 3


def test_ac1_penetration_is_between_zero_and_one_and_is_buyers_over_peers(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path, peer_groups=MIN2)
    assert query(
        settings,
        "select count(*) from mart_peer_category_share where penetration < 0 or penetration > 1 "
        "or abs(penetration - n_buying * 1.0 / n_peers) > 0.0001",
    ) == [(0,)]


def test_ac1_median_is_null_when_nobody_buys(tmp_path: Path) -> None:
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
            "REVINT_PATHS_BRONZE": str(tmp_path / "b"),
        }
    )
    build(settings, [sale(8, "X", "PA", "Magway", "GT", "-5")])
    run_gold(settings)
    got = mart(settings)[(("GT",), A)]  # a group of one is below the default min_size
    assert (got["n_buying"], got["penetration"], got["median_buyer_net_sales"]) == (
        0,
        Decimal("0.0000"),
        None,
    )


def test_ac1_the_label_maps_apply_to_the_group_keys(built: Settings, tmp_path: Path) -> None:
    got = mart(gold(built, tmp_path, peer_groups=MIN2))
    assert (("Modern Trade",), A) in got  # MT is mapped to Modern Trade


def test_ac1_the_sql_reads_net_sales_only_from_the_category_mart() -> None:
    raw = (GOLD_DIR / "10_mart_peer_category_share.sql").read_text(encoding="utf-8")
    text = " ".join(line.split("--")[0] for line in raw.splitlines())
    assert "mart_customer_category_month" in text and "mart_customer_profile" in text
    assert "silver_sales" not in text
    assert "amount_" not in text and "Net_Amount" not in text and "Internal_Category" not in text


def test_ac1_the_header_comment_states_the_grain_the_buyer_rule_and_the_fallback() -> None:
    raw = (GOLD_DIR / "10_mart_peer_category_share.sql").read_text(encoding="utf-8")
    header = raw.split("create or replace table")[0].lower()
    for word in ("grain", "peer", "category", "penetration", "median", "fallback", "min_size"):
        assert word in header


# AC2: groups smaller than min_size fall back, marked on the row ------


def test_ac2_small_groups_are_pooled_into_the_fallback_group(
    built: Settings, tmp_path: Path
) -> None:
    got = mart(gold(built, tmp_path, peer_groups=MIN2))
    pooled = got[(("GT",), A)]
    assert pooled["peer_columns"] == ["Channel_Category"]
    assert (pooled["n_peers"], pooled["n_buying"], pooled["penetration"]) == (
        2,
        1,
        Decimal("0.5000"),
    )
    assert (pooled["f_fallback"], pooled["f_below_min_size"]) == (True, False)
    assert pooled["median_buyer_net_sales"] == Decimal("8.0000")


def test_ac2_the_small_groups_have_no_row_of_their_own(built: Settings, tmp_path: Path) -> None:
    keys = {k[0] for k in mart(gold(built, tmp_path, peer_groups=MIN2))}
    assert ("GT", "Pyay") not in keys
    assert ("GT", "Dawei") not in keys
    assert ("Modern Trade", "Magway") not in keys


def test_ac2_only_fallback_rows_are_marked(built: Settings, tmp_path: Path) -> None:
    got = mart(gold(built, tmp_path, peer_groups=MIN2))
    assert {k[0] for k, r in got.items() if r["f_fallback"]} == {("GT",), ("Modern Trade",)}
    assert {k[0] for k, r in got.items() if not r["f_fallback"]} == {("GT", "Magway")}


def test_ac2_a_fallback_group_that_is_still_too_small_is_flagged(
    built: Settings, tmp_path: Path
) -> None:
    got = mart(gold(built, tmp_path, peer_groups=MIN2))[(("Modern Trade",), A)]
    assert (got["n_peers"], got["f_fallback"], got["f_below_min_size"]) == (1, True, True)
    assert got["penetration"] == Decimal("1.0000")


def test_ac2_a_group_exactly_at_min_size_does_not_fall_back(
    built: Settings, tmp_path: Path
) -> None:
    got = mart(gold(built, tmp_path, peer_groups={"min_size": 3}))
    assert (("GT", "Magway"), A) in got  # size 3 is not smaller than 3
    assert got[(("GT", "Magway"), A)]["f_fallback"] is False


def test_ac2_with_min_size_one_no_group_falls_back(built: Settings, tmp_path: Path) -> None:
    got = mart(gold(built, tmp_path, peer_groups={"min_size": 1}))
    assert not any(r["f_fallback"] or r["f_below_min_size"] for r in got.values())
    assert (("GT", "Pyay"), A) in got


def test_ac2_with_a_large_min_size_everything_falls_back_to_the_channel(
    built: Settings, tmp_path: Path
) -> None:
    got = mart(gold(built, tmp_path, peer_groups={"min_size": 10}))
    assert {k[0] for k in got} == {("GT",), ("Modern Trade",)}
    assert all(r["f_fallback"] and r["f_below_min_size"] for r in got.values())
    assert got[(("GT",), A)]["n_peers"] == 5


def test_ac2_with_no_fallback_columns_small_groups_keep_their_own_row_flagged(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path, peer_groups={"min_size": 2, "fallback_columns": []})
    got = mart(settings)
    assert (("GT", "Pyay"), A) in got
    assert got[(("GT", "Pyay"), A)]["f_below_min_size"] is True
    assert not any(r["f_fallback"] for r in got.values())


def test_ac2_a_fallback_equal_to_the_group_columns_is_no_fallback(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(
        built,
        tmp_path,
        peer_groups={
            "min_size": 2,
            "columns": ["Channel_Category", "Branch_Name"],
            "fallback_columns": ["Channel_Category", "Branch_Name"],
        },
    )
    got = mart(settings)
    assert not any(r["f_fallback"] for r in got.values())
    assert got[(("GT", "Pyay"), A)]["f_below_min_size"] is True


# AC3: category totals reconcile to mart_customer_category_month ------


@pytest.mark.parametrize("min_size", [1, 2, 3, 10])
@pytest.mark.parametrize("exclude", [True, False])
def test_ac3_each_category_total_equals_the_category_mart_over_real_customers(
    built: Settings, tmp_path: Path, min_size: int, exclude: bool
) -> None:
    settings = gold(
        built,
        tmp_path,
        peer_groups={"min_size": min_size},
        duplicates={"exclude_from_net_sales": exclude},
    )
    differing = query(
        settings,
        "with peer as (select category, sum(total_net_sales) as ns, sum(n_lines) as nl "
        "from mart_peer_category_share group by 1), "
        "cat as (select category, sum(net_sales) as ns, sum(n_lines) as nl "
        "from mart_customer_category_month where customer_key <> -1 group by 1) "
        "select count(*) from peer full join cat on peer.category = cat.category "
        "where coalesce(peer.ns, 0) <> coalesce(cat.ns, 0) "
        "or coalesce(peer.nl, 0) <> coalesce(cat.nl, 0)",
    )
    assert differing == [(0,)]


def test_ac3_the_grand_total_plus_the_unknown_customer_equals_the_fact_total(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path, peer_groups=MIN2)
    peer = query(settings, "select sum(total_net_sales) from mart_peer_category_share")[0][0]
    unknown = query(
        settings,
        "select sum(net_sales) from mart_customer_category_month where customer_key = -1",
    )[0][0]
    fact = query(settings, "select sum(net_sales) from fact_sales where included")[0][0]
    assert (peer, unknown) == (Decimal("64.0000"), Decimal("9.0000"))
    assert peer + unknown == fact


def test_ac3_every_real_customer_is_in_exactly_one_group(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, peer_groups=MIN2)
    peers = query(
        settings,
        "select sum(n_peers) from (select distinct peer_columns, peer_keys, n_peers "
        "from mart_peer_category_share)",
    )
    assert peers == [(6,)]  # C1 to C6
    assert peers == query(
        settings, "select count(*) from mart_customer_profile where customer_key <> -1"
    )


def test_ac3_the_totals_hold_with_zero_fill_off(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, peer_groups=MIN2, marts={"zero_fill": False})
    assert query(settings, "select sum(total_net_sales) from mart_peer_category_share") == [
        (Decimal("64.0000"),)
    ]


def test_ac3_the_copy_kept_raises_the_total_by_its_amount(built: Settings, tmp_path: Path) -> None:
    on = gold(built, tmp_path / "on", peer_groups=MIN2, duplicates={"exclude_from_net_sales": True})
    off = gold(
        built, tmp_path / "off", peer_groups=MIN2, duplicates={"exclude_from_net_sales": False}
    )
    total = "select sum(total_net_sales) from mart_peer_category_share"
    assert query(off, total)[0][0] - query(on, total)[0][0] == Decimal("20.0000")


# AC4: a change to min_size or the group columns changes the mart with no code edit ------


def test_ac4_changing_min_size_changes_the_mart(built: Settings, tmp_path: Path) -> None:
    small = mart(gold(built, tmp_path / "a", peer_groups={"min_size": 1}))
    large = mart(gold(built, tmp_path / "b", peer_groups={"min_size": 10}))
    assert {k[0] for k in small} != {k[0] for k in large}
    assert len(small) != len(large)


def test_ac4_changing_the_group_columns_changes_the_mart(built: Settings, tmp_path: Path) -> None:
    by_channel = gold(
        built,
        tmp_path,
        peer_groups={"min_size": 2, "columns": ["Channel_Category"], "fallback_columns": []},
    )
    got = mart(by_channel)
    assert {k[0] for k in got} == {("GT",), ("Modern Trade",)}
    assert got[(("GT",), A)]["n_peers"] == 5
    assert got[(("GT",), A)]["peer_columns"] == ["Channel_Category"]


def test_ac4_the_group_columns_can_be_swapped_and_reordered(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(
        built,
        tmp_path,
        peer_groups={
            "min_size": 2,
            "columns": ["Branch_Name", "Channel_Category"],
            "fallback_columns": ["Branch_Name"],
        },
    )
    got = mart(settings)
    assert (("Magway", "GT"), A) in got
    assert got[(("Magway", "GT"), A)]["peer_columns"] == ["Branch_Name", "Channel_Category"]


def test_ac4_the_sql_hard_codes_no_group_column_or_size() -> None:
    raw = (GOLD_DIR / "10_mart_peer_category_share.sql").read_text(encoding="utf-8")
    text = " ".join(line.split("--")[0] for line in raw.splitlines())
    for parameter in (
        "$peer_groups_columns",
        "$peer_groups_fallback_columns",
        "$peer_groups_min_size",
    ):
        assert parameter in text
    for literal in ("Channel_Category", "Branch_Name", "10"):
        assert literal not in text


# Unknown category, files and safety ------


def test_the_unknown_category_rows_are_kept_and_flagged(built: Settings, tmp_path: Path) -> None:
    got = mart(gold(built, tmp_path, peer_groups=MIN2))
    row = got[(("GT",), "Unknown")]
    assert row["f_unknown_category"] is True
    assert (row["n_buying"], row["total_net_sales"]) == (1, Decimal("2.0000"))
    assert all(r["f_unknown_category"] is (k[1] == "Unknown") for k, r in got.items())


def test_the_file_runs_after_the_profile_mart_and_before_the_branch_mart() -> None:
    names = sorted(p.name for p in GOLD_DIR.glob("*.sql"))
    assert names.index("09_mart_customer_profile.sql") < names.index(
        "10_mart_peer_category_share.sql"
    )
    assert names.index("10_mart_peer_category_share.sql") < names.index("11_mart_branch_month.sql")


def test_a_gold_rerun_gives_identical_rows(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, peer_groups=MIN2)
    sql = "select * from mart_peer_category_share order by peer_keys, category"
    first = query(settings, sql)
    run_gold(settings)
    assert query(settings, sql) == first


def test_changing_min_size_between_runs_replaces_the_mart(built: Settings, tmp_path: Path) -> None:
    first = gold(built, tmp_path, peer_groups={"min_size": 1})
    count = "select count(*) from mart_peer_category_share"
    before = query(first, count)[0][0]
    second = variant(tmp_path / "again", first, peer_groups={"min_size": 10})
    run_gold(second)
    assert query(second, count)[0][0] != before


def test_gold_refuses_a_typed_peer_column(built: Settings, tmp_path: Path) -> None:
    with pytest.raises(GoldError, match="peer_groups.columns"):
        gold(built, tmp_path, peer_groups={"columns": ["Date"], "fallback_columns": []})


def test_the_gold_stage_logs_and_the_mart_holds_no_customer_codes(
    built: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        settings = gold(built, tmp_path, peer_groups=MIN2)
    assert S not in caplog.text
    # peer keys are channel and branch labels and categories are product categories, but no
    # customer code or name reaches the mart
    assert "name" not in repr(query(settings, "select peer_keys from mart_peer_category_share"))


# AC5 ------


def test_ac5_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 5):
        assert f"def test_ac{ac}_" in text


@pytest.mark.realdata
def test_ac1_ac2_ac3_real_file_peer_mart(tmp_path: Path) -> None:
    """Counts and sums only. Gold runs on a temporary warehouse built from the real bronze files."""
    real = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    if not list(real.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    from revint.silver import run_silver

    run_silver(real)
    run_gold(real)
    assert query(
        real,
        "select count(*) from (select peer_columns, peer_keys, category "
        "from mart_peer_category_share group by 1, 2, 3 having count(*) > 1)",
    ) == [(0,)]
    assert query(
        real,
        "select sum(n_peers) from (select distinct peer_columns, peer_keys, n_peers "
        "from mart_peer_category_share)",
    ) == [(12_239,)]
    assert query(
        real,
        "select count(*) from (select category, sum(total_net_sales) as ns "
        "from mart_peer_category_share group by 1) as peer "
        "full join (select category, sum(net_sales) as ns from mart_customer_category_month "
        "where customer_key <> -1 group by 1) as cat on peer.category = cat.category "
        "where coalesce(peer.ns, 0) <> coalesce(cat.ns, 0)",
    ) == [(0,)]
    assert query(
        real,
        "select count(*) from mart_peer_category_share "
        "where penetration < 0 or penetration > 1 or n_buying > n_peers",
    ) == [(0,)]
    assert query(
        real,
        "select count(*) from mart_peer_category_share where not f_below_min_size "
        "and n_peers < (select 10)",
    ) == [(0,)]
    off = variant(tmp_path / "small", real, peer_groups={"min_size": 1})
    run_gold(off)
    assert query(off, "select count(*) from mart_peer_category_share where f_fallback") == [(0,)]
