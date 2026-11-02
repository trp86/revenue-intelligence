"""Story #112: value ranges of the opportunities (spec 03 section 5).

Synthetic data only. The whitespace fixture is reused: it triggers in one engine with known
gaps. A row whose gap cannot be defended cannot come from the engines (every gap they write is
above zero), so those tests add one through an extra stage file, the way an engine would.
"""

from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from gold_helpers import variant
from silver_helpers import query
from test_whitespace import ASOF, CAT, built  # noqa: F401  (module fixture)

from revint.config import Settings, load_settings
from revint.opportunities import OPPORTUNITIES_DIR, run_opportunities, with_asof


def run(
    built: Settings,  # noqa: F811
    tmp_path: Path,
    extra_sql: str | None = None,
    **sections: dict,
) -> Settings:
    tmp_path.mkdir(parents=True, exist_ok=True)
    shutil.copy(built.paths.warehouse, tmp_path / "warehouse.duckdb")
    source = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "warehouse.duckdb")})
    settings = with_asof(variant(tmp_path, source, peer_groups={"min_size": 3}, **sections), ASOF)
    stage = OPPORTUNITIES_DIR
    if extra_sql is not None:
        stage = tmp_path / "stage"
        stage.mkdir()
        for path in OPPORTUNITIES_DIR.glob("*.sql"):
            shutil.copy(path, stage / path.name)
        # runs after the engines (06_crosssell.sql) and before 07_value.sql
        (stage / "06z_test_rows.sql").write_text(extra_sql, encoding="utf-8")
    run_opportunities(settings, stage_dir=stage)
    return settings


def undefended(gap: str) -> str:
    """A recovery row for customer 1 with this gap, and its trigger."""
    return (
        "insert into opp_recovery (opp_id, type, customer_key, category, as_of_date, "
        "algo_version, gap, reason_codes) values ('t1', 'recovery', 1, null, "
        f"cast($asof_date as date), 'recovery-1', {gap}, []);\n"
        "delete from opp_evaluations where type = 'recovery' and customer_key = 1;\n"
        "insert into opp_evaluations values ('recovery', cast($asof_date as date), 1, null, "
        "'triggered');\n"
    )


def values(settings: Settings, where: str = "true") -> list[tuple]:
    return query(
        settings,
        "select type, gap, value_low, value_high, value_level, value_method from opp_value "
        f"where {where} order by type, gap",
    )


@pytest.fixture
def result(built: Settings, tmp_path: Path) -> Settings:  # noqa: F811
    return run(built, tmp_path)


# AC1: the range is the factors times the gap ------


def test_ac1_the_range_is_the_factors_times_the_gap(result: Settings) -> None:
    rows = values(result)
    assert rows  # the whitespace fixture triggers
    for _type, gap, low, high, _level, _method in rows:
        assert low == (Decimal("0.25") * gap).quantize(Decimal("0.0001"))
        assert high == (Decimal("0.75") * gap).quantize(Decimal("0.0001"))


def test_ac1_every_opportunity_has_a_value_row(result: Settings) -> None:
    engines = query(
        result,
        "select count(*) from (select opp_id from opp_dormancy union all select opp_id from "
        "opp_recovery union all select opp_id from opp_whitespace union all select opp_id "
        "from opp_crosssell)",
    )
    assert query(result, "select count(*) from opp_value") == engines


def test_ac1_a_known_gap(result: Settings) -> None:
    # M5 for B in the whitespace fixture: gap 25
    rows = values(result, "gap = 25")
    assert [(r[2], r[3]) for r in rows] == [(Decimal("6.2500"), Decimal("18.7500"))]


# AC2: value_method states how ------


def test_ac2_value_method_states_the_factors_and_the_gap(result: Settings) -> None:
    for row in values(result):
        method = row[5]
        assert method.startswith("Estimate: 0.25 to 0.75 x the gap")
        assert "median net sales in the category per buying peer" in method


# AC3: an undefended gap gets a level and no range ------


@pytest.mark.parametrize("gap", ["null", "0", "-5"])
def test_ac3_an_undefended_gap_has_a_level_and_no_range(
    built: Settings,  # noqa: F811
    tmp_path: Path,
    gap: str,
) -> None:
    got = run(built, tmp_path, undefended(gap))
    ((low, high, level, method, defensible),) = query(
        got,
        "select value_low, value_high, value_level, value_method, f_defensible_gap "
        "from opp_value where opp_id = 't1'",
    )
    assert (low, high, level, defensible) == (None, None, "Low", False)
    assert method.startswith("No range:")


def test_ac3_levels_are_percentiles_of_the_gap_within_type(result: Settings) -> None:
    levels = {r[1]: r[4] for r in values(result)}
    # the whitespace gaps are ranked low to high; the top third is High, the bottom third Low
    ordered = [levels[g] for g in sorted(levels)]
    assert ordered[0] == "Low" and ordered[-1] == "High"
    assert set(ordered) <= {"High", "Medium", "Low"}


# AC4: a changed factor changes the range ------


def test_ac4_a_changed_factor_changes_the_range(built: Settings, tmp_path: Path) -> None:  # noqa: F811
    got = run(built, tmp_path, value={"low_factor": 0.1, "high_factor": 0.9})
    rows = values(got, "gap = 25")
    assert [(r[2], r[3]) for r in rows] == [(Decimal("2.5000"), Decimal("22.5000"))]
    assert rows[0][5].startswith("Estimate: 0.1 to 0.9 x the gap")


# AC5: never both missing ------


def test_ac5_every_row_has_a_range_or_a_level(built: Settings, tmp_path: Path) -> None:  # noqa: F811
    got = run(built, tmp_path, undefended("null"))
    missing = query(
        got,
        "select count(*) from opp_value where value_level is null "
        "and (value_low is null or value_high is null)",
    )
    assert missing == [(0,)]
    assert query(got, "select count(*) from opp_value where value_level is null") == [(0,)]


def test_ac5_a_defended_gap_always_has_a_range(result: Settings) -> None:
    assert query(
        result,
        "select count(*) from opp_value where f_defensible_gap "
        "and (value_low is null or value_high is null)",
    ) == [(0,)]


# AC6 and the real file ------


def test_ac6_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 6):
        assert f"def test_ac{ac}_" in text


@pytest.mark.realdata
def test_ac1_ac5_real_file_value(tmp_path: Path) -> None:
    """Counts only, on a copy of the built warehouse."""
    real = load_settings()
    if not real.paths.warehouse.is_file():
        pytest.skip("warehouse not built: run `uv run revint build all` first")
    shutil.copy(real.paths.warehouse, tmp_path / "w.duckdb")
    copy = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    run_opportunities(copy)
    assert query(copy, "select count(*) from opp_value where value_level is null") == [(0,)]
    assert query(
        copy, "select count(*) from opp_value where f_defensible_gap and value_low is null"
    ) == [(0,)]
    assert query(copy, "select count(distinct type) from opp_value") == [(4,)]
    assert CAT  # the fixture import is used
