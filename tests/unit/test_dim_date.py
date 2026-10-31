"""Story #75: dim_date (spec 02 section 4).

Synthetic data only. Silver is built once per module; each test copies the warehouse and runs
the gold stage on its own copy. The real-file test is marked `realdata` and asserts counts.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import pytest
from gold_helpers import gold, variant
from silver_helpers import bronze_row, build, query

from revint.config import Settings, load_settings
from revint.gold import GOLD_DIR, GoldError, run_gold

SECRET = "SECRET-"
FIRST = date(2019, 12, 30)  # a Monday: ISO week 1 of 2020
MIDDLE = date(2020, 1, 5)
LAST = date(2020, 3, 1)  # one day after the as-of date 2020-02-29
DAYS = (LAST - FIRST).days + 1


def sale(row: int, day: str | None, **extra: str) -> dict[str, str | None]:
    return bronze_row(
        row, OrderReference=f"{SECRET}O{row}", Customer=f"{SECRET}C", Date=day, **extra
    )


ROWS = [
    sale(8, str(FIRST)),
    sale(9, str(MIDDLE)),
    sale(10, str(LAST)),
    sale(11, str(MIDDLE), Product_Decription=f"{SECRET}other"),
    sale(12, None),  # a line with no date
    sale(13, "not a date"),  # a line whose date silver could not type
]


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("dimdate")
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    build(settings, ROWS)
    return settings


def rows(settings: Settings, columns: str = "*", where: str = "date_key <> -1") -> list:
    return query(settings, f"select {columns} from dim_date where {where} order by date_key")


# AC1: one row per calendar day, no gaps, with the listed columns ------


def test_ac1_one_row_per_day_from_the_first_to_the_last_silver_date(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path)
    got = rows(settings, "date")
    assert [r[0] for r in got] == [FIRST + timedelta(days=n) for n in range(DAYS)]


def test_ac1_there_are_no_gaps_and_no_repeats(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(
        settings, "select count(*), count(distinct date) from dim_date where date_key <> -1"
    ) == [(DAYS, DAYS)]
    gaps = query(
        settings,
        "select count(*) from (select date - lag(date) over (order by date) as step "
        "from dim_date where date_key <> -1) where step <> 1",
    )
    assert gaps == [(0,)]


def test_ac1_the_table_has_the_documented_columns(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    columns = [
        c
        for (c,) in query(
            settings,
            "select column_name from information_schema.columns "
            "where table_name = 'dim_date' order by ordinal_position",
        )
    ]
    assert columns == [
        "date_key",
        "date",
        "week",
        "iso_year",
        "week_start",
        "month",
        "quarter",
        "year",
        "month_start",
        "fiscal_year",
        "fiscal_quarter",
        "f_after_asof",
    ]


def test_ac1_calendar_fields_of_a_known_day(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    got = query(
        settings,
        "select date_key, week, iso_year, week_start, month, quarter, year, month_start "
        "from dim_date where date = date '2019-12-30'",
    )
    assert got == [(20191230, 1, 2020, date(2019, 12, 30), 12, 4, 2019, date(2019, 12, 1))]


def test_ac1_the_week_starts_on_monday(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(
        settings,
        "select count(*) from dim_date where date_key <> -1 and dayofweek(week_start) <> 1",
    ) == [(0,)]
    assert query(
        settings,
        "select count(*) from dim_date where date_key <> -1 "
        "and date - week_start not between 0 and 6",
    ) == [(0,)]


def test_ac1_month_and_quarter_fields_are_consistent(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    bad = query(
        settings,
        "select count(*) from dim_date where date_key <> -1 and ("
        "month_start <> date_trunc('month', date) or quarter <> (month - 1) // 3 + 1 "
        "or year <> year(date))",
    )
    assert bad == [(0,)]


def test_ac1_dates_that_silver_could_not_type_add_no_day(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(settings, "select count(*) from dim_date where date_key <> -1") == [(DAYS,)]


def test_ac1_the_date_column_comes_from_config_and_is_checked(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path / "ok", calendar={"date_column": "Date"})
    assert query(settings, "select count(*) from dim_date") == [(DAYS + 1,)]
    with pytest.raises(GoldError, match="calendar.date_column"):
        gold(built, tmp_path / "bad", calendar={"date_column": "Customer"})


def test_ac1_a_date_column_that_is_typed_but_not_a_date_is_refused(
    built: Settings, tmp_path: Path
) -> None:
    with pytest.raises(GoldError, match="calendar.date_column"):
        gold(built, tmp_path, calendar={"date_column": "Year"})


def test_ac1_another_typed_date_column_can_be_chosen(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, calendar={"date_column": "SCJ_FISCAL_MONTH"})
    # that column is empty in the fixture, so only the unknown member remains
    assert query(settings, "select count(*) from dim_date") == [(1,)]


def test_ac1_silver_with_no_dates_gives_only_the_unknown_member(tmp_path: Path) -> None:
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
            "REVINT_PATHS_BRONZE": str(tmp_path / "b"),
        }
    )
    build(settings, [sale(8, None)])
    run_gold(settings)
    assert query(settings, "select date_key from dim_date") == [(-1,)]


# AC2: the fiscal fields follow calendar.fiscal_year_start_month ------


def test_ac2_at_month_one_the_fiscal_fields_equal_the_calendar_fields(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path)
    assert query(
        settings,
        "select count(*) from dim_date where date_key <> -1 "
        "and (fiscal_year <> year or fiscal_quarter <> quarter)",
    ) == [(0,)]


@pytest.mark.parametrize(
    ("start", "day", "fiscal_year", "fiscal_quarter"),
    [
        (4, date(2020, 3, 1), 2019, 4),
        (4, date(2019, 12, 30), 2019, 3),
        (7, date(2019, 12, 30), 2019, 2),
        (7, date(2020, 1, 5), 2019, 3),
        (12, date(2019, 12, 30), 2019, 1),
        (12, date(2020, 1, 5), 2019, 1),
        (12, date(2020, 3, 1), 2019, 2),
        (2, date(2020, 1, 5), 2019, 4),
    ],
)
def test_ac2_fiscal_year_and_quarter_follow_the_start_month(
    built: Settings,
    tmp_path: Path,
    start: int,
    day: date,
    fiscal_year: int,
    fiscal_quarter: int,
) -> None:
    settings = gold(built, tmp_path, calendar={"fiscal_year_start_month": start})
    got = query(
        settings, f"select fiscal_year, fiscal_quarter from dim_date where date = date '{day}'"
    )
    assert got == [(fiscal_year, fiscal_quarter)]


def test_ac2_the_fiscal_year_is_named_by_the_calendar_year_it_starts_in(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path, calendar={"fiscal_year_start_month": 4})
    got = dict(query(settings, "select date, fiscal_year from dim_date where date_key <> -1"))
    assert got[LAST] == 2019  # March 2020 is before the April start
    assert got[FIRST] == 2019


def test_ac2_fiscal_quarters_are_always_one_to_four(built: Settings, tmp_path: Path) -> None:
    for start in (1, 5, 12):
        settings = gold(built, tmp_path / str(start), calendar={"fiscal_year_start_month": start})
        low, high = query(
            settings,
            "select min(fiscal_quarter), max(fiscal_quarter) from dim_date where date_key <> -1",
        )[0]
        assert 1 <= low <= high <= 4


def test_ac2_changing_the_start_month_changes_the_fiscal_fields_only(
    built: Settings, tmp_path: Path
) -> None:
    a = gold(built, tmp_path / "a")
    b = gold(built, tmp_path / "b", calendar={"fiscal_year_start_month": 4})
    cal = "select date_key, date, week, month, quarter, year, month_start from dim_date order by 1"
    assert query(a, cal) == query(b, cal)
    fis = "select fiscal_year, fiscal_quarter from dim_date order by date_key"
    assert query(a, fis) != query(b, fis)


# AC3: date_key is unique and deterministic; the unknown member exists ------


def test_ac3_date_key_is_the_day_as_yyyymmdd(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(
        settings,
        "select count(*) from dim_date where date_key <> -1 "
        "and date_key <> cast(strftime(date, '%Y%m%d') as integer)",
    ) == [(0,)]


def test_ac3_date_key_is_unique(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(settings, "select count(*), count(distinct date_key) from dim_date") == [
        (DAYS + 1, DAYS + 1)
    ]


def test_ac3_the_unknown_member_exists_once(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    got = query(
        settings,
        "select date_key, date, week, month, quarter, year, month_start, fiscal_year, "
        "fiscal_quarter, f_after_asof from dim_date where date_key = -1",
    )
    assert got == [(-1, None, None, None, None, None, None, None, None, False)]


def test_ac3_a_rebuild_gives_identical_rows(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    first = query(settings, "select * from dim_date order by date_key")
    run_gold(settings)
    assert query(settings, "select * from dim_date order by date_key") == first


def test_ac3_the_same_data_gives_the_same_keys_in_two_warehouses(
    built: Settings, tmp_path: Path
) -> None:
    a = gold(built, tmp_path / "a")
    b = gold(built, tmp_path / "b")
    sql = "select date_key from dim_date order by date_key"
    assert query(a, sql) == query(b, sql)


# AC4: f_after_asof ------


def test_ac4_days_after_the_as_of_date_are_flagged(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    flagged = [r[0] for r in rows(settings, "date", "f_after_asof")]
    assert flagged == [LAST]
    assert settings.asof.date == date(2020, 2, 29)


def test_ac4_the_as_of_day_itself_is_not_after(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(settings, "select f_after_asof from dim_date where date = date '2020-02-29'") == [
        (False,)
    ]


def test_ac4_the_flag_follows_the_as_of_setting(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, asof={"date": date(2020, 1, 1)})
    flagged = [r[0] for r in rows(settings, "date", "f_after_asof")]
    assert flagged[0] == date(2020, 1, 2)
    assert flagged[-1] == LAST
    assert len(flagged) == (LAST - date(2020, 1, 1)).days


def test_ac4_a_fact_style_join_flags_a_line_by_its_date(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    got = query(
        settings,
        "select s._source_row, d.f_after_asof from silver_sales as s "
        'inner join dim_date as d on d.date = s."Date" order by 1',
    )
    assert got == [(8, False), (9, False), (10, True), (11, False)]


def test_ac4_a_line_with_no_date_joins_the_unknown_member(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    got = query(
        settings,
        "select s._source_row, coalesce(d.date_key, -1), coalesce(d.f_after_asof, false) "
        'from silver_sales as s left join dim_date as d on d.date = s."Date" '
        "where s._source_row in (12, 13) order by 1",
    )
    assert got == [(12, -1, False), (13, -1, False)]


# Safety ------


def test_the_gold_stage_logs_and_stores_no_cell_values(
    built: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        settings = gold(built, tmp_path)
    assert SECRET not in caplog.text
    assert SECRET not in repr(query(settings, "select * from dim_date"))


def test_the_sql_file_is_numbered_after_the_view() -> None:
    names = sorted(p.name for p in GOLD_DIR.glob("*.sql"))
    assert names.index("01_v_net_sales.sql") < names.index("02_dim_date.sql")


def test_the_gold_sql_hard_codes_no_date_column() -> None:
    text = (GOLD_DIR / "02_dim_date.sql").read_text(encoding="utf-8")
    assert '"Date"' not in text
    assert "$calendar_date_column" in text


def test_the_view_is_still_built_with_the_dimension(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(settings, "select count(*) from v_net_sales")[0][0] > 0


# AC5 ------


def test_ac5_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 5):
        assert f"def test_ac{ac}_" in text


@pytest.mark.realdata
def test_ac1_ac3_ac4_real_file_calendar(tmp_path: Path) -> None:
    """Counts only. Gold runs on a temporary warehouse built from the real bronze files."""
    real = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    if not list(real.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    from revint.silver import run_silver

    run_silver(real)
    run_gold(real)
    first, last = query(real, 'select min("Date"), max("Date") from silver_sales')[0]
    days = (last - first).days + 1
    assert query(real, "select count(*), count(distinct date_key) from dim_date") == [
        (days + 1, days + 1)
    ]
    assert query(real, "select min(date), max(date) from dim_date")[0] == (first, last)
    assert query(real, "select count(*) from dim_date where f_after_asof") == [(0,)]
    off = variant(tmp_path / "fy", real, calendar={"fiscal_year_start_month": 4})
    run_gold(off)
    assert query(
        off, "select count(*) from dim_date where date_key <> -1 and fiscal_year > year"
    ) == [(0,)]
