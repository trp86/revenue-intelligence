"""Story #105: profile the opportunity engine thresholds (spec 03 section 10).

Synthetic data only; customer codes and categories carry a SECRET- marker, and amounts are odd
values, to prove no customer value reaches the output. The real-file test is marked `realdata`
and asserts counts only.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import date
from pathlib import Path

import pytest
from gold_helpers import variant
from silver_helpers import bronze_row, build

from revint.config import Settings, load_settings
from revint.gold import run_gold
from revint.opportunities import with_asof
from revint.threshold_profile import (
    MIN_CUSTOMERS_FOR_PERCENTILES,
    READINGS,
    ProfileError,
    ThresholdProfile,
    format_profile,
    main,
    profile_thresholds,
)

ROOT = Path(__file__).resolve().parents[2]
S = "SECRET-"
ASOF = date(2020, 2, 29)


def sale(row: int, customer: str, day: str, net: str, category: str = "A") -> dict:
    return bronze_row(
        row,
        OrderReference=f"O{row}",
        CustomerCode=f"{S}{customer}",
        Customer=f"{S}name",
        SCJ_CODE_1=f"P{category}",
        Internal_Category=f"{S}{category}",
        Branch_Name="Magway",
        Channel_Category="GT",
        Date=day,
        Net_Amount_2=net,
        **{"Quantity(PCS)": "1"},
    )


def rows() -> list[dict]:
    out: list[dict] = []
    n = 8
    # R1: 3 orders in Dec 2018 - Feb 2019 (prior window), one small order in the current window
    # (Dec 2019 - Feb 2020): declined by far more than 20 percent.
    for day in ("2018-12-05", "2019-01-05", "2019-02-05"):
        out.append(sale(n, "R1", day, "1001.17"))
        n += 1
    out.append(sale(n, "R1", "2020-02-10", "13.31"))
    n += 1
    # R2: 3 prior orders and the same in the current window: no decline.
    for day in ("2018-12-06", "2019-01-06", "2019-02-06", "2019-12-06", "2020-01-06", "2020-02-06"):
        out.append(sale(n, "R2", day, "500.03"))
        n += 1
    # D1: monthly orders Jan - Jun 2019 and nothing after: dormant (interval ~30, quiet ~240).
    for month in range(1, 7):
        out.append(sale(n, "D1", f"2019-{month:02d}-15", "77.77"))
        n += 1
    # H1: two orders only: insufficient history for dormancy.
    out.append(sale(n, "H1", "2019-03-01", "9.99"))
    out.append(sale(n + 1, "H1", "2019-04-01", "9.99"))
    n += 2
    # B buyers: C1..C3 buy A and B; C4 buys A only (whitespace and cross-sell candidate).
    for i in range(1, 4):
        out.append(sale(n, f"C{i}", "2020-01-20", "3.33", "A"))
        out.append(sale(n + 1, f"C{i}", "2020-01-21", "4.44", "B"))
        n += 2
    out.append(sale(n, "C4", "2020-01-20", "3.33", "A"))
    return out


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("thresholds")
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    build(settings, rows())
    run_gold(settings)
    return settings


def configured(built: Settings, tmp_path: Path, **sections: dict) -> Settings:
    """The committed settings with test thresholds, on a private copy of the warehouse."""
    shutil.copy(built.paths.warehouse, tmp_path / "warehouse.duckdb")
    source = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "warehouse.duckdb")})
    base = {
        "recovery": {"min_prior_sales": 0},
        "peer_groups": {"min_size": 2},
        "crosssell": {"min_support": 2, "min_confidence": 0.3, "min_lift": 1.0},
    }
    for name, keys in sections.items():
        base[name] = {**base.get(name, {}), **keys}
    return with_asof(variant(tmp_path, source, **base), ASOF)


@pytest.fixture
def profile(built: Settings, tmp_path: Path) -> ThresholdProfile:
    return profile_thresholds(configured(built, tmp_path))


# AC1: counts per engine at the configured as-of date ------


def test_ac1_the_profile_is_for_the_configured_as_of_date(profile: ThresholdProfile) -> None:
    assert profile.as_of_date == ASOF


def test_ac1_recovery_counts(profile: ThresholdProfile) -> None:
    r = profile.recovery
    assert r.evaluated == 3  # R1, R2 and D1 ordered in the prior window (Dec 2018 - Feb 2019)
    assert r.pass_min_decline_pct == 2  # R1, and D1 (no current sales)
    assert r.pass_min_prior_orders == 2  # R1 and R2; D1 had 2 prior orders
    assert r.flagged == 1  # R1
    assert r.flagged_not_dormant == 1


def test_ac1_recovery_min_prior_sales_is_applied(built: Settings, tmp_path: Path) -> None:
    got = profile_thresholds(configured(built, tmp_path, recovery={"min_prior_sales": 5000}))
    assert (got.recovery.pass_min_prior_sales, got.recovery.flagged) == (0, 0)


def test_ac1_dormancy_counts(profile: ThresholdProfile) -> None:
    d = profile.dormancy
    assert d.evaluated == 8  # R1, R2, D1, H1, C1..C4
    assert d.insufficient_history == 5  # H1 and C1..C4 have fewer than 4 orders
    assert d.flagged == 1  # D1


def test_ac1_whitespace_counts(profile: ThresholdProfile) -> None:
    # all 8 customers are one peer group; 3 of 8 buy B (penetration 0.375 < 0.5): no flag
    w = profile.whitespace
    assert (w.customers, w.small_peer_group, w.evaluated) == (8, 0, 8)
    assert (w.eligible_pairs, w.flagged_pairs) == (8, 0)  # only A is eligible, all bought it


def test_ac1_whitespace_penetration_is_applied(built: Settings, tmp_path: Path) -> None:
    got = profile_thresholds(
        configured(built, tmp_path, whitespace={"min_peer_penetration": 0.3})
    ).whitespace
    # B is now eligible: R1, R2, D1, H1 and C4 did not buy it in the last 12 months
    assert (got.flagged_pairs, got.flagged_customers) == (5, 5)


def test_ac1_a_small_peer_group_is_not_evaluated(built: Settings, tmp_path: Path) -> None:
    got = profile_thresholds(configured(built, tmp_path, peer_groups={"min_size": 50})).whitespace
    assert (got.small_peer_group, got.evaluated, got.flagged_pairs) == (8, 0, 0)


def test_ac1_crosssell_counts(profile: ThresholdProfile) -> None:
    c = profile.crosssell
    assert c.categories == 2
    assert c.evaluated_pairs == 2  # A -> B and B -> A
    # all 8 bought A in the lookback; R1, R2, D1, H1 and C4 never bought B
    assert (c.buying_customers, c.flagged_pairs) == (8, 2)
    assert (c.candidates, c.candidate_customers) == (5, 5)


def test_ac1_crosssell_support_is_applied(built: Settings, tmp_path: Path) -> None:
    got = profile_thresholds(configured(built, tmp_path, crosssell={"min_support": 4}))
    assert (got.crosssell.pass_min_support, got.crosssell.candidates) == (0, 0)


def test_ac1_the_thresholds_used_are_reported(profile: ThresholdProfile) -> None:
    assert profile.thresholds["recovery"]["min_decline_pct"] == 20
    assert profile.thresholds["whitespace"]["peer_groups_min_size"] == 2
    assert set(profile.thresholds) == {
        "recovery",
        "dormancy",
        "whitespace",
        "crosssell",
        "opportunities",
    }


def test_ac1_percentiles_need_enough_customers(profile: ThresholdProfile) -> None:
    assert profile.recovery.evaluated < MIN_CUSTOMERS_FOR_PERCENTILES
    assert profile.recovery.prior_sales_percentiles is None
    assert profile.recovery.flagged_at_prior_sales_percentile is None


def test_ac1_the_readings_are_printed(profile: ThresholdProfile) -> None:
    text = format_profile(profile)
    for reading in READINGS:
        assert reading in text


def test_ac1_the_warehouse_is_not_written(built: Settings, tmp_path: Path) -> None:
    settings = configured(built, tmp_path)
    before = settings.paths.warehouse.read_bytes()
    profile_thresholds(settings)
    assert settings.paths.warehouse.read_bytes() == before


def test_ac1_the_profile_needs_a_warehouse(tmp_path: Path) -> None:
    settings = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "none.duckdb")})
    with pytest.raises(ProfileError, match="revint build gold"):
        profile_thresholds(settings)


def test_ac1_main_prints_json(
    built: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    shutil.copy(built.paths.warehouse, tmp_path / "w.duckdb")
    monkeypatch.setenv("REVINT_PATHS_WAREHOUSE", str(tmp_path / "w.duckdb"))
    assert main(["--json", "--as-of", "2020-02-29"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["as_of_date"] == "2020-02-29"
    assert set(data) >= {"recovery", "dormancy", "whitespace", "crosssell", "readings"}


def test_ac1_main_reports_a_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVINT_PATHS_WAREHOUSE", str(tmp_path / "none.duckdb"))
    assert main([]) == 4


# AC2: the chosen values are in the config and the findings in the spec ------


def test_ac2_the_values_are_set_and_marked_provisional() -> None:
    settings = load_settings(env={})
    assert settings.recovery.min_prior_sales == 25000
    assert settings.opportunities.top_n_per_type == 250
    config = (ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
    for key in ("min_prior_sales:", "top_n_per_type:"):
        line = next(x for x in config.splitlines() if x.strip().startswith(key))
        assert "provisional" in line and "#105" in line, key


def test_ac2_the_findings_are_in_spec_section_10() -> None:
    spec = (ROOT / "docs" / "specs" / "03-opportunity-engines.md").read_text(encoding="utf-8")
    section = spec[spec.index("## 10. OPEN QUESTIONS") :]
    assert "Threshold profile findings (story #105; provisional" in section
    assert "revint.threshold_profile" in section


# AC3: counts and percentiles only ------


def test_ac3_no_customer_value_reaches_the_output(
    built: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        got = profile_thresholds(configured(built, tmp_path))
    out = format_profile(got) + json.dumps(got.as_dict()) + caplog.text
    assert S not in out
    for amount in ("1001.17", "13.31", "500.03", "77.77", "9.99", "3.33", "4.44"):
        assert amount not in out, amount


def test_ac3_the_output_holds_only_counts_thresholds_and_percentiles(
    profile: ThresholdProfile,
) -> None:
    data = profile.as_dict()
    for engine in ("recovery", "dormancy", "whitespace", "crosssell"):
        for key, value in data[engine].items():
            assert value is None or isinstance(value, (int, dict)), (engine, key)


# AC4: the real file ------


@pytest.mark.realdata
def test_ac1_ac3_real_file_profile() -> None:
    """Counts only, on a copy of the built warehouse (the profile never writes it)."""
    real = load_settings()
    if not real.paths.warehouse.is_file():
        pytest.skip("warehouse not built: run `uv run revint build all` first")
    got = profile_thresholds(real)
    assert got.recovery.evaluated > MIN_CUSTOMERS_FOR_PERCENTILES
    assert got.recovery.prior_sales_percentiles is not None
    assert got.recovery.flagged <= got.recovery.evaluated
    assert got.dormancy.flagged <= got.dormancy.evaluated - got.dormancy.insufficient_history
    assert got.whitespace.flagged_customers <= got.whitespace.evaluated
    assert got.crosssell.flagged_pairs <= got.crosssell.evaluated_pairs
