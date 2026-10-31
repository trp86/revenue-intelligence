"""Story #76: dim_branch (spec 02 section 4).

Synthetic data only. Silver is built once per module; each test copies the warehouse and runs
the gold stage on its own copy. The real-file test is marked `realdata` and asserts counts.
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

SECRET = "SECRET-"


def sale(row: int, branch: str | None, region: str | None = None) -> dict[str, str | None]:
    return bronze_row(
        row,
        OrderReference=f"O{row}",
        Customer=f"{SECRET}C",
        Branch_Name=branch,
        Region=region,
    )


# Rows 8 to 19. The branch map joins MAGWAY and Magway, Hpa-an and Hpa-An, PYAY and Pyay;
# 'yangon' is only a case variant, which the map does not join.
ROWS = [
    sale(8, "MAGWAY", "North"),
    sale(9, "Magway", "North"),
    sale(10, "Hpa-an", "East"),
    sale(11, "Hpa-An", "West"),
    sale(12, "Hpa-An", "West"),
    sale(13, "Yangon", None),
    sale(14, " Yangon ", None),
    sale(15, "yangon", "South"),
    sale(16, None, "North"),
    sale(17, "Pyay", "Centre"),
    sale(18, "PYAY", "Delta"),
    sale(19, "DAWEI", "  "),
]
BRANCHES = ["Dawei", "Hpa-An", "Magway", "Pyay", "Yangon", "yangon"]


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("dimbranch")
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    build(settings, ROWS)
    return settings


def branches(settings: Settings) -> dict[str, tuple]:
    rows = query(
        settings,
        "select branch_name, branch_key, region, region_source, f_region_conflict "
        "from dim_branch where branch_key <> -1",
    )
    return {r[0]: r[1:] for r in rows}


def key_of(name: str) -> int:
    return int(hashlib.md5(name.encode("utf-8")).hexdigest()[:15], 16)


# AC1: one row per distinct normalised name, with a deterministic key ------


def test_ac1_one_row_per_distinct_normalised_branch(built: Settings, tmp_path: Path) -> None:
    got = branches(gold(built, tmp_path))
    assert sorted(got) == BRANCHES


def test_ac1_the_table_has_the_documented_columns(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    columns = [
        c
        for (c,) in query(
            settings,
            "select column_name from information_schema.columns "
            "where table_name = 'dim_branch' order by ordinal_position",
        )
    ]
    assert columns == ["branch_key", "branch_name", "region", "region_source", "f_region_conflict"]


def test_ac1_branch_key_is_the_hash_of_the_name(built: Settings, tmp_path: Path) -> None:
    got = branches(gold(built, tmp_path))
    for name, (key, *_) in got.items():
        assert key == key_of(name)


def test_ac1_keys_are_unique_positive_and_never_the_unknown_key(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path)
    assert query(settings, "select count(*), count(distinct branch_key) from dim_branch") == [
        (len(BRANCHES) + 1, len(BRANCHES) + 1)
    ]
    assert query(
        settings, "select count(*) from dim_branch where branch_key <> -1 and branch_key < 1"
    ) == [(0,)]


def test_ac1_names_are_unique(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(settings, "select count(*), count(distinct branch_name) from dim_branch") == [
        (len(BRANCHES) + 1, len(BRANCHES) + 1)
    ]


def test_ac1_a_rebuild_gives_identical_rows_and_keys(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    first = query(settings, "select * from dim_branch order by branch_key")
    run_gold(settings)
    assert query(settings, "select * from dim_branch order by branch_key") == first


def test_ac1_two_warehouses_from_the_same_data_give_the_same_keys(
    built: Settings, tmp_path: Path
) -> None:
    a = branches(gold(built, tmp_path / "a"))
    b = branches(gold(built, tmp_path / "b"))
    assert a == b


def test_ac1_the_name_is_the_normalised_label_without_padding(
    built: Settings, tmp_path: Path
) -> None:
    got = branches(gold(built, tmp_path))
    assert "Yangon" in got
    assert " Yangon " not in got
    assert all(name == name.strip() for name in got)


# AC2: region from the config map, else the source column, else Unknown ------


def test_ac2_region_comes_from_the_source_column_by_default(
    built: Settings, tmp_path: Path
) -> None:
    got = branches(gold(built, tmp_path))
    assert got["Magway"][1:3] == ("North", "source")
    assert got["yangon"][1:3] == ("South", "source")
    assert got["Dawei"][1:3] == ("Unknown", "unknown")  # a blank region
    assert got["Yangon"][1:3] == ("Unknown", "unknown")  # no region at all


def test_ac2_a_branch_with_several_regions_takes_the_most_frequent(
    built: Settings, tmp_path: Path
) -> None:
    got = branches(gold(built, tmp_path))
    assert got["Hpa-An"][1] == "West"  # West on two lines, East on one
    assert got["Hpa-An"][3] is True


def test_ac2_a_tie_goes_to_the_value_on_the_lowest_source_row(
    built: Settings, tmp_path: Path
) -> None:
    got = branches(gold(built, tmp_path))
    assert got["Pyay"][1] == "Centre"  # Centre on row 17, Delta on row 18
    assert got["Pyay"][3] is True


def test_ac2_a_branch_with_one_region_has_no_conflict(built: Settings, tmp_path: Path) -> None:
    got = branches(gold(built, tmp_path))
    assert [n for n, v in got.items() if v[3]] == ["Hpa-An", "Pyay"]


def test_ac2_the_config_map_overrides_the_source_column(built: Settings, tmp_path: Path) -> None:
    settings = gold(
        built,
        tmp_path,
        regions={"branch_to_region": {"Magway": "Upper", "Hpa-An": "Lower", "Yangon": "Coast"}},
    )
    got = branches(settings)
    assert got["Magway"][1:3] == ("Upper", "config")
    assert got["Hpa-An"][1:3] == ("Lower", "config")
    assert got["Yangon"][1:3] == ("Coast", "config")
    assert got["yangon"][1:3] == ("South", "source")  # the map is case-sensitive
    assert got["Pyay"][1:3] == ("Centre", "source")


def test_ac2_a_config_entry_removes_the_conflict_flag_but_not_the_data(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path, regions={"branch_to_region": {"Hpa-An": "Lower"}})
    assert branches(settings)["Hpa-An"][3] is False


def test_ac2_map_keys_match_after_trimming_both_ends(built: Settings, tmp_path: Path) -> None:
    # the data has a padded ' Yangon ' and a plain 'Yangon'; both are the branch Yangon
    settings = gold(built, tmp_path, regions={"branch_to_region": {"Yangon": "Coast"}})
    assert branches(settings)["Yangon"][1] == "Coast"


def test_ac2_a_map_entry_for_a_branch_that_does_not_exist_changes_nothing(
    built: Settings, tmp_path: Path
) -> None:
    plain = branches(gold(built, tmp_path / "a"))
    mapped = branches(gold(built, tmp_path / "b", regions={"branch_to_region": {"Nowhere": "X"}}))
    assert mapped == plain


def test_ac2_the_source_column_comes_from_config(built: Settings, tmp_path: Path) -> None:
    # Branch_Type is empty in the fixture, so every region becomes Unknown
    settings = gold(built, tmp_path, regions={"source_column": "Branch_Type"})
    assert {v[1] for v in branches(settings).values()} == {"Unknown"}


def test_ac2_a_source_column_that_is_typed_is_refused(built: Settings, tmp_path: Path) -> None:
    with pytest.raises(GoldError, match="regions.source_column"):
        gold(built, tmp_path, regions={"source_column": "Date"})


def test_ac2_a_region_is_never_blank(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(
        settings,
        "select count(*) from dim_branch where region is null or trim(region) = ''",
    ) == [(0,)]


# AC3: a blank branch maps to the unknown member and no row is dropped ------


def test_ac3_the_unknown_member_exists_once(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(
        settings,
        "select branch_key, branch_name, region, region_source, f_region_conflict "
        "from dim_branch where branch_key = -1",
    ) == [(-1, "Unknown", "Unknown", "unknown", False)]


def test_ac3_every_silver_line_finds_a_branch_and_none_is_dropped(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path)
    got = query(
        settings,
        "select count(*), count(*) filter (where coalesce(b.branch_key, -1) = -1) "
        "from silver_sales as s left join dim_branch as b "
        "on b.branch_name = nullif(trim(s.\"Branch_Name_normalised\"), '')",
    )
    total = query(settings, "select count(*) from silver_sales")[0][0]
    assert got == [(total, 1)]  # one line has no branch; the join never multiplies a line


def test_ac3_a_blank_branch_line_joins_the_unknown_member(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    got = query(
        settings,
        "select s._source_row, coalesce(b.branch_key, -1) from silver_sales as s "
        "left join dim_branch as b "
        "on b.branch_name = nullif(trim(s.\"Branch_Name_normalised\"), '') "
        "where s._source_row = 16",
    )
    assert got == [(16, -1)]


def test_ac3_whitespace_only_branches_are_blank_too(tmp_path: Path) -> None:
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
            "REVINT_PATHS_BRONZE": str(tmp_path / "b"),
        }
    )
    build(settings, [sale(8, "   "), sale(9, " "), sale(10, "Magway", "North")])
    run_gold(settings)
    assert sorted(r[0] for r in query(settings, "select branch_key from dim_branch")) == [
        -1,
        key_of("Magway"),
    ]


def test_ac3_with_no_branches_at_all_only_the_unknown_member_remains(tmp_path: Path) -> None:
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
            "REVINT_PATHS_BRONZE": str(tmp_path / "b"),
        }
    )
    build(settings, [sale(8, None)])
    run_gold(settings)
    assert query(settings, "select branch_key from dim_branch") == [(-1,)]


# AC4: the label map joins variants; nothing else is merged ------


def test_ac4_variants_the_map_joins_are_one_branch(built: Settings, tmp_path: Path) -> None:
    got = branches(gold(built, tmp_path))
    assert "MAGWAY" not in got and "Magway" in got
    assert "Hpa-an" not in got and "Hpa-An" in got
    assert "PYAY" not in got and "Pyay" in got
    assert "DAWEI" not in got and "Dawei" in got


def test_ac4_a_case_variant_the_map_does_not_join_stays_separate(
    built: Settings, tmp_path: Path
) -> None:
    got = branches(gold(built, tmp_path))
    assert "Yangon" in got and "yangon" in got
    assert got["Yangon"][0] != got["yangon"][0]


def test_ac4_the_dimension_follows_the_normalised_twin_not_the_raw_label(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path)
    raw = query(
        settings, "select count(distinct nullif(trim(\"Branch_Name\"), '')) from silver_sales"
    )
    assert raw[0][0] > len(BRANCHES) - 1
    assert len(branches(settings)) == len(BRANCHES)


def test_ac4_dim_branch_needs_exactly_one_branch_label_column(
    built: Settings, tmp_path: Path
) -> None:
    with pytest.raises(GoldError, match="labels.branch_columns"):
        gold(built, tmp_path, labels={"branch_columns": ["Branch_Name", "Branch_Type"]})


# Safety ------


def test_the_gold_stage_logs_and_stores_no_cell_values(
    built: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        settings = gold(built, tmp_path)
    assert SECRET not in caplog.text
    assert SECRET not in repr(query(settings, "select * from dim_branch"))


def test_the_sql_hard_codes_no_column_name() -> None:
    raw = (GOLD_DIR / "03_dim_branch.sql").read_text(encoding="utf-8")
    text = " ".join(line.split("--")[0] for line in raw.splitlines())  # code, not comments
    for name in ("Branch_Name", "Region", "Branch_Type"):
        assert name not in text
    assert "$regions_source_column" in text
    assert "$labels_branch_columns" in text


def test_the_files_run_after_the_view_and_dim_date() -> None:
    names = sorted(p.name for p in GOLD_DIR.glob("*.sql"))
    assert names.index("02_dim_date.sql") < names.index("03_dim_branch.sql")


def test_the_earlier_gold_objects_are_still_built(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(settings, "select count(*) from v_net_sales")[0][0] > 0
    assert query(settings, "select count(*) from dim_date")[0][0] > 0


# AC5 ------


def test_ac5_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 5):
        assert f"def test_ac{ac}_" in text


@pytest.mark.realdata
def test_ac1_ac2_ac3_real_file_branches(tmp_path: Path) -> None:
    """Counts only. Gold runs on a temporary warehouse built from the real bronze files."""
    real = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    if not list(real.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    from revint.silver import run_silver

    run_silver(real)
    run_gold(real)
    assert query(real, "select count(*), count(distinct branch_key) from dim_branch") == [(34, 34)]
    assert query(real, "select count(*) from dim_branch where f_region_conflict") == [(6,)]
    assert query(real, "select count(*) from dim_branch where region = 'Unknown'") == [(1,)]
    assert query(real, "select count(distinct region) from dim_branch where branch_key <> -1") == [
        (2,)
    ]
    lost = query(
        real,
        "select count(*) from silver_sales as s left join dim_branch as b "
        "on b.branch_name = nullif(trim(s.\"Branch_Name_normalised\"), '') "
        'where s."Branch_Name_normalised" is not null and b.branch_key is null',
    )
    assert lost == [(0,)]
