"""Story #85: the gold reconciliation checks (spec 02 section 10).

Synthetic data only; customer codes carry a SECRET- marker to prove none reaches output, logs or
`recon_results`. Silver is built once per module, each test copies the warehouse, runs gold and
the checks on its own copy, and tampers with the gold tables to prove that each check fails. The
real-file test is marked `realdata` and asserts counts and sums only.
"""

from __future__ import annotations

import logging
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pytest
from gold_helpers import gold, variant
from silver_helpers import bronze_row, build, query
from typer.testing import CliRunner

from revint.cli import app
from revint.config import Settings, load_settings
from revint.gold import GOLD_DIR, run_gold
from revint.ingest.bronze import run_bronze
from revint.recon import (
    EXIT_CHECK_FAILED,
    GOLD_CHECKS_DIR,
    ReconError,
    execute_recon,
    gold_is_built,
    run_gold_checks,
    run_recon,
)
from revint.silver import AMOUNT_COLUMNS, run_silver

runner = CliRunner()
S = "SECRET-"
AMOUNTS = [f"amount_{c}" for c in AMOUNT_COLUMNS]


def sale(
    row: int,
    customer: str | None,
    product: str,
    branch: str | None,
    day: str | None,
    net: str,
    order: int | None = None,
) -> dict[str, str | None]:
    return bronze_row(
        row,
        OrderReference=f"O{order or row}",
        CustomerCode=customer,
        Customer=f"{S}name" if customer else None,
        SCJ_CODE_1=product,
        Internal_Category={"P1": f"{S}A", "P2": f"{S}B"}.get(product),
        Branch_Name=branch,
        Channel_Category="GT",
        Date=day,
        Net_Amount_2=net,
        Selling_Amount=str(int(net) * 2),
        TAX_AMOUNT="1",
        **{"Quantity(PCS)": "1"},
    )


# Rows 8 to 17: a copy (row 13 of row 12, excluded), the stray row (17), a blank customer, a
# blank branch, an undated line and a return.
ROWS = [
    sale(8, f"{S}C1", "P1", "Magway", "2019-01-10", "10"),
    sale(9, f"{S}C1", "P1", "Magway", "2019-02-10", "5"),
    sale(10, f"{S}C1", "P2", "Magway", "2019-04-10", "-1"),
    sale(11, f"{S}C2", "P2", "PYAY", "2019-02-15", "7"),
    sale(12, f"{S}C2", "P1", "PYAY", "2019-03-01", "3"),
    sale(13, f"{S}C2", "P1", "PYAY", "2019-03-01", "3", order=12),
    sale(14, None, "P1", "Magway", "2019-03-05", "4"),
    sale(15, f"{S}C3", "P2", None, "2019-03-06", "6"),
    sale(16, f"{S}C3", "P1", "Magway", None, "2"),
    bronze_row(17, Change_to_Ctn="1"),
]


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("goldchecks")
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    build(settings, ROWS)
    return settings


def checked(built: Settings, tmp_path: Path, **sections: dict[str, Any]) -> Settings:
    """A private warehouse copy with gold built and the gold checks run."""
    settings = gold(built, tmp_path, **sections)
    run_gold_checks(settings)
    return settings


def results(settings: Settings) -> dict[tuple[str, str], tuple]:
    rows = query(
        settings,
        "select check_id, subject, status, expected, actual, difference from recon_results",
    )
    return {(r[0], r[1]): r[2:] for r in rows}


def statuses(settings: Settings, check_id: str) -> dict[str, str]:
    return {s: v[0] for (c, s), v in results(settings).items() if c == check_id}


def execute(settings: Settings, sql: str) -> None:
    con = duckdb.connect(str(settings.paths.warehouse))
    try:
        con.execute(sql)
    finally:
        con.close()


# AC1: R7 gold form, under both settings, for every candidate amount column ------


@pytest.mark.parametrize("exclude", [True, False])
def test_ac1_r7_gold_passes_for_every_candidate_column_under_both_settings(
    built: Settings, tmp_path: Path, exclude: bool
) -> None:
    settings = checked(built, tmp_path, duplicates={"exclude_from_net_sales": exclude})
    got = {s: v for s, v in statuses(settings, "R7").items() if s.startswith("gold:")}
    assert set(got) == {f"gold:{c}" for c in AMOUNT_COLUMNS}
    assert set(got.values()) == {"pass"}


@pytest.mark.parametrize("exclude", [True, False])
def test_ac1_the_identity_is_exact_on_the_fixture(
    built: Settings, tmp_path: Path, exclude: bool
) -> None:
    settings = checked(built, tmp_path, duplicates={"exclude_from_net_sales": exclude})
    expected, actual, difference = results(settings)[("R7", "gold:Net_Amount_2")][1:]
    assert (expected, actual, difference) == (Decimal("39.0000"), Decimal("39.0000"), 0)


def test_ac1_with_true_the_left_out_rows_are_every_excluded_row(
    built: Settings, tmp_path: Path
) -> None:
    settings = checked(built, tmp_path, duplicates={"exclude_from_net_sales": True})
    fact = query(settings, "select sum(amount_Net_Amount_2) from fact_sales")[0][0]
    left_out = query(settings, "select sum(net_amount_2) from silver_excluded_rows")[0][0]
    silver = query(settings, "select sum(Net_Amount_2) from silver_sales")[0][0]
    assert fact + left_out == silver
    assert left_out == Decimal("3.0000")  # the copy; the stray row has no amount


def test_ac1_with_false_only_the_stray_row_is_left_out(built: Settings, tmp_path: Path) -> None:
    settings = checked(built, tmp_path, duplicates={"exclude_from_net_sales": False})
    fact = query(settings, "select sum(amount_Net_Amount_2) from fact_sales")[0][0]
    silver = query(settings, "select sum(Net_Amount_2) from silver_sales")[0][0]
    assert fact == silver  # the stray row has no amount


def test_ac1_the_tolerance_comes_from_config(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    execute(
        settings,
        "update fact_sales set amount_Net_Amount_2 = amount_Net_Amount_2 + 0.005 "
        "where sales_line_id = 8",
    )
    run_gold_checks(settings)
    assert statuses(settings, "R7")["gold:Net_Amount_2"] == "pass"
    strict = variant(tmp_path / "strict", settings, recon={"tolerance_amount": 0.001})
    run_gold_checks(strict)
    assert statuses(strict, "R7")["gold:Net_Amount_2"] == "fail"


def test_ac1_the_candidate_list_follows_the_setting(built: Settings, tmp_path: Path) -> None:
    settings = checked(
        built,
        tmp_path,
        net_sales={"candidate_columns": ["Net_Amount_2", "TAX_AMOUNT"]},
    )
    assert {s for s in statuses(settings, "R7") if s.startswith("gold:")} == {
        "gold:Net_Amount_2",
        "gold:TAX_AMOUNT",
    }


# AC2: each mart equals the fact; the fact equals the chosen silver column ------


@pytest.mark.parametrize("exclude", [True, False])
@pytest.mark.parametrize("zero_fill", [True, False])
def test_ac2_every_mart_equals_the_fact(
    built: Settings, tmp_path: Path, exclude: bool, zero_fill: bool
) -> None:
    settings = checked(
        built,
        tmp_path,
        duplicates={"exclude_from_net_sales": exclude},
        marts={"zero_fill": zero_fill},
    )
    got = statuses(settings, "G2")
    assert set(got) == {
        "mart_customer_month",
        "mart_customer_month:n_lines",
        "mart_customer_category_month",
        "mart_customer_category_month:n_lines",
        "mart_branch_month",
        "mart_branch_month:n_lines",
        "mart_peer_category_share",
        "mart_peer_category_share:n_lines",
        "mart_customer_profile:customers",
    }
    assert set(got.values()) == {"pass"}


def test_ac2_the_peer_mart_is_compared_with_real_customers_only(
    built: Settings, tmp_path: Path
) -> None:
    settings = checked(built, tmp_path)
    expected, actual, _ = results(settings)[("G2", "mart_peer_category_share")][1:]
    all_fact = query(settings, "select sum(net_sales) from fact_sales where included")[0][0]
    assert actual == expected
    assert expected == all_fact - Decimal("4.0000")  # the blank-customer line is not a peer


@pytest.mark.parametrize("exclude", [True, False])
def test_ac2_the_fact_equals_the_chosen_silver_column(
    built: Settings, tmp_path: Path, exclude: bool
) -> None:
    settings = checked(built, tmp_path, duplicates={"exclude_from_net_sales": exclude})
    assert results(settings)[("G1", "fact_net_sales")][0] == "pass"


def test_ac2_g1_names_the_column_it_compared(built: Settings, tmp_path: Path) -> None:
    settings = checked(built, tmp_path)
    assert query(settings, "select detail from recon_results where check_id = 'G1'") == [
        ("Net_Amount_2",)
    ]


def test_ac2_a_line_with_included_false_stays_in_both_sums(built: Settings, tmp_path: Path) -> None:
    settings = checked(built, tmp_path, net_sales={"exclude_flags": ["f_negative_value"]})
    assert results(settings)[("G1", "fact_net_sales")][0] == "pass"
    assert statuses(settings, "G2")["mart_customer_month"] == "pass"


# AC3: a grep test over sql/20_gold ------


def test_ac3_only_the_v_net_sales_file_references_a_source_amount_column() -> None:
    offenders = []
    for path in sorted(GOLD_DIR.glob("*.sql")):
        raw = path.read_text(encoding="utf-8")
        code = " ".join(line.split("--")[0] for line in raw.splitlines())
        if path.name != "01_v_net_sales.sql" and any(c in code for c in AMOUNT_COLUMNS):
            offenders.append(path.name)
    assert offenders == []


def test_ac3_the_view_file_is_the_one_that_exists_for_the_definition() -> None:
    names = [p.name for p in GOLD_DIR.glob("*.sql")]
    assert "01_v_net_sales.sql" in names


def test_ac3_the_grep_covers_comments_too_apart_from_the_header_words() -> None:
    # a source column named in a comment of another file is allowed, in code it is not
    for path in GOLD_DIR.glob("*.sql"):
        if path.name == "01_v_net_sales.sql":
            continue
        code = " ".join(line.split("--")[0] for line in path.read_text("utf-8").splitlines())
        assert "Net_Amount_2" not in code and "Selling_Amount" not in code


def test_ac3_the_grep_detects_a_planted_reference(tmp_path: Path) -> None:
    planted = tmp_path / "99_bad.sql"
    planted.write_text("select Net_Amount_2 from silver_sales;", encoding="utf-8")
    code = planted.read_text(encoding="utf-8")
    assert any(c in code for c in AMOUNT_COLUMNS)


# AC4: unique keys and no orphan foreign keys ------


def test_ac4_every_key_is_unique(built: Settings, tmp_path: Path) -> None:
    got = statuses(checked(built, tmp_path), "G3")
    assert set(got) == {
        "dim_date.date_key",
        "dim_customer.customer_key",
        "dim_product.product_key",
        "dim_branch.branch_key",
        "fact_sales.sales_line_id",
    }
    assert set(got.values()) == {"pass"}


def test_ac4_there_are_no_orphan_foreign_keys(built: Settings, tmp_path: Path) -> None:
    got = statuses(checked(built, tmp_path), "G4")
    assert set(got) == {
        "fact_sales.date_key",
        "fact_sales.customer_key",
        "fact_sales.product_key",
        "fact_sales.branch_key",
        "mart_customer_month.customer_key",
        "mart_customer_category_month.customer_key",
        "mart_customer_profile.customer_key",
        "mart_branch_month.branch_key",
    }
    assert set(got.values()) == {"pass"}


@pytest.mark.parametrize("exclude", [True, False])
def test_ac4_the_fact_row_count_matches_silver_under_both_settings(
    built: Settings, tmp_path: Path, exclude: bool
) -> None:
    settings = checked(built, tmp_path, duplicates={"exclude_from_net_sales": exclude})
    status, expected, actual, difference = results(settings)[("G5", "fact_rows")]
    assert status == "pass"
    assert (expected, actual, difference) == (
        Decimal(10 - (2 if exclude else 1)),
        Decimal(10 - (2 if exclude else 1)),
        0,
    )


# AC5: switching net_sales.field changes the mart totals with no code edit ------


def test_ac5_switching_the_field_changes_every_mart_total(built: Settings, tmp_path: Path) -> None:
    a = checked(built, tmp_path / "a")
    b = checked(built, tmp_path / "b", net_sales={"field": "Selling_Amount"})
    for mart, column in (
        ("mart_customer_month", "net_sales"),
        ("mart_customer_category_month", "net_sales"),
        ("mart_branch_month", "net_sales"),
        ("mart_peer_category_share", "total_net_sales"),
    ):
        sql = f"select sum({column}) from {mart}"
        assert query(b, sql)[0][0] == 2 * query(a, sql)[0][0], mart


def test_ac5_the_checks_still_pass_after_the_switch(built: Settings, tmp_path: Path) -> None:
    settings = checked(built, tmp_path, net_sales={"field": "Selling_Amount"})
    assert {v[0] for v in results(settings).values()} <= {"pass", "info"}
    assert query(settings, "select detail from recon_results where check_id = 'G1'") == [
        ("Selling_Amount",)
    ]


# AC6: a tampered fixture fails each check; the results are in recon_results ------

JAN_MART = "where month_start = date '2019-01-01'"
LINE_8 = "where sales_line_id = 8"
BRANCH_MART = "update mart_branch_month"

# (check id, subject, tampering SQL): each makes exactly that check fail.
TAMPERS = [
    (
        "R7",
        "gold:Net_Amount_2",
        f"update fact_sales set amount_Net_Amount_2 = amount_Net_Amount_2 + 1 {LINE_8}",
    ),
    ("G1", "fact_net_sales", f"update fact_sales set net_sales = net_sales + 1 {LINE_8}"),
    (
        "G2",
        "mart_customer_month",
        f"update mart_customer_month set net_sales = net_sales + 1 {JAN_MART}",
    ),
    (
        "G2",
        "mart_customer_month:n_lines",
        f"update mart_customer_month set n_lines = n_lines + 1 {JAN_MART}",
    ),
    (
        "G2",
        "mart_customer_category_month",
        f"update mart_customer_category_month set net_sales = net_sales + 1 {JAN_MART}",
    ),
    ("G2", "mart_branch_month", f"{BRANCH_MART} set net_sales = net_sales + 1 {JAN_MART}"),
    (
        "G2",
        "mart_peer_category_share",
        "update mart_peer_category_share set total_net_sales = total_net_sales + 1",
    ),
    (
        "G2",
        "mart_customer_profile:customers",
        "delete from mart_customer_profile where customer_key = -1",
    ),
    (
        "G3",
        "dim_customer.customer_key",
        "insert into dim_customer select * from dim_customer where customer_key = -1",
    ),
    ("G3", "fact_sales.sales_line_id", f"insert into fact_sales select * from fact_sales {LINE_8}"),
    ("G4", "fact_sales.customer_key", f"update fact_sales set customer_key = 123456789 {LINE_8}"),
    ("G4", "fact_sales.product_key", f"update fact_sales set product_key = 123456789 {LINE_8}"),
    ("G4", "fact_sales.date_key", f"update fact_sales set date_key = 20990101 {LINE_8}"),
    ("G4", "fact_sales.branch_key", f"update fact_sales set branch_key = 123456789 {LINE_8}"),
    ("G4", "mart_branch_month.branch_key", f"{BRANCH_MART} set branch_key = 123456789"),
    ("G5", "fact_rows", f"delete from fact_sales {LINE_8}"),
]


@pytest.mark.parametrize(
    ("check_id", "subject", "tamper"), TAMPERS, ids=[f"{c}-{s}" for c, s, _ in TAMPERS]
)
def test_ac6_a_tampered_fixture_fails_that_check(
    built: Settings, tmp_path: Path, check_id: str, subject: str, tamper: str
) -> None:
    settings = gold(built, tmp_path)
    execute(settings, tamper)
    outcome = run_gold_checks(settings)
    assert statuses(settings, check_id)[subject] == "fail"
    assert not outcome.passed


def test_ac6_a_tampered_check_leaves_the_untouched_ones_passing(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path)
    execute(settings, "update fact_sales set net_sales = net_sales + 1 where sales_line_id = 8")
    run_gold_checks(settings)
    assert statuses(settings, "G3") and set(statuses(settings, "G3").values()) == {"pass"}
    assert statuses(settings, "G1")["fact_net_sales"] == "fail"


def test_ac6_the_results_are_written_to_recon_results_with_the_documented_columns(
    built: Settings, tmp_path: Path
) -> None:
    settings = checked(built, tmp_path)
    assert {c for (c, _) in results(settings)} >= {"R7", "G1", "G2", "G3", "G4", "G5"}
    assert query(
        settings,
        "select count(*) from recon_results where status not in ('pass', 'fail', 'info') "
        "or checked_at is null or description is null",
    ) == [(0,)]


def test_ac6_a_rerun_replaces_the_gold_rows_and_keeps_the_others(
    built: Settings, tmp_path: Path
) -> None:
    settings = checked(built, tmp_path)
    before = query(settings, "select count(*) from recon_results")[0][0]
    run_gold_checks(settings)
    run_gold_checks(settings)
    assert query(settings, "select count(*) from recon_results")[0][0] == before


def test_ac6_the_checks_live_in_sql_checks_gold() -> None:
    assert GOLD_CHECKS_DIR == GOLD_CHECKS_DIR.parent / "gold"
    assert GOLD_CHECKS_DIR.parent.name == "checks" and GOLD_CHECKS_DIR.parent.parent.name == "sql"
    names = sorted(p.name for p in GOLD_CHECKS_DIR.glob("*.sql"))
    assert names == ["01_amount_totals.sql", "02_marts.sql", "03_rows_and_keys.sql"]


def test_ac6_the_gold_checks_are_not_part_of_the_silver_checks_folder_run() -> None:
    top = sorted(p.name for p in GOLD_CHECKS_DIR.parent.glob("*.sql"))
    assert all(not name.startswith("gold") for name in top)


def test_ac6_gold_checks_need_the_gold_layer(built: Settings, tmp_path: Path) -> None:
    shutil.copy(built.paths.warehouse, tmp_path / "warehouse.duckdb")
    settings = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "warehouse.duckdb")})
    assert gold_is_built(settings) is False
    with pytest.raises(ReconError, match="gold"):
        run_gold_checks(settings)


def test_ac6_a_failed_gold_check_stage_changes_nothing(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    run_gold_checks(settings)
    before = query(settings, "select count(*) from recon_results")
    execute(settings, "drop table mart_branch_month")
    with pytest.raises(ReconError):
        run_gold_checks(settings)
    assert query(settings, "select count(*) from recon_results") == before


# `revint check` ------


def make_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Workbook -> bronze -> silver -> gold in a temporary project, wired into the CLI."""
    import xlsxwriter
    from silver_helpers import EXPECTED

    raw = tmp_path / "raw"
    raw.mkdir()
    book = xlsxwriter.Workbook(str(raw / "sales.xlsx"))
    sheet = book.add_worksheet("RAW SCJ SALES")
    for col, name in enumerate(EXPECTED):
        sheet.write(3, col, name)
    for offset, (customer, day, net) in enumerate(
        [(f"{S}C1", "2019-01-10", 10), (f"{S}C2", "2019-02-10", 7)]
    ):
        for name, value in {
            "CustomerCode": customer,
            "Customer": f"{S}name",
            "SCJ_CODE_1": "P1",
            "Branch_Name": "Magway",
            "Channel_Category": "GT",
            "Date": day,
            "Net_Amount_2": net,
            "Selling_Amount": net * 2,
            "Quantity(PCS)": 1,
        }.items():
            sheet.write(4 + offset, EXPECTED.index(name), value)
    book.close()
    env = {
        "REVINT_PATHS_RAW": str(raw),
        "REVINT_PATHS_BRONZE": str(tmp_path / "bronze"),
        "REVINT_PATHS_WAREHOUSE": str(tmp_path / "warehouse.duckdb"),
        "REVINT_PATHS_APP_DB": str(tmp_path / "app.duckdb"),
        "REVINT_PATHS_REPORTS": str(tmp_path / "reports"),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    settings = load_settings(env=env)
    run_bronze(settings)
    run_silver(settings)
    return settings


def test_cli_check_without_gold_runs_only_the_silver_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_project(tmp_path, monkeypatch)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0, result.output
    assert "G1" not in result.output and "R1" in result.output


def test_cli_check_with_gold_runs_the_gold_checks_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_project(tmp_path, monkeypatch)
    run_gold(settings)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0, result.output
    for check in ("R1", "R7 gold:Net_Amount_2", "G1", "G2", "G3", "G4", "G5"):
        assert check in result.output


def test_ac6_cli_check_exits_non_zero_on_a_failing_gold_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_project(tmp_path, monkeypatch)
    run_gold(settings)
    execute(settings, "update fact_sales set net_sales = net_sales + 1 where sales_line_id = 5")
    result = runner.invoke(app, ["check"])
    assert result.exit_code == EXIT_CHECK_FAILED
    assert "G1 fact_net_sales: fail" in result.output


def test_cli_check_output_and_results_hold_no_customer_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = make_project(tmp_path, monkeypatch)
    run_gold(settings)
    with caplog.at_level(logging.DEBUG):
        assert execute_recon(settings) == 0
    out = capsys.readouterr()
    assert S not in out.out + out.err + caplog.text
    assert S not in repr(query(settings, "select * from recon_results"))


def test_run_recon_after_gold_includes_the_gold_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_project(tmp_path, monkeypatch)
    run_gold(settings)
    outcome = run_recon(settings)
    assert {r.check_id for r in outcome.results} >= {"R1", "R2", "R3", "R4", "R7", "R8", "G1"}
    assert outcome.passed


# AC7 ------


def test_ac7_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 7):
        assert f"def test_ac{ac}_" in text


@pytest.mark.realdata
@pytest.mark.parametrize("exclude", [True, False])
def test_ac1_to_ac6_real_file_gold_checks(tmp_path: Path, exclude: bool) -> None:
    """Counts and sums only. Gold and its checks run on a temporary warehouse from real bronze."""
    real = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    if not list(real.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    run_silver(real)
    settings = variant(tmp_path / "cfg", real, duplicates={"exclude_from_net_sales": exclude})
    run_gold(settings)
    outcome = run_gold_checks(settings)
    gold_results = [r for r in outcome.results if r.check_id in {"G1", "G2", "G3", "G4", "G5"}]
    gold_results += [
        r for r in outcome.results if r.check_id == "R7" and r.subject.startswith("gold:")
    ]
    assert len(gold_results) == 1 + 9 + 5 + 8 + 1 + len(real.net_sales.candidate_columns)
    assert {r.status for r in gold_results} == {"pass"}
    fact_rows = query(settings, "select count(*) from fact_sales")[0][0]
    assert fact_rows == 662_128 - (557 if exclude else 1)
