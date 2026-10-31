"""Story #77: dim_customer (spec 02 section 4).

Synthetic data only; customer values carry a SECRET- marker to prove none reaches logs. Silver is
built once per module, each test copies the warehouse and runs gold on its own copy. The
real-file test is marked `realdata` and asserts counts only.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date
from pathlib import Path

import pytest
from gold_helpers import gold
from silver_helpers import bronze_row, build, query

from revint.config import Settings, load_settings
from revint.gold import GOLD_DIR, GoldError, run_gold

SECRET = "SECRET-"


def sale(
    row: int,
    code: str | None,
    name: str | None = None,
    branch: str | None = None,
    channel: str | None = None,
    day: str | None = None,
    order: int | None = None,
) -> dict[str, str | None]:
    return bronze_row(
        row,
        OrderReference=f"O{order or row}",
        CustomerCode=code,
        Customer=name,
        Branch_Name=branch,
        Channel_Category=channel,
        Date=day,
    )


S = SECRET
ROWS = [
    # A1: a name seen twice beats one seen once; branches differ; the latest order decides
    # channel and branch (the label maps turn PYAY into Pyay and MT into Modern Trade).
    sale(8, f"{S}A1", f"{S}Alpha", "Magway", "GT", "2019-01-01"),
    sale(9, f"{S}A1", f"{S}Alpha", "Magway", "GT", "2019-02-01"),
    sale(10, f"{S}A1", f"{S}Alpha Ltd", "PYAY", "MT", "2019-03-01"),
    # B1: two spellings seen once each: the one on the later order wins.
    sale(11, f"{S}B1", f"{S}Beta One", "Magway", "GT", "2019-05-01"),
    sale(12, f"{S}B1", f"{S}Beta Uno", "Magway", "GT", "2019-06-01"),
    # C1 and c1: near-duplicate codes (case only). Two rows, never merged.
    sale(13, f"{S}C1", f"{S}Cee", "Magway", "GT", "2019-01-01"),
    sale(14, f"{S}c1", f"{S}Cee", "Magway", "GT", "2019-01-02"),
    # Blank codes: an empty one and a whitespace-only one.
    sale(15, None, f"{S}Nobody", "Magway", "GT", "2019-01-03"),
    sale(16, "   ", f"{S}Nobody", "Magway", "GT", "2019-01-04"),
    # E1: no name and no date.
    sale(17, f"{S}E1", None, "Dawei", "GT", None),
    # F1: an exact duplicate pair; the copy (row 19) is excluded and counted nowhere.
    sale(18, f"{S}F1", f"{S}Eff", "Magway", "GT", "2019-04-01", order=18),
    sale(19, f"{S}F1", f"{S}Eff", "Magway", "GT", "2019-04-01", order=18),
    # G1: two branches on the same latest date: the lowest _source_row wins.
    sale(20, f"{S}G1", f"{S}Gee", "Magway", "GT", "2019-07-01"),
    sale(21, f"{S}G1", f"{S}Gee", "PYAY", "GT", "2019-07-01"),
    # H1: the latest order has no branch, so the latest order that has one is used.
    sale(22, f"{S}H1", f"{S}Aitch", "Magway", "GT", "2019-01-01"),
    sale(23, f"{S}H1", f"{S}Aitch", None, "GT", "2019-02-01"),
    bronze_row(24, Change_to_Ctn="1"),  # the stray row
]
CODES = [f"{S}A1", f"{S}B1", f"{S}C1", f"{S}E1", f"{S}F1", f"{S}G1", f"{S}H1", f"{S}c1"]


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("dimcustomer")
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    build(settings, ROWS)
    return settings


COLUMNS = (
    "customer_key, customer_code, customer_name, n_name_variants, n_branches, "
    "n_near_duplicate_codes, f_multi_identity, channel, branch, first_order_date, "
    "last_order_date, order_lines"
)


def customers(settings: Settings) -> dict[str, dict]:
    names = [c.strip() for c in COLUMNS.split(",")]
    rows = query(settings, f"select {COLUMNS} from dim_customer where customer_key <> -1")
    return {r[1]: dict(zip(names, r, strict=True)) for r in rows}


def key_of(code: str) -> int:
    return int(hashlib.md5(code.encode("utf-8")).hexdigest()[:15], 16)


# AC1: one row per customer code with a deterministic key and the unknown member ------


def test_ac1_one_row_per_customer_code_in_silver_customer_codes(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path)
    assert sorted(customers(settings)) == CODES
    assert query(settings, "select count(*) from dim_customer") == [(len(CODES) + 1,)]
    silver = query(settings, "select count(*) from silver_customer_codes")
    assert silver == [(len(CODES),)]


def test_ac1_the_table_has_the_documented_columns(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    columns = [
        c
        for (c,) in query(
            settings,
            "select column_name from information_schema.columns "
            "where table_name = 'dim_customer' order by ordinal_position",
        )
    ]
    assert columns == [c.strip() for c in COLUMNS.split(",")]


def test_ac1_customer_key_is_the_hash_of_the_code(built: Settings, tmp_path: Path) -> None:
    for code, row in customers(gold(built, tmp_path)).items():
        assert row["customer_key"] == key_of(code)


def test_ac1_keys_are_unique_and_positive_apart_from_the_unknown_member(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path)
    assert query(settings, "select count(*), count(distinct customer_key) from dim_customer") == [
        (len(CODES) + 1, len(CODES) + 1)
    ]
    assert query(
        settings, "select count(*) from dim_customer where customer_key <> -1 and customer_key < 1"
    ) == [(0,)]


def test_ac1_the_unknown_member_exists_once(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(
        settings,
        f"select {COLUMNS} from dim_customer where customer_key = -1",
    ) == [(-1, None, "Unknown", 0, 0, 0, False, "Unknown", "Unknown", None, None, 0)]


def test_ac1_a_rebuild_gives_identical_rows_and_keys(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    first = query(settings, "select * from dim_customer order by customer_key")
    run_gold(settings)
    assert query(settings, "select * from dim_customer order by customer_key") == first


def test_ac1_two_warehouses_from_the_same_data_give_the_same_rows(
    built: Settings, tmp_path: Path
) -> None:
    assert customers(gold(built, tmp_path / "a")) == customers(gold(built, tmp_path / "b"))


# AC2: name, variant counts, flag, latest-order attributes and dates ------


def test_ac2_the_name_is_the_most_frequent_spelling(built: Settings, tmp_path: Path) -> None:
    got = customers(gold(built, tmp_path))
    assert got[f"{S}A1"]["customer_name"] == f"{S}Alpha"


def test_ac2_a_tie_between_spellings_goes_to_the_one_on_the_later_order(
    built: Settings, tmp_path: Path
) -> None:
    assert customers(gold(built, tmp_path))[f"{S}B1"]["customer_name"] == f"{S}Beta Uno"


def test_ac2_a_tie_on_the_same_date_goes_to_the_lowest_source_row(tmp_path: Path) -> None:
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
            "REVINT_PATHS_BRONZE": str(tmp_path / "b"),
        }
    )
    build(
        settings,
        [
            sale(8, "X", "Second", day="2019-01-01"),
            sale(9, "X", "First", day="2019-01-01"),
        ],
    )
    run_gold(settings)
    assert customers(settings)["X"]["customer_name"] == "Second"


def test_ac2_variant_counts_come_from_silver(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    got = customers(settings)
    silver = {
        r[0]: r[1:]
        for r in query(
            settings,
            "select customer_code, name_count, branch_count, near_duplicate_count "
            "from silver_customer_codes",
        )
    }
    for code, row in got.items():
        names, branches, near = silver[code]
        assert (row["n_name_variants"], row["n_branches"], row["n_near_duplicate_codes"]) == (
            names,
            branches,
            near,
        )
    assert (got[f"{S}A1"]["n_name_variants"], got[f"{S}A1"]["n_branches"]) == (2, 2)


def test_ac2_f_multi_identity_is_any_of_several_names_several_branches_or_a_near_duplicate(
    built: Settings, tmp_path: Path
) -> None:
    got = customers(gold(built, tmp_path))
    flagged = sorted(code for code, row in got.items() if row["f_multi_identity"])
    # A1 several names and branches, B1 several names, C1 and c1 near-duplicates, G1 several
    # branches. E1, F1 and H1 have one name and one branch and no near-duplicate.
    assert flagged == [f"{S}A1", f"{S}B1", f"{S}C1", f"{S}G1", f"{S}c1"]


def test_ac2_channel_and_branch_come_from_the_latest_order_and_are_normalised(
    built: Settings, tmp_path: Path
) -> None:
    got = customers(gold(built, tmp_path))[f"{S}A1"]
    assert (got["channel"], got["branch"]) == ("Modern Trade", "Pyay")


def test_ac2_two_branches_on_the_latest_date_go_to_the_lowest_source_row(
    built: Settings, tmp_path: Path
) -> None:
    assert customers(gold(built, tmp_path))[f"{S}G1"]["branch"] == "Magway"


def test_ac2_a_blank_branch_on_the_latest_order_falls_back_to_the_latest_that_has_one(
    built: Settings, tmp_path: Path
) -> None:
    assert customers(gold(built, tmp_path))[f"{S}H1"]["branch"] == "Magway"


def test_ac2_first_and_last_order_dates(built: Settings, tmp_path: Path) -> None:
    got = customers(gold(built, tmp_path))
    assert (got[f"{S}A1"]["first_order_date"], got[f"{S}A1"]["last_order_date"]) == (
        date(2019, 1, 1),
        date(2019, 3, 1),
    )
    assert got[f"{S}E1"]["first_order_date"] is None
    assert got[f"{S}E1"]["last_order_date"] is None


def test_ac2_a_customer_with_no_name_has_unknown_and_zero_variants(
    built: Settings, tmp_path: Path
) -> None:
    got = customers(gold(built, tmp_path))[f"{S}E1"]
    assert (got["customer_name"], got["n_name_variants"]) == ("Unknown", 0)
    assert (got["channel"], got["branch"]) == ("GT", "Dawei")


def test_ac2_a_customer_with_no_channel_or_branch_has_unknown(tmp_path: Path) -> None:
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
            "REVINT_PATHS_BRONZE": str(tmp_path / "b"),
        }
    )
    build(settings, [sale(8, "X", "Ex", None, None, "2019-01-01")])
    run_gold(settings)
    assert (customers(settings)["X"]["channel"], customers(settings)["X"]["branch"]) == (
        "Unknown",
        "Unknown",
    )


def test_ac2_excluded_lines_count_nowhere(built: Settings, tmp_path: Path) -> None:
    got = customers(gold(built, tmp_path))[f"{S}F1"]
    assert got["order_lines"] == 1  # the copy on row 19 is excluded
    assert got["n_name_variants"] == 1


def test_ac2_order_lines_equal_the_kept_lines_per_code(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    total = sum(row["order_lines"] for row in customers(settings).values())
    kept = query(
        settings,
        'select count(*) from silver_sales where not is_excluded and "CustomerCode" is not null '
        "and trim(\"CustomerCode\") <> ''",
    )[0][0]
    assert total == kept


# AC3: near-duplicate codes stay two rows ------


def test_ac3_near_duplicate_codes_stay_two_rows_with_their_own_keys(
    built: Settings, tmp_path: Path
) -> None:
    got = customers(gold(built, tmp_path))
    upper, lower = got[f"{S}C1"], got[f"{S}c1"]
    assert upper["customer_key"] != lower["customer_key"]
    assert (upper["order_lines"], lower["order_lines"]) == (1, 1)
    assert (upper["n_near_duplicate_codes"], lower["n_near_duplicate_codes"]) == (1, 1)


def test_ac3_a_near_duplicate_is_flagged_even_with_one_name_and_one_branch(
    built: Settings, tmp_path: Path
) -> None:
    got = customers(gold(built, tmp_path))
    for code in (f"{S}C1", f"{S}c1"):
        assert (got[code]["n_name_variants"], got[code]["n_branches"]) == (1, 1)
        assert got[code]["f_multi_identity"] is True


def test_ac3_the_code_is_never_trimmed_or_case_folded(built: Settings, tmp_path: Path) -> None:
    assert f"{S}c1" in customers(gold(built, tmp_path))


# AC4: a blank code maps to -1 and no line is dropped ------


def test_ac4_blank_code_lines_map_to_the_unknown_member_and_none_is_dropped(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path)
    got = query(
        settings,
        "select count(*), count(*) filter (where coalesce(c.customer_key, -1) = -1), "
        "count(*) filter (where nullif(trim(s.\"CustomerCode\"), '') is not null "
        "and c.customer_key is null) "
        "from silver_sales as s left join dim_customer as c "
        "on c.customer_code = nullif(trim(s.\"CustomerCode\"), '')",
    )
    total = query(settings, "select count(*) from silver_sales")[0][0]
    # blank-code lines: rows 15 and 16, plus the stray row (no code at all)
    assert got == [(total, 3, 0)]


def test_ac4_the_join_never_multiplies_a_line(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(
        settings,
        "select count(*) from silver_sales as s left join dim_customer as c "
        "on c.customer_code = nullif(trim(s.\"CustomerCode\"), '')",
    ) == query(settings, "select count(*) from silver_sales")


def test_ac4_no_dimension_row_is_made_for_a_blank_code(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(
        settings,
        "select count(*) from dim_customer where customer_code is not null "
        "and trim(customer_code) = ''",
    ) == [(0,)]


def test_ac4_silver_with_no_customers_gives_only_the_unknown_member(tmp_path: Path) -> None:
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
            "REVINT_PATHS_BRONZE": str(tmp_path / "b"),
        }
    )
    build(settings, [sale(8, None, "Nobody")])
    run_gold(settings)
    assert query(settings, "select customer_key from dim_customer") == [(-1,)]


# Settings the SQL reads ------


def test_the_columns_come_from_config_and_the_sql_hard_codes_none() -> None:
    raw = (GOLD_DIR / "04_dim_customer.sql").read_text(encoding="utf-8")
    text = " ".join(line.split("--")[0] for line in raw.splitlines())
    for name in ("CustomerCode", "Customer", "Branch_Name", "Channel_Category", '"Date"'):
        assert name not in text
    for parameter in (
        "$customers_code_column",
        "$customers_name_column",
        "$labels_channel_columns",
        "$labels_branch_columns",
        "$calendar_date_column",
    ):
        assert parameter in text


def test_gold_needs_exactly_one_channel_label_column(built: Settings, tmp_path: Path) -> None:
    with pytest.raises(GoldError, match="labels.channel_columns"):
        gold(built, tmp_path, labels={"channel_columns": ["Channel_Category", "Channel_Type"]})


def test_gold_refuses_a_typed_customer_code_column(built: Settings, tmp_path: Path) -> None:
    with pytest.raises(GoldError, match="customers.code_column"):
        gold(built, tmp_path, customers={"code_column": "Date"})


def test_gold_refuses_a_typed_customer_name_column(built: Settings, tmp_path: Path) -> None:
    with pytest.raises(GoldError, match="customers.name_column"):
        gold(built, tmp_path, customers={"name_column": "Year"})


def test_the_file_runs_after_dim_branch() -> None:
    names = sorted(p.name for p in GOLD_DIR.glob("*.sql"))
    assert names.index("03_dim_branch.sql") < names.index("04_dim_customer.sql")


def test_the_earlier_gold_objects_are_still_built(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    for table in ("v_net_sales", "dim_date", "dim_branch"):
        assert query(settings, f"select count(*) from {table}")[0][0] > 0


# Safety ------


def test_the_gold_stage_logs_no_customer_values(
    built: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        gold(built, tmp_path)
    assert SECRET not in caplog.text


def test_a_gold_error_message_holds_no_customer_values(built: Settings, tmp_path: Path) -> None:
    with pytest.raises(GoldError) as info:
        gold(built, tmp_path, customers={"code_column": "Date"})
    assert SECRET not in str(info.value)


# AC6 ------


def test_ac6_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 5):
        assert f"def test_ac{ac}_" in text
    assert "def test_ac5_real_file" in text


@pytest.mark.realdata
def test_ac5_real_file_row_count_equals_the_distinct_codes(tmp_path: Path) -> None:
    """Counts only. Gold runs on a temporary warehouse built from the real bronze files."""
    real = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    if not list(real.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    from revint.silver import run_silver

    run_silver(real)
    run_gold(real)
    codes = query(real, "select count(*) from silver_customer_codes")[0][0]
    assert codes == 12_239
    assert query(real, "select count(*), count(distinct customer_key) from dim_customer") == [
        (codes + 1, codes + 1)
    ]
    assert query(real, "select count(*) from dim_customer where customer_key = -1") == [(1,)]
    silver_flags = query(
        real,
        "select count(*) from silver_customer_codes "
        "where f_multiple_names or f_multiple_branches or near_duplicate_count > 0",
    )
    assert query(real, "select count(*) from dim_customer where f_multi_identity") == silver_flags
    assert query(real, "select count(*) from dim_customer where n_near_duplicate_codes > 0") == [
        (109,)
    ]
    lost = query(
        real,
        "select count(*) filter (where nullif(trim(s.\"CustomerCode\"), '') is not null "
        "and c.customer_key is null), count(*) from silver_sales as s "
        "left join dim_customer as c on c.customer_code = nullif(trim(s.\"CustomerCode\"), '')",
    )
    assert lost == [(0, 662_128)]
    assert query(
        real,
        "select count(*) from dim_customer where customer_key <> -1 and customer_name = 'Unknown'",
    ) == [(2,)]
    assert query(real, "select sum(order_lines) from dim_customer") == [(661_566,)]
