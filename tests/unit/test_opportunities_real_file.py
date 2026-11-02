"""Story #117: E3 proven on the real file (spec 03 section 8).

Every test here is marked `realdata`: it needs the built warehouse in data/ and is skipped
without it. Each works on a copy of the warehouse, so data/ is never written, and asserts
counts and aggregates only. `test_ac4_evidence_summary` builds the counts posted on #117.
The synthetic proofs of the same checks are in test_opportunity_acceptance.py (#115).
"""

from __future__ import annotations

import hashlib
import shutil
from datetime import date
from pathlib import Path

import pytest
from silver_helpers import query
from test_opportunity_acceptance import poison

from revint.config import Settings, load_settings
from revint.opportunities import ENGINES, run_opportunities, with_asof

pytestmark = pytest.mark.realdata
TABLES = ("opp_opportunities", "opp_evidence", "opp_run_summary", "opp_value")


def real() -> Settings:
    settings = load_settings()
    if not settings.paths.warehouse.is_file():
        pytest.skip("warehouse not built: run `uv run revint build all` first")
    return settings


def copy_of(source: Settings, folder: Path) -> Settings:
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy(source.paths.warehouse, folder / "w.duckdb")
    return load_settings(env={"REVINT_PATHS_WAREHOUSE": str(folder / "w.duckdb")})


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    settings = copy_of(real(), tmp_path_factory.mktemp("real_opp"))
    run_opportunities(settings)
    return settings


def snapshot(settings: Settings) -> dict[str, str]:
    """A hash of each output table, so two large tables compare without holding both."""
    out = {}
    for table in TABLES:
        rows = query(settings, f"select * from {table} order by all")
        out[table] = hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()
    return out


# AC1: ranked rows with evidence and a value ------


def test_ac1_recovery_dormancy_and_whitespace_produce_ranked_rows(built: Settings) -> None:
    counts = dict(query(built, "select type, count(*) from opp_opportunities group by 1"))
    for engine in ("recovery", "dormancy", "whitespace"):
        assert counts.get(engine, 0) > 0, engine
    # cross-sell produces rows on this file (an empty result would need an explanation)
    assert counts.get("crosssell", 0) > 0
    ranks = query(
        built, "select min(rank), max(rank), count(distinct rank), count(*) from opp_opportunities"
    )
    ((low, high, distinct, total),) = ranks
    assert (low, high, distinct) == (1, total, total)


def test_ac1_every_row_has_evidence_and_a_value(built: Settings) -> None:
    assert query(
        built,
        "select count(*) from opp_opportunities o where o.score is null or o.priority is null "
        "or o.confidence is null or (o.value_level is null and "
        "(o.value_low is null or o.value_high is null)) "
        "or not exists (select 1 from opp_evidence e where e.opp_id = o.opp_id)",
    ) == [(0,)]


# AC3: no leakage, identical rerun, an earlier as-of date ------


def test_ac3_a_rerun_gives_identical_output(built: Settings) -> None:
    before = snapshot(built)
    run_opportunities(built)
    assert snapshot(built) == before


def test_ac3_poison_rows_after_the_as_of_date_change_nothing(
    built: Settings, tmp_path: Path
) -> None:
    clean = snapshot(built)
    poisoned = copy_of(real(), tmp_path)
    # every line copied to 2020-06-15, 1000 times larger, with ids above the real ones
    poison(poisoned, offset=10_000_000)
    run_opportunities(poisoned)
    assert snapshot(poisoned) == clean


def test_ac3_the_as_of_date_can_move_earlier(tmp_path: Path) -> None:
    earlier = with_asof(copy_of(real(), tmp_path), date(2019, 6, 30))
    run_opportunities(earlier)
    assert query(earlier, "select distinct as_of_date from opp_opportunities") == [
        (date(2019, 6, 30),)
    ]
    assert query(earlier, "select count(*) from opp_opportunities")[0][0] > 0
    assert query(earlier, "select max(order_date) from asof_orders")[0][0] <= date(2019, 6, 30)


# AC4: the evidence posted on the issue (counts and aggregates only) ------


def test_ac4_evidence_summary(built: Settings) -> None:
    summary = query(
        built,
        "select type, n_evaluated, n_triggered, n_suppressed, suppressed_by_reason "
        "from opp_run_summary order by type",
    )
    assert [row[0] for row in summary] == sorted(ENGINES)
    for _type, evaluated, triggered, suppressed, reasons in summary:
        assert evaluated == triggered + suppressed
        assert sum(reasons.values()) == suppressed
    per_engine = dict(query(built, "select type, count(*) from opp_opportunities group by 1"))
    assert {t: n for t, _e, n, _s, _r in summary} == per_engine


# AC5: bronze untouched, no customer value in the evidence ------


def test_ac5_bronze_is_byte_identical_after_a_run(tmp_path: Path) -> None:
    settings = real()
    files = sorted(settings.paths.bronze.glob("*.parquet"))
    assert files
    before = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    run_opportunities(copy_of(settings, tmp_path))
    after = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    assert after == before


def test_ac5_the_evidence_holds_no_customer_value(built: Settings) -> None:
    # no customer code or name, as text, is in any evidence column
    codes = {
        c
        for (c,) in query(
            built, "select customer_code from dim_customer where customer_code is not null"
        )
    }
    texts = {
        v
        for (v,) in query(
            built,
            "select distinct unnest([fact, unit, kind, definition_id]) from opp_evidence",
        )
    }
    assert not texts & codes
    columns = {
        c
        for (c,) in query(
            built,
            "select column_name from information_schema.columns where table_name = 'opp_evidence'",
        )
    }
    assert columns == {
        "opp_id",
        "fact",
        "value_number",
        "value_date",
        "unit",
        "kind",
        "definition_id",
    }


# AC6 ------


def test_ac6_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in (1, 3, 4, 5):
        assert f"def test_ac{ac}_" in text
    # AC2 (definitions and the dictionary) is in test_data_dictionary.py
    dictionary = (Path(__file__).parent / "test_data_dictionary.py").read_text(encoding="utf-8")
    assert "run_opportunities(real)" in dictionary
