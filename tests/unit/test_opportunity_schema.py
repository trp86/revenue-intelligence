"""Story #107: the opportunity schema, opp_id, algo_version and the run summary (spec 03 section 2).

There are no engines yet, so the tests run the real opportunity stage with one extra SQL file
between the schema and the summary. That file inserts synthetic engine rows the way an engine
will, which is how the summary, the ids and the checks are exercised. Synthetic data only.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

import pytest
from silver_helpers import bronze_row, build, query

from revint.config import Settings, load_settings
from revint.gold import run_gold
from revint.opportunities import (
    ENGINES,
    OPPORTUNITIES_DIR,
    OPPORTUNITY_COLUMNS,
    OpportunitiesError,
    opp_id,
    run_opportunities,
    with_asof,
)
from revint.pipeline import run_stage

ASOF = date(2020, 2, 29)


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("oppschema")
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    build(
        settings,
        [
            bronze_row(
                8, OrderReference="O1", CustomerCode="C1", Date="2019-01-10", Net_Amount_2="5"
            ),
            bronze_row(
                9, OrderReference="O2", CustomerCode="C2", Date="2019-02-10", Net_Amount_2="7"
            ),
        ],
    )
    run_gold(settings)
    return settings


@pytest.fixture
def work(built: Settings, tmp_path: Path) -> Settings:
    shutil.copy(built.paths.warehouse, tmp_path / "warehouse.duckdb")
    return load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "warehouse.duckdb")})


SCHEMA_FILES = ("01_asof_inputs.sql", "02_schema.sql", "90_run_summary.sql")


def schema_files() -> list[Path]:
    """The stage without the engine files: these tests write their own engine rows."""
    return [OPPORTUNITIES_DIR / name for name in SCHEMA_FILES]


def run_schema(settings: Settings, tmp_path: Path) -> None:
    """Run the stage with no engine, through the module."""
    stage = tmp_path / "schema_only"
    stage.mkdir(parents=True, exist_ok=True)
    for path in schema_files():
        shutil.copy(path, stage / path.name)
    run_opportunities(settings, stage_dir=stage)


def with_engine_rows(settings: Settings, tmp_path: Path, sql: str) -> None:
    """Run the real stage with `sql` inserted between the schema and the run summary."""
    stage = tmp_path / "stage"
    stage.mkdir(parents=True)
    for path in schema_files():
        shutil.copy(path, stage / path.name)
    (stage / "50_test_engine_rows.sql").write_text(sql, encoding="utf-8")
    run_stage(stage, settings)


def dormancy_row(customer: int, category: str | None = None) -> str:
    cat = "null" if category is None else f"'{category}'"
    return (
        "insert into opp_dormancy (opp_id, type, customer_key, category, as_of_date, "
        "algo_version, gap, reason_codes) "
        f"select opp_id('dormancy', {customer}, {cat}, cast($asof_date as date)), 'dormancy', "
        f"{customer}, {cat}, cast($asof_date as date), "
        "(select algo_version from opp_engines where type = 'dormancy'), 10, ['quiet'];\n"
    )


def evaluation(
    customer: int, outcome: str, engine: str = "dormancy", category: str | None = None
) -> str:
    cat = "null" if category is None else f"'{category}'"
    return (
        "insert into opp_evaluations (type, as_of_date, customer_key, category, outcome) "
        f"values ('{engine}', cast($asof_date as date), {customer}, {cat}, '{outcome}');\n"
    )


def columns_of(settings: Settings, table: str) -> list[str]:
    return [
        c
        for (c,) in query(
            settings,
            "select column_name from information_schema.columns where table_name = ? "
            "order by ordinal_position",
            table,
        )
    ]


# AC1: opp_opportunities has the common columns ------


def test_ac1_opp_opportunities_has_the_common_columns_in_order(
    work: Settings, tmp_path: Path
) -> None:
    run_schema(work, tmp_path)
    assert columns_of(work, "opp_opportunities") == list(OPPORTUNITY_COLUMNS)
    assert OPPORTUNITY_COLUMNS == (
        "opp_id",
        "type",
        "customer_key",
        "category",
        "as_of_date",
        "algo_version",
        "score",
        "priority",
        "confidence",
        "value_low",
        "value_high",
        "value_level",
        "value_method",
        "rank",
        "reason_codes",
    )


def test_ac1_the_column_types_fit_their_use(work: Settings, tmp_path: Path) -> None:
    run_schema(work, tmp_path)
    types = dict(
        query(
            work,
            "select column_name, data_type from information_schema.columns "
            "where table_name = 'opp_opportunities'",
        )
    )
    assert types["category"] == "VARCHAR"  # text: there is no category key in E2
    assert types["as_of_date"] == "DATE"
    assert types["reason_codes"] == "VARCHAR[]"
    assert types["customer_key"] == "BIGINT"
    assert types["score"].startswith("DECIMAL") or types["score"] == "DOUBLE"


def test_ac1_category_may_be_null(work: Settings, tmp_path: Path) -> None:
    with_engine_rows(work, tmp_path, dormancy_row(1) + evaluation(1, "triggered"))
    assert query(work, "select category from opp_dormancy") == [(None,)]


def test_ac1_each_engine_has_its_own_table_with_the_identity_columns(
    work: Settings, tmp_path: Path
) -> None:
    run_schema(work, tmp_path)
    for engine in ENGINES:
        columns = columns_of(work, f"opp_{engine}")
        assert columns[:6] == [
            "opp_id",
            "type",
            "customer_key",
            "category",
            "as_of_date",
            "algo_version",
        ], engine
        assert "gap" in columns and "reason_codes" in columns, engine


def test_ac1_the_tables_start_empty(work: Settings, tmp_path: Path) -> None:
    run_schema(work, tmp_path)
    for table in ("opp_opportunities", "opp_evaluations", *(f"opp_{e}" for e in ENGINES)):
        assert query(work, f"select count(*) from {table}") == [(0,)], table


# AC2: opp_id is a hash of type, customer, category and as-of date ------


def test_ac2_opp_id_is_the_same_on_every_run(work: Settings, tmp_path: Path) -> None:
    with_engine_rows(
        work, tmp_path / "a", dormancy_row(1, "Cat") + evaluation(1, "triggered", category="Cat")
    )
    first = query(work, "select opp_id from opp_dormancy")
    with_engine_rows(
        work, tmp_path / "b", dormancy_row(1, "Cat") + evaluation(1, "triggered", category="Cat")
    )
    assert query(work, "select opp_id from opp_dormancy") == first


def test_ac2_the_sql_and_the_python_id_agree(work: Settings, tmp_path: Path) -> None:
    with_engine_rows(
        work, tmp_path, dormancy_row(42, "Cat") + evaluation(42, "triggered", category="Cat")
    )
    expected = opp_id("dormancy", 42, "Cat", ASOF)
    assert query(work, "select opp_id from opp_dormancy") == [(expected,)]


def test_ac2_the_python_id_is_md5_of_a_json_list(work: Settings) -> None:
    expected = hashlib.md5(
        json.dumps(["dormancy", "42", "Cat", "2020-02-29"], separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert opp_id("dormancy", 42, "Cat", ASOF) == expected


@pytest.mark.parametrize(
    "other",
    [
        ("recovery", 42, "Cat", ASOF),
        ("dormancy", 43, "Cat", ASOF),
        ("dormancy", 42, "Dog", ASOF),
        ("dormancy", 42, None, ASOF),
        ("dormancy", 42, "Cat", date(2020, 1, 31)),
    ],
)
def test_ac2_any_of_the_four_values_changes_the_id(other: tuple) -> None:
    assert opp_id(*other) != opp_id("dormancy", 42, "Cat", ASOF)


def test_ac2_no_category_and_an_empty_category_are_different(work: Settings) -> None:
    assert opp_id("dormancy", 1, None, ASOF) != opp_id("dormancy", 1, "", ASOF)


def test_ac2_a_separator_inside_a_value_cannot_make_two_ids_collide() -> None:
    assert opp_id("dormancy", 1, "a|b", ASOF) != opp_id("dormancy|1", 1, "b", ASOF)


def test_ac2_ids_are_unique_within_an_engine_table(work: Settings, tmp_path: Path) -> None:
    sql = dormancy_row(1) + dormancy_row(1) + evaluation(1, "triggered")
    # opp_id is the primary key of every engine table
    with pytest.raises(OpportunitiesError, match="PRIMARY KEY"):
        with_engine_rows_via_api(work, tmp_path, sql)


def with_engine_rows_via_api(settings: Settings, tmp_path: Path, sql: str) -> None:
    """As with_engine_rows, but through the module, so stage errors become OpportunitiesError."""
    stage = tmp_path / "stage"
    stage.mkdir(parents=True)
    for path in schema_files():
        shutil.copy(path, stage / path.name)
    (stage / "50_test_engine_rows.sql").write_text(sql, encoding="utf-8")
    run_opportunities(settings, stage_dir=stage)


# AC3: opp_run_summary counts per engine, and suppressions by reason ------


def test_ac3_the_summary_has_one_row_per_engine(work: Settings, tmp_path: Path) -> None:
    run_schema(work, tmp_path)
    rows = query(
        work,
        "select type, n_evaluated, n_triggered, n_suppressed from opp_run_summary order by 1",
    )
    assert rows == [(engine, 0, 0, 0) for engine in sorted(ENGINES)]


def test_ac3_evaluated_triggered_and_suppressed_are_counted(work: Settings, tmp_path: Path) -> None:
    sql = (
        dormancy_row(1)
        + evaluation(1, "triggered")
        + evaluation(2, "insufficient_history")
        + evaluation(3, "insufficient_history")
        + evaluation(4, "not_quiet")
    )
    with_engine_rows(work, tmp_path, sql)
    got = query(
        work,
        "select n_evaluated, n_triggered, n_suppressed, suppressed_by_reason "
        "from opp_run_summary where type = 'dormancy'",
    )
    assert got == [(4, 1, 3, {"insufficient_history": 2, "not_quiet": 1})]


def test_ac3_an_engine_with_no_suppression_has_an_empty_map(work: Settings, tmp_path: Path) -> None:
    with_engine_rows(work, tmp_path, dormancy_row(1) + evaluation(1, "triggered"))
    assert query(
        work, "select suppressed_by_reason from opp_run_summary where type = 'dormancy'"
    ) == [({},)]


def test_ac3_the_summary_carries_the_as_of_date_and_the_algo_version(
    work: Settings, tmp_path: Path
) -> None:
    run_schema(with_asof(work, date(2019, 6, 30)), tmp_path)
    rows = query(work, "select type, as_of_date, algo_version from opp_run_summary order by 1")
    assert rows == [(e, date(2019, 6, 30), f"{e}-1") for e in sorted(ENGINES)]


def test_ac3_triggered_must_match_the_engine_table(work: Settings, tmp_path: Path) -> None:
    # an engine that records a trigger but writes no opportunity row fails the stage
    with pytest.raises(OpportunitiesError, match="dormancy"):
        with_engine_rows_via_api(work, tmp_path, evaluation(1, "triggered"))


def test_ac3_an_opportunity_without_an_evaluation_fails_the_stage(
    work: Settings, tmp_path: Path
) -> None:
    with pytest.raises(OpportunitiesError, match="dormancy"):
        with_engine_rows_via_api(work, tmp_path, dormancy_row(1))


def test_ac3_an_unknown_engine_in_the_evaluations_fails_the_stage(
    work: Settings, tmp_path: Path
) -> None:
    with pytest.raises(OpportunitiesError, match="assortment"):
        with_engine_rows_via_api(work, tmp_path, evaluation(1, "triggered", engine="assortment"))


def test_ac3_a_customer_is_evaluated_once_per_engine_and_category(
    work: Settings, tmp_path: Path
) -> None:
    sql = evaluation(2, "not_quiet") + evaluation(2, "insufficient_history")
    with pytest.raises(OpportunitiesError, match="opp_evaluations"):
        with_engine_rows_via_api(work, tmp_path, sql)


def test_ac3_the_stage_holds_counts_only(work: Settings, tmp_path: Path) -> None:
    run_schema(work, tmp_path)
    assert columns_of(work, "opp_run_summary") == [
        "type",
        "as_of_date",
        "algo_version",
        "n_evaluated",
        "n_triggered",
        "n_suppressed",
        "suppressed_by_reason",
    ]


# AC4: algo_version is a constant per engine, stored on every row ------


def test_ac4_each_engine_has_one_algo_version(work: Settings, tmp_path: Path) -> None:
    run_schema(work, tmp_path)
    assert query(work, "select type, algo_version from opp_engines order by 1") == [
        (e, f"{e}-1") for e in sorted(ENGINES)
    ]


def test_ac4_algo_version_is_required_on_every_engine_row(work: Settings, tmp_path: Path) -> None:
    sql = (
        "insert into opp_dormancy (opp_id, type, customer_key, category, as_of_date, gap) "
        "values ('x', 'dormancy', 1, null, cast($asof_date as date), 1);\n"
        + evaluation(1, "triggered")
    )
    with pytest.raises(OpportunitiesError):
        with_engine_rows_via_api(work, tmp_path, sql)


def test_ac4_a_row_with_another_engines_version_fails_the_stage(
    work: Settings, tmp_path: Path
) -> None:
    sql = dormancy_row(1).replace(
        "(select algo_version from opp_engines where type = 'dormancy')", "'dormancy-0'"
    ) + evaluation(1, "triggered")
    with pytest.raises(OpportunitiesError, match="algo_version"):
        with_engine_rows_via_api(work, tmp_path, sql)


def test_ac4_the_engine_list_is_the_four_spec_engines() -> None:
    assert ENGINES == ("dormancy", "recovery", "whitespace", "crosssell")


# AC5: a rerun rebuilds the tables in full ------


def test_ac5_a_rerun_empties_the_tables_left_by_an_earlier_run(
    work: Settings, tmp_path: Path
) -> None:
    with_engine_rows(work, tmp_path, dormancy_row(1) + evaluation(1, "triggered"))
    assert query(work, "select count(*) from opp_dormancy") == [(1,)]
    run_schema(work, tmp_path)
    for table in ("opp_dormancy", "opp_evaluations", "opp_opportunities"):
        assert query(work, f"select count(*) from {table}") == [(0,)], table
    assert query(work, "select sum(n_evaluated) from opp_run_summary") == [(0,)]


def test_ac5_two_runs_give_one_summary_row_per_engine(work: Settings, tmp_path: Path) -> None:
    run_schema(work, tmp_path)
    run_schema(work, tmp_path)
    assert query(work, "select count(*) from opp_run_summary") == [(len(ENGINES),)]


def test_ac5_a_failed_run_keeps_the_previous_tables(work: Settings, tmp_path: Path) -> None:
    with_engine_rows(work, tmp_path / "ok", dormancy_row(1) + evaluation(1, "triggered"))
    with pytest.raises(OpportunitiesError):
        with_engine_rows_via_api(work, tmp_path / "bad", evaluation(9, "triggered"))
    assert query(work, "select count(*) from opp_dormancy") == [(1,)]


# Files, the module and the as-of inputs ------


def test_the_files_run_inputs_then_schema_and_the_summary_last() -> None:
    names = sorted(p.name for p in OPPORTUNITIES_DIR.glob("*.sql"))
    assert names[:2] == ["01_asof_inputs.sql", "02_schema.sql"]
    assert names[-1] == "90_run_summary.sql"


def test_run_opportunities_needs_the_gold_layer(tmp_path: Path) -> None:
    settings = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "none.duckdb")})
    with pytest.raises(OpportunitiesError, match="revint build gold"):
        run_opportunities(settings)


def test_the_as_of_inputs_are_still_built(work: Settings, tmp_path: Path) -> None:
    run_schema(work, tmp_path)
    assert query(work, "select count(*) from asof_orders")[0][0] == 2


# AC6 ------


def test_ac6_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 6):
        assert f"def test_ac{ac}_" in text
