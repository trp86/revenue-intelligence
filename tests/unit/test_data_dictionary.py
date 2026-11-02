"""Story #86: config/definitions.yaml and the generated docs/data_dictionary.md (spec 02 section 7).

Synthetic data only. The dictionary is generated from the gold tables of a synthetic warehouse
and from the hand-written definitions; the committed file is checked against the real column
set of a synthetic build, so no customer-level value is ever involved. The real-file test is
marked `realdata` and asserts counts only.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest
import yaml
from gold_helpers import gold
from silver_helpers import bronze_row, build, query
from typer.testing import CliRunner

from revint.cli import app
from revint.config import Settings, load_settings
from revint.data_dictionary import (
    DEFINITIONS_FILE,
    DICTIONARY_FILE,
    GOLD_TABLES,
    OPPORTUNITY_TABLES,
    DictionaryError,
    build_dictionary,
    gold_columns,
    load_definitions,
    missing_definitions,
    present_tables,
    write_dictionary,
)
from revint.gold import run_gold
from revint.opportunities import run_opportunities
from revint.silver import run_silver

runner = CliRunner()
S = "SECRET-"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("dictionary")
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    rows = [
        bronze_row(
            8,
            OrderReference=f"{S}O1",
            CustomerCode=f"{S}C1",
            Customer=f"{S}name",
            SCJ_CODE_1="P1",
            Product_Decription=f"{S}product",
            Branch_Name="Magway",
            Channel_Category="GT",
            Date="2019-01-10",
            Net_Amount_2="10",
        )
    ]
    build(settings, rows)
    run_gold(settings)
    return settings


@pytest.fixture
def work(built: Settings, tmp_path: Path) -> Settings:
    # gold, then the opportunity tables (story #117): the dictionary documents both
    settings = gold(built, tmp_path)
    run_opportunities(settings)
    return settings


@pytest.fixture
def gold_only(built: Settings, tmp_path: Path) -> Settings:
    return gold(built, tmp_path)


def definitions_text() -> str:
    return DEFINITIONS_FILE.read_text(encoding="utf-8")


# AC1: config/definitions.yaml has a definition per metric and dimension, each with an id ------


def test_ac1_the_file_exists_where_the_spec_says() -> None:
    assert DEFINITIONS_FILE == ROOT / "config" / "definitions.yaml"
    assert DEFINITIONS_FILE.is_file()


def test_ac1_it_is_valid_yaml_with_a_list_of_definitions() -> None:
    data = yaml.safe_load(definitions_text())
    assert isinstance(data, dict) and isinstance(data["definitions"], list)
    assert len(data["definitions"]) > 20


def test_ac1_every_definition_has_an_id_and_a_plain_language_text() -> None:
    for entry in load_definitions():
        assert re.fullmatch(r"[a-z][a-z0-9_]*", entry.id), entry.id
        assert entry.kind in {"metric", "dimension", "flag", "key"}, entry.id
        assert len(entry.text.split()) >= 3, entry.id
        assert entry.text.strip() == entry.text and "\n" not in entry.text


def test_ac1_ids_are_unique() -> None:
    ids = [d.id for d in load_definitions()]
    assert len(ids) == len(set(ids))


def test_ac1_metrics_and_dimensions_are_both_defined() -> None:
    kinds = {d.kind for d in load_definitions()}
    assert {"metric", "dimension"} <= kinds


def test_ac1_net_sales_is_defined_once_and_says_where_it_comes_from() -> None:
    by_id = {d.id: d for d in load_definitions()}
    text = by_id["net_sales"].text.lower()
    assert by_id["net_sales"].kind == "metric"
    assert "v_net_sales" in text and "net_sales.field" in text


def test_ac1_a_definition_names_no_customer_level_value() -> None:
    for entry in load_definitions():
        assert S not in entry.text
        assert not re.search(r"\d{4,}", entry.text), entry.id  # no code, count or amount


def test_ac1_a_duplicate_id_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "defs.yaml"
    bad.write_text(
        "definitions:\n"
        "  - {id: a_b, kind: metric, text: 'One plain definition here', applies_to: ['t.c']}\n"
        "  - {id: a_b, kind: metric, text: 'Another plain definition here', applies_to: ['t.d']}\n",
        encoding="utf-8",
    )
    with pytest.raises(DictionaryError, match="a_b"):
        load_definitions(bad)


@pytest.mark.parametrize(
    "entry",
    [
        "{kind: metric, text: 'No id on this one', applies_to: ['t.c']}",
        "{id: Bad-Id, kind: metric, text: 'Bad id characters', applies_to: ['t.c']}",
        "{id: x, kind: weird, text: 'A strange kind of entry', applies_to: ['t.c']}",
        "{id: x, kind: metric, text: '', applies_to: ['t.c']}",
        "{id: x, kind: metric, text: 'No columns are named here'}",
        "{id: x, kind: metric, text: 'An extra key is refused', applies_to: ['t.c'], extra: 1}",
    ],
)
def test_ac1_an_invalid_entry_is_refused_and_named(tmp_path: Path, entry: str) -> None:
    bad = tmp_path / "defs.yaml"
    bad.write_text(f"definitions:\n  - {entry}\n", encoding="utf-8")
    with pytest.raises(DictionaryError):
        load_definitions(bad)


def test_ac1_a_missing_file_is_refused_with_its_path(tmp_path: Path) -> None:
    with pytest.raises(DictionaryError, match="nope.yaml"):
        load_definitions(tmp_path / "nope.yaml")


# AC2: docs/data_dictionary.md from table metadata with the listed fields ------


def test_ac2_one_row_per_gold_column_with_every_field(work: Settings) -> None:
    text = build_dictionary(work)
    rows = [line for line in text.splitlines() if line.startswith("| `")]
    gold = sum(len(gold_columns(work, t)) for t in GOLD_TABLES)
    expected = sum(len(gold_columns(work, t)) for t in present_tables(work))
    assert gold == 140
    assert len(rows) == expected == 247  # 140 gold and 107 opportunity columns (story #117)
    header = next(line for line in text.splitlines() if line.startswith("| Column"))
    cells = [c.strip().lower() for c in header.strip("|").split("|")]
    assert cells == ["column", "type", "definition", "source", "rule", "flags that affect it"]


def test_ac2_every_gold_table_has_a_section_with_its_grain(work: Settings) -> None:
    text = build_dictionary(work)
    for table in GOLD_TABLES:
        assert f"## {table}" in text
    assert "Grain:" in text.split("## fact_sales")[1].split("## ")[0]


def test_ac2_the_type_is_the_warehouse_type(work: Settings) -> None:
    text = build_dictionary(work)
    row = next(line for line in text.splitlines() if line.startswith("| `net_sales` |"))
    assert "DECIMAL(18,4)" in row
    assert "BOOLEAN" in next(
        line for line in text.splitlines() if line.startswith("| `f_after_asof` |")
    )


def test_ac2_the_definition_comes_from_the_definitions_file(work: Settings) -> None:
    by_id = {d.id: d for d in load_definitions()}
    text = build_dictionary(work)
    assert by_id["net_sales"].text in text


def test_ac2_net_sales_is_labelled_with_the_configured_field_and_provisional(
    work: Settings,
) -> None:
    text = build_dictionary(work)
    assert "Net_Amount_2" in text and "provisional" in text.lower()


def test_ac2_source_column_and_rule_id_are_given_where_there_is_one(work: Settings) -> None:
    text = build_dictionary(work)
    row = next(line for line in text.splitlines() if line.startswith("| `f_blank_void` |"))
    assert "S6" in row and "Void" in row
    row = next(line for line in text.splitlines() if line.startswith("| `f_stray_row` |"))
    assert "S9" in row


def test_ac2_the_flags_that_affect_a_column_are_listed(work: Settings) -> None:
    text = build_dictionary(work)
    row = next(line for line in text.splitlines() if line.startswith("| `net_sales` |"))
    assert "included" in row and "is_duplicate" in row
    row = next(line for line in text.splitlines() if line.startswith("| `penetration` |"))
    assert "f_fallback" in row


def test_ac2_the_f_bad_flags_are_defined_by_one_template_and_named_per_column(
    work: Settings,
) -> None:
    text = build_dictionary(work)
    assert len([line for line in text.splitlines() if line.startswith("| `f_bad_")]) == 28
    row = next(line for line in text.splitlines() if line.startswith("| `f_bad_Net_Amount_2` |"))
    assert "Net_Amount_2" in row and "S2" in row


def test_ac2_the_amount_columns_name_their_source_through_the_candidate_setting(
    work: Settings,
) -> None:
    text = build_dictionary(work)
    row = next(line for line in text.splitlines() if line.startswith("| `amount_Selling_Amount` |"))
    assert "Selling_Amount" in row


def test_ac2_the_dictionary_says_it_is_generated_and_how_to_regenerate() -> None:
    text = (ROOT / "docs" / "data_dictionary.md").read_text(encoding="utf-8")
    assert "Generated by" in text[:400]
    assert "revint report dictionary" in text


def test_ac2_the_committed_file_is_where_the_spec_says() -> None:
    assert DICTIONARY_FILE == ROOT / "docs" / "data_dictionary.md"


def test_ac2_the_committed_file_matches_what_the_generator_makes(work: Settings) -> None:
    committed = DICTIONARY_FILE.read_text(encoding="utf-8")
    assert committed == build_dictionary(work)


# AC3: a gold column with no entry fails a test that names it ------


def test_ac3_every_gold_column_has_a_dictionary_entry(work: Settings) -> None:
    assert missing_definitions(work) == []


def test_ac3_a_column_with_no_entry_is_named(work: Settings) -> None:
    con = __import__("duckdb").connect(str(work.paths.warehouse))
    try:
        con.execute("alter table dim_branch add column surprise_column varchar")
    finally:
        con.close()
    assert missing_definitions(work) == ["dim_branch.surprise_column"]
    with pytest.raises(DictionaryError, match="dim_branch.surprise_column"):
        build_dictionary(work)


def test_ac3_a_removed_definition_names_the_columns_that_lost_it(
    work: Settings, tmp_path: Path
) -> None:
    data = yaml.safe_load(definitions_text())
    data["definitions"] = [d for d in data["definitions"] if d["id"] != "penetration"]
    trimmed = tmp_path / "defs.yaml"
    trimmed.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert missing_definitions(work, trimmed) == ["mart_peer_category_share.penetration"]


def test_ac3_the_definitions_cover_the_gold_tables_and_nothing_stale() -> None:
    # every table.column a definition names must be a gold or an opportunity table
    import fnmatch

    tables = [*GOLD_TABLES, *OPPORTUNITY_TABLES]
    for entry in load_definitions():
        for target in entry.applies_to:
            table = target.split(".")[0]
            assert fnmatch.filter(tables, table), (entry.id, target)


def test_ac3_no_definition_points_at_a_column_that_does_not_exist(work: Settings) -> None:
    existing = {f"{t}.{c.name}" for t in present_tables(work) for c in gold_columns(work, t)}
    patterns = [
        t for d in load_definitions() for t in d.applies_to if "{" not in t and "*" not in t
    ]
    stale = sorted(set(patterns) - existing)
    assert stale == []


def test_ac3_a_gold_table_with_no_entries_at_all_is_reported_per_column(
    gold_only: Settings,
) -> None:
    empty = gold_only.paths.warehouse.parent / "empty.yaml"
    empty.write_text("definitions: []\n", encoding="utf-8")
    missing = missing_definitions(gold_only, empty)
    assert len(missing) == 140
    assert "fact_sales.net_sales" in missing


# AC4: a re-run is identical; the file holds no customer-level values ------


def test_ac4_two_runs_give_the_same_text(work: Settings) -> None:
    assert build_dictionary(work) == build_dictionary(work)


def test_ac4_the_file_written_is_identical_on_a_rerun(work: Settings, tmp_path: Path) -> None:
    target = tmp_path / "docs" / "data_dictionary.md"
    write_dictionary(work, target)
    first = target.read_bytes()
    write_dictionary(work, target)
    assert target.read_bytes() == first


def test_ac4_it_has_no_timestamp_or_machine_specific_text(work: Settings) -> None:
    text = build_dictionary(work)
    assert not re.search(r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d", text)
    assert str(work.paths.warehouse.parent) not in text
    assert "C:\\" not in text and "/Users/" not in text


def test_ac4_it_holds_no_customer_level_values(work: Settings) -> None:
    text = build_dictionary(work)
    assert S not in text
    for value in ("Magway", "P1", "Modern Trade"):
        assert f"`{value}`" not in text


def test_ac4_the_same_data_in_two_warehouses_gives_the_same_dictionary(
    built: Settings, tmp_path: Path
) -> None:
    a = gold(built, tmp_path / "a")
    b = gold(built, tmp_path / "b")
    assert build_dictionary(a) == build_dictionary(b)


def test_ac4_the_text_uses_unix_line_ends_and_ends_with_a_newline(
    work: Settings, tmp_path: Path
) -> None:
    target = tmp_path / "d.md"
    write_dictionary(work, target)
    data = target.read_bytes()
    assert b"\r\n" not in data and data.endswith(b"\n")


def test_ac4_a_failed_run_keeps_the_previous_file(work: Settings, tmp_path: Path) -> None:
    target = tmp_path / "d.md"
    write_dictionary(work, target)
    before = target.read_bytes()
    con = __import__("duckdb").connect(str(work.paths.warehouse))
    try:
        con.execute("alter table dim_branch add column surprise_column varchar")
    finally:
        con.close()
    with pytest.raises(DictionaryError):
        write_dictionary(work, target)
    assert target.read_bytes() == before


def test_ac4_it_does_not_change_the_warehouse(work: Settings) -> None:
    before = query(work, "select count(*) from fact_sales")
    tables = query(work, "select table_name from information_schema.tables order by 1")
    build_dictionary(work)
    assert query(work, "select count(*) from fact_sales") == before
    assert query(work, "select table_name from information_schema.tables order by 1") == tables


def test_ac4_logs_hold_no_values(
    work: Settings, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    with caplog.at_level(logging.DEBUG):
        write_dictionary(work, tmp_path / "d.md")
    assert S not in caplog.text


# The command ------


def use(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {
        "RAW": settings.paths.raw,
        "BRONZE": settings.paths.bronze,
        "WAREHOUSE": settings.paths.warehouse,
        "APP_DB": settings.paths.app_db,
        "REPORTS": settings.paths.reports,
    }.items():
        monkeypatch.setenv(f"REVINT_PATHS_{key}", str(value))


def test_cli_report_dictionary_writes_the_file(
    work: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    use(work, monkeypatch)
    target = tmp_path / "out.md"
    result = runner.invoke(app, ["report", "dictionary", "--output", str(target)])
    assert result.exit_code == 0, result.output
    assert target.read_text(encoding="utf-8") == build_dictionary(work)
    assert "247 columns in 23 tables" in result.output


def test_cli_without_a_warehouse_says_to_build_gold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "none.duckdb")})
    use(settings, monkeypatch)
    result = runner.invoke(app, ["report", "dictionary", "--output", str(tmp_path / "o.md")])
    assert result.exit_code == 4
    assert "gold" in result.output.lower()


def test_cli_with_a_missing_definition_exits_four_and_names_it(
    work: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    con = __import__("duckdb").connect(str(work.paths.warehouse))
    try:
        con.execute("alter table dim_branch add column surprise_column varchar")
    finally:
        con.close()
    use(work, monkeypatch)
    result = runner.invoke(app, ["report", "dictionary", "--output", str(tmp_path / "o.md")])
    assert result.exit_code == 4
    assert "dim_branch.surprise_column" in result.output


def test_cli_without_output_writes_the_committed_docs_file(
    work: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "docs" / "data_dictionary.md"
    monkeypatch.setattr("revint.data_dictionary.DICTIONARY_FILE", target)
    use(work, monkeypatch)
    result = runner.invoke(app, ["report", "dictionary"])
    assert result.exit_code == 0, result.output
    assert target.read_text(encoding="utf-8") == build_dictionary(work)


# AC5 ------


def test_ac5_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 5):
        assert f"def test_ac{ac}_" in text


@pytest.mark.realdata
def test_ac2_ac3_real_file_dictionary(tmp_path: Path) -> None:
    """Counts only. Gold runs on a temporary warehouse built from the real bronze files."""
    real = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    if not list(real.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    run_silver(real)
    run_gold(real)
    run_opportunities(real)
    assert missing_definitions(real) == []
    assert build_dictionary(real) == DICTIONARY_FILE.read_text(encoding="utf-8")
    assert sum(len(gold_columns(real, t)) for t in GOLD_TABLES) == 140
    assert len(present_tables(real)) == len(GOLD_TABLES) + len(OPPORTUNITY_TABLES)


# Story #117: the opportunity tables are in the dictionary ------


def test_story_117_every_opportunity_column_has_a_definition(work: Settings) -> None:
    assert set(OPPORTUNITY_TABLES) <= set(present_tables(work))
    assert missing_definitions(work) == []


def test_story_117_the_dictionary_has_a_section_per_opportunity_table(work: Settings) -> None:
    text = build_dictionary(work)
    for table in OPPORTUNITY_TABLES:
        assert f"\n## {table}\n" in text, table


def test_story_117_a_gold_only_warehouse_documents_gold_only(gold_only: Settings) -> None:
    assert list(present_tables(gold_only)) == list(GOLD_TABLES)
    assert "## opp_" not in build_dictionary(gold_only)


def test_story_117_an_opportunity_column_with_no_entry_is_named(
    work: Settings, tmp_path: Path
) -> None:
    data = yaml.safe_load(definitions_text())
    data["definitions"] = [d for d in data["definitions"] if d["id"] != "opp_rank"]
    trimmed = tmp_path / "defs.yaml"
    trimmed.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert missing_definitions(work, trimmed) == ["opp_opportunities.rank"]
