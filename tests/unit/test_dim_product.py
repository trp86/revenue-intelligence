"""Story #78: dim_product (spec 02 section 4; columns chosen in story #73).

Synthetic data only; names, brands and categories carry a SECRET- marker to prove none reaches
logs. Silver is built once per module, each test copies the warehouse and runs gold on its own
copy. The real-file test is marked `realdata` and asserts counts only.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pytest
from gold_helpers import gold
from silver_helpers import bronze_row, build, query

from revint.config import Settings, load_settings
from revint.gold import GOLD_DIR, GoldError, run_gold

S = "SECRET-"


def sale(
    row: int,
    code: str | None,
    name: str | None = None,
    brand: str | None = None,
    category: str | None = None,
    order: int | None = None,
) -> dict[str, str | None]:
    return bronze_row(
        row,
        OrderReference=f"O{order or row}",
        SCJ_CODE_1=code,
        Product_Decription=name,
        Actual_Brands_1=brand,
        Internal_Category=category,
    )


ROWS = [
    # P1: a name seen twice beats one seen once.
    sale(8, "P1", f"{S}One", f"{S}B1", f"{S}C1"),
    sale(9, "P1", f"{S}One", f"{S}B1", f"{S}C1"),
    sale(10, "P1", f"{S}Uno", f"{S}B1", f"{S}C1"),
    # P2: a tie on the name and on the brand goes to the value on the lowest _source_row.
    sale(11, "P2", f"{S}Two", f"{S}B1", f"{S}C2"),
    sale(12, "P2", f"{S}Dos", f"{S}B2", f"{S}C2"),
    # P3: no category.
    sale(13, "P3", f"{S}Three", f"{S}B2", None),
    # P4: nothing but the code.
    sale(14, "P4"),
    # Blank codes: empty, whitespace-only and non-breaking space.
    sale(15, None, f"{S}Nobody", f"{S}B1", f"{S}C1"),
    sale(16, "   ", f"{S}Nobody", f"{S}B1", f"{S}C1"),
    sale(17, " ", f"{S}Nobody", f"{S}B1", f"{S}C1"),
    # P5: an exact duplicate pair; the copy (row 19) is excluded.
    sale(18, "P5", f"{S}Five", f"{S}B1", f"{S}C1", order=18),
    sale(19, "P5", f"{S}Five", f"{S}B1", f"{S}C1", order=18),
    # p1: a near-duplicate code (case only). The code is never folded, so it is a new product.
    sale(20, "p1", f"{S}One", f"{S}B1", f"{S}C1"),
    bronze_row(21, Change_to_Ctn="1"),  # the stray row
]
CODES = ["P1", "P2", "P3", "P4", "P5", "p1"]
COLUMNS = (
    "product_key, product_code, product_name, brand, category, n_name_values, n_brand_values, "
    "n_category_values, f_value_conflict, f_no_category, order_lines"
)


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("dimproduct")
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    build(settings, ROWS)
    return settings


def products(settings: Settings) -> dict[str, dict]:
    names = [c.strip() for c in COLUMNS.split(",")]
    rows = query(settings, f"select {COLUMNS} from dim_product where product_key <> -1")
    return {r[1]: dict(zip(names, r, strict=True)) for r in rows}


def key_of(code: str) -> int:
    return int(hashlib.md5(code.encode("utf-8")).hexdigest()[:15], 16)


# AC1: one row per product code with name, brand and category ------


def test_ac1_one_row_per_product_code(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert sorted(products(settings)) == sorted(CODES)
    assert query(settings, "select count(*) from dim_product") == [(len(CODES) + 1,)]


def test_ac1_the_table_has_the_documented_columns(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    columns = [
        c
        for (c,) in query(
            settings,
            "select column_name from information_schema.columns "
            "where table_name = 'dim_product' order by ordinal_position",
        )
    ]
    assert columns == [c.strip() for c in COLUMNS.split(",")]


def test_ac1_name_brand_and_category_come_from_the_configured_columns(
    built: Settings, tmp_path: Path
) -> None:
    got = products(gold(built, tmp_path))["P5"]
    assert (got["product_name"], got["brand"], got["category"]) == (
        f"{S}Five",
        f"{S}B1",
        f"{S}C1",
    )


def test_ac1_the_columns_follow_the_product_settings(built: Settings, tmp_path: Path) -> None:
    # point brand at the category column: every brand becomes the category value
    settings = gold(built, tmp_path, product={"brand_column": "Internal_Category"})
    assert products(settings)["P2"]["brand"] == f"{S}C2"


def test_ac1_the_product_code_is_the_code_as_written(built: Settings, tmp_path: Path) -> None:
    assert "p1" in products(gold(built, tmp_path))


def test_ac1_order_lines_count_the_kept_lines_per_code(built: Settings, tmp_path: Path) -> None:
    got = products(gold(built, tmp_path))
    assert {c: r["order_lines"] for c, r in got.items()} == {
        "P1": 3,
        "P2": 2,
        "P3": 1,
        "P4": 1,
        "P5": 1,  # the copy on row 19 is excluded
        "p1": 1,
    }


def test_ac1_a_product_with_no_name_or_brand_shows_unknown(built: Settings, tmp_path: Path) -> None:
    got = products(gold(built, tmp_path))["P4"]
    assert (got["product_name"], got["brand"], got["category"]) == ("Unknown", "Unknown", "Unknown")
    assert (got["n_name_values"], got["n_brand_values"], got["n_category_values"]) == (0, 0, 0)


# AC2: no category gives Unknown and a flag ------


def test_ac2_a_product_with_no_category_has_category_unknown_and_the_flag(
    built: Settings, tmp_path: Path
) -> None:
    got = products(gold(built, tmp_path))
    assert (got["P3"]["category"], got["P3"]["f_no_category"]) == ("Unknown", True)
    assert (got["P4"]["category"], got["P4"]["f_no_category"]) == ("Unknown", True)


def test_ac2_a_product_with_a_category_is_not_flagged(built: Settings, tmp_path: Path) -> None:
    got = products(gold(built, tmp_path))
    flagged = sorted(code for code, row in got.items() if row["f_no_category"])
    assert flagged == ["P3", "P4"]
    assert got["P1"]["category"] == f"{S}C1"


def test_ac2_a_whitespace_only_category_counts_as_no_category(tmp_path: Path) -> None:
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
            "REVINT_PATHS_BRONZE": str(tmp_path / "b"),
        }
    )
    build(settings, [sale(8, "X", "Ex", "B", "   "), sale(9, "Y", "Why", "B", " ")])
    run_gold(settings)
    assert {(c, r["category"], r["f_no_category"]) for c, r in products(settings).items()} == {
        ("X", "Unknown", True),
        ("Y", "Unknown", True),
    }


def test_ac2_a_real_category_called_unknown_is_not_flagged(tmp_path: Path) -> None:
    # the flag says "the source had no category", not "the word is Unknown"
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
            "REVINT_PATHS_BRONZE": str(tmp_path / "b"),
        }
    )
    build(settings, [sale(8, "X", "Ex", "B", "Unknown")])
    run_gold(settings)
    assert products(settings)["X"]["f_no_category"] is False


# AC3: key deterministic and unique; unknown member; blank code maps to -1 ------


def test_ac3_product_key_is_the_hash_of_the_code(built: Settings, tmp_path: Path) -> None:
    for code, row in products(gold(built, tmp_path)).items():
        assert row["product_key"] == key_of(code)


def test_ac3_keys_are_unique_and_positive_apart_from_the_unknown_member(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path)
    assert query(settings, "select count(*), count(distinct product_key) from dim_product") == [
        (len(CODES) + 1, len(CODES) + 1)
    ]
    assert query(
        settings, "select count(*) from dim_product where product_key <> -1 and product_key < 1"
    ) == [(0,)]


def test_ac3_near_duplicate_codes_get_different_keys(built: Settings, tmp_path: Path) -> None:
    got = products(gold(built, tmp_path))
    assert got["P1"]["product_key"] != got["p1"]["product_key"]


def test_ac3_the_unknown_member_exists_once(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(settings, f"select {COLUMNS} from dim_product where product_key = -1") == [
        (-1, None, "Unknown", "Unknown", "Unknown", 0, 0, 0, False, True, 0)
    ]


def test_ac3_blank_code_lines_map_to_the_unknown_member_and_none_is_dropped(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path)
    got = query(
        settings,
        "select count(*), count(*) filter (where coalesce(p.product_key, -1) = -1), "
        "count(*) filter (where nullif(trim(s.\"SCJ_CODE_1\", ' ' || chr(160)), '') is not null "
        "and p.product_key is null) "
        "from silver_sales as s left join dim_product as p "
        "on p.product_code = nullif(trim(s.\"SCJ_CODE_1\", ' ' || chr(160)), '')",
    )
    total = query(settings, "select count(*) from silver_sales")[0][0]
    # rows 15, 16, 17 have a blank code; the stray row has none; the excluded copy has P5
    assert got == [(total, 4, 0)]


def test_ac3_the_join_never_multiplies_a_line(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(
        settings,
        "select count(*) from silver_sales as s left join dim_product as p "
        "on p.product_code = nullif(trim(s.\"SCJ_CODE_1\"), '')",
    ) == query(settings, "select count(*) from silver_sales")


def test_ac3_a_rebuild_gives_identical_rows_and_keys(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    first = query(settings, "select * from dim_product order by product_key")
    run_gold(settings)
    assert query(settings, "select * from dim_product order by product_key") == first


def test_ac3_two_warehouses_from_the_same_data_give_the_same_rows(
    built: Settings, tmp_path: Path
) -> None:
    assert products(gold(built, tmp_path / "a")) == products(gold(built, tmp_path / "b"))


def test_ac3_silver_with_no_products_gives_only_the_unknown_member(tmp_path: Path) -> None:
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
            "REVINT_PATHS_BRONZE": str(tmp_path / "b"),
        }
    )
    build(settings, [sale(8, None, "Nobody")])
    run_gold(settings)
    assert query(settings, "select product_key from dim_product") == [(-1,)]


# AC4: several values use the most frequent one, and the conflict count is reported ------


def test_ac4_the_most_frequent_value_is_used(built: Settings, tmp_path: Path) -> None:
    assert products(gold(built, tmp_path))["P1"]["product_name"] == f"{S}One"


def test_ac4_a_tie_goes_to_the_value_on_the_lowest_source_row(
    built: Settings, tmp_path: Path
) -> None:
    got = products(gold(built, tmp_path))["P2"]
    assert (got["product_name"], got["brand"]) == (f"{S}Two", f"{S}B1")


def test_ac4_value_counts_are_per_column(built: Settings, tmp_path: Path) -> None:
    got = products(gold(built, tmp_path))
    assert (got["P1"]["n_name_values"], got["P1"]["n_brand_values"]) == (2, 1)
    assert (got["P2"]["n_name_values"], got["P2"]["n_brand_values"]) == (2, 2)
    assert got["P2"]["n_category_values"] == 1


def test_ac4_f_value_conflict_marks_any_column_with_several_values(
    built: Settings, tmp_path: Path
) -> None:
    got = products(gold(built, tmp_path))
    assert sorted(code for code, row in got.items() if row["f_value_conflict"]) == ["P1", "P2"]


def test_ac4_the_conflict_counts_are_reported_by_column(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    got = query(
        settings,
        "select count(*) filter (where n_name_values > 1), "
        "count(*) filter (where n_brand_values > 1), "
        "count(*) filter (where n_category_values > 1), "
        "count(*) filter (where f_value_conflict) from dim_product",
    )
    assert got == [(2, 1, 0, 2)]


def test_ac4_a_blank_beside_a_value_is_not_a_conflict(tmp_path: Path) -> None:
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
            "REVINT_PATHS_BRONZE": str(tmp_path / "b"),
        }
    )
    build(settings, [sale(8, "X", "Ex", "B", "C"), sale(9, "X", "Ex", None, "  ")])
    run_gold(settings)
    got = products(settings)["X"]
    assert (got["n_brand_values"], got["n_category_values"], got["f_value_conflict"]) == (
        1,
        1,
        False,
    )


def test_ac4_excluded_lines_add_no_values(built: Settings, tmp_path: Path) -> None:
    got = products(gold(built, tmp_path))["P5"]
    assert (got["n_name_values"], got["order_lines"]) == (1, 1)


def test_ac4_values_are_compared_as_trimmed_text_with_the_case_kept(tmp_path: Path) -> None:
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
            "REVINT_PATHS_BRONZE": str(tmp_path / "b"),
        }
    )
    build(settings, [sale(8, "X", "Ex", "B", "C"), sale(9, "X", "Ex", " B ", "c")])
    run_gold(settings)
    got = products(settings)["X"]
    assert (got["n_brand_values"], got["n_category_values"]) == (1, 2)


# Settings the SQL reads ------


def test_the_sql_hard_codes_no_column_name() -> None:
    raw = (GOLD_DIR / "05_dim_product.sql").read_text(encoding="utf-8")
    text = " ".join(line.split("--")[0] for line in raw.splitlines())
    for name in ("SCJ_CODE_1", "Product_Decription", "Actual_Brands", "Internal_Category"):
        assert name not in text
    for parameter in (
        "$product_code_column",
        "$product_name_column",
        "$product_brand_column",
        "$product_category_column",
    ):
        assert parameter in text


@pytest.mark.parametrize("key", ["code_column", "name_column", "brand_column", "category_column"])
def test_gold_refuses_a_typed_product_column(built: Settings, tmp_path: Path, key: str) -> None:
    with pytest.raises(GoldError, match=rf"product\.{key}"):
        gold(built, tmp_path, product={key: "Quantity(PCS)"})


def test_the_file_runs_after_dim_customer() -> None:
    names = sorted(p.name for p in GOLD_DIR.glob("*.sql"))
    assert names.index("04_dim_customer.sql") < names.index("05_dim_product.sql")


def test_the_earlier_gold_objects_are_still_built(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    for table in ("v_net_sales", "dim_date", "dim_branch", "dim_customer"):
        assert query(settings, f"select count(*) from {table}")[0][0] > 0


# Safety ------


def test_the_gold_stage_logs_and_stores_no_names_brands_or_categories(
    built: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        settings = gold(built, tmp_path)
    assert S not in caplog.text
    # the dimension itself holds the values (it is the dimension); the table of counts does not
    counts = query(
        settings,
        "select n_name_values, n_brand_values, n_category_values, order_lines from dim_product",
    )
    assert S not in repr(counts)


def test_a_gold_error_message_holds_no_product_values(built: Settings, tmp_path: Path) -> None:
    with pytest.raises(GoldError) as info:
        gold(built, tmp_path, product={"brand_column": "Date"})
    assert S not in str(info.value)


# AC6 ------


def test_ac6_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 5):
        assert f"def test_ac{ac}_" in text
    assert "def test_ac5_real_file" in text


@pytest.mark.realdata
def test_ac5_real_file_product_count_equals_the_distinct_codes(tmp_path: Path) -> None:
    """Counts only. Gold runs on a temporary warehouse built from the real bronze files."""
    real = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    if not list(real.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    from revint.silver import run_silver

    run_silver(real)
    run_gold(real)
    distinct = query(
        real,
        "select count(distinct nullif(trim(\"SCJ_CODE_1\", ' ' || chr(9) || chr(10) || chr(13) "
        "|| chr(160)), '')) from silver_sales",
    )[0][0]
    assert distinct == 181
    assert query(real, "select count(*), count(distinct product_key) from dim_product") == [
        (182, 182)
    ]
    assert query(real, "select count(*) from dim_product where product_key = -1") == [(1,)]
    assert query(
        real,
        "select count(*) filter (where n_name_values > 1), "
        "count(*) filter (where n_brand_values > 1), "
        "count(*) filter (where n_category_values > 1), "
        "count(*) filter (where f_value_conflict) from dim_product where product_key <> -1",
    ) == [(12, 4, 2, 16)]
    assert query(
        real, "select count(*) from dim_product where product_key <> -1 and f_no_category"
    ) == [(4,)]
    assert query(
        real,
        "select count(*) from dim_product where product_key <> -1 and product_name = 'Unknown'",
    ) == [(9,)]
    lost = query(
        real,
        "select count(*) filter (where nullif(trim(s.\"SCJ_CODE_1\"), '') is not null "
        "and p.product_key is null), count(*) from silver_sales as s left join dim_product as p "
        "on p.product_code = nullif(trim(s.\"SCJ_CODE_1\"), '')",
    )
    assert lost == [(0, 662_128)]
    assert query(real, "select sum(order_lines) from dim_product") == [(660_545,)]
