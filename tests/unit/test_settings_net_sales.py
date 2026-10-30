"""Stories #28 and #51: the `net_sales` section of config/settings.yaml.

Net sales is source column 46 (Excel AT, raw header `Net Amount`), final name
`Net_Amount_2` (decision on issue #31, provisional, client to confirm).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from revint.config import ConfigError, config_hash, load_settings
from revint.silver import AMOUNT_COLUMNS

ROOT = Path(__file__).resolve().parents[2]

SIX = [
    "Selling_Amount",
    "NET_AMOUNT_1",
    "AMOUNT_AF_DIS",
    "Net_Amount_2",
    "Net_AMOUNT_3",
    "TAX_AMOUNT",
]
QUANTITY = "Quantity(PCS)"
KNOWN = [*SIX, QUANTITY, "Other"]  # a small expected_columns list for the cross-checks


def known(**changes: object) -> dict[str, object]:
    """Settings extras with a known expected_columns list and the given net_sales keys."""
    return {"ingest": {"expected_columns": KNOWN}, "net_sales": changes}


# AC1: the committed config names column 46 ------------------------------------------------


def test_ac1_committed_config_uses_column_46_by_its_final_name() -> None:
    settings = load_settings(env={})
    assert settings.net_sales.field == "Net_Amount_2"
    assert settings.net_sales.field == settings.ingest.expected_columns[45]


def test_ac1_defaults_apply_when_the_section_is_absent(load_with) -> None:
    net_sales = load_with().net_sales
    assert net_sales.field == "Net_Amount_2"
    assert net_sales.candidate_columns == SIX
    assert net_sales.quantity_field == QUANTITY


def test_ac1_field_can_be_changed_in_the_file_to_another_candidate(load_with) -> None:
    assert load_with({"net_sales": {"field": "Net_AMOUNT_3"}}).net_sales.field == "Net_AMOUNT_3"


# AC2: a field outside the known column names fails, naming the key -------------------------


def test_ac2_unknown_key_fails_and_names_it(load_with) -> None:
    with pytest.raises(ConfigError, match=r"net_sales\.fields"):
        load_with({"net_sales": {"fields": "Net_Amount_2"}})


@pytest.mark.parametrize("value", ["", None])
def test_ac2_empty_field_fails_and_names_the_key(load_with, value) -> None:
    with pytest.raises(ConfigError, match=r"net_sales\.field"):
        load_with({"net_sales": {"field": value}})


def test_ac2_field_not_in_expected_columns_fails_and_names_the_key(load_with) -> None:
    without_field = [c for c in KNOWN if c != "Net_Amount_2"]
    extra = {"ingest": {"expected_columns": without_field}, "net_sales": {}}
    with pytest.raises(ConfigError, match=r"net_sales\.field.*ingest\.expected_columns"):
        load_with(extra)


def test_ac2_a_name_that_is_in_no_list_fails(load_with) -> None:
    with pytest.raises(ConfigError, match=r"net_sales\.field"):
        load_with(known(field="Net_Amount_9"))


def test_ac2_the_check_is_skipped_while_expected_columns_is_empty(load_with) -> None:
    # Before profiling there is no list to check against; the candidate rule still applies.
    assert load_with({"net_sales": {"field": "Net_Amount_2"}}).net_sales.field == "Net_Amount_2"
    with pytest.raises(ConfigError, match=r"net_sales\.field"):
        load_with({"net_sales": {"field": "Anything_Else"}})


def test_ac2_the_message_names_the_value_and_never_a_row_value(load_with) -> None:
    with pytest.raises(ConfigError) as info:
        load_with(known(field="Net_Amount_9"))
    assert "Net_Amount_9" in str(info.value)
    assert "\n" not in str(info.value)


# AC3: the old placeholder is gone ------------------------------------------------------------


def test_ac3_the_old_value_is_rejected_as_a_field(load_with) -> None:
    with pytest.raises(ConfigError, match=r"net_sales\.field"):
        load_with({"net_sales": {"field": "Net AMOUNT"}})
    with pytest.raises(ConfigError, match=r"net_sales\.field"):
        load_with(known(field="Net AMOUNT"))


@pytest.mark.parametrize("folder", ["src", "config", "sql"])
def test_ac3_no_code_config_or_sql_still_uses_the_old_value(folder: str) -> None:
    # "Net AMOUNT" is also the raw header text of source column 48; that spelling lives only
    # in tests that build header fixtures, never in what the build reads.
    offenders = [
        str(path.relative_to(ROOT))
        for path in (ROOT / folder).rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".yaml", ".yml", ".sql"}
        and "Net AMOUNT" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_ac3_the_net_sales_parameter_for_sql_is_the_new_name() -> None:
    from revint.pipeline import settings_parameters

    params = settings_parameters(load_settings(env={}))
    assert params["net_sales_field"] == "Net_Amount_2"
    assert params["net_sales_quantity_field"] == QUANTITY
    assert params["net_sales_candidate_columns"] == SIX


# AC4: the decision is recorded ----------------------------------------------------------------


def test_ac4_decisions_states_the_choice_the_reason_and_that_the_client_may_change_it() -> None:
    text = (ROOT / "docs" / "decisions.md").read_text(encoding="utf-8")
    section = text.split("## 3. Open business questions")[1].split("## 4.")[0]
    entry = " ".join(section.split("- Net sales field")[1].split("\n- ")[0].split())
    assert "Net_Amount_2" in entry
    assert "column 46" in entry
    assert "back margin" in entry.lower()
    assert "client" in entry.lower()
    assert "provisional" in entry.lower()
    assert "`Net AMOUNT`" not in entry, "the old placeholder is not the answer"


def test_ac4_the_gold_spec_no_longer_names_the_old_default() -> None:
    gold = (ROOT / "docs" / "specs" / "02-gold-layer.md").read_text(encoding="utf-8")
    overview = (ROOT / "docs" / "specs" / "00-overview.md").read_text(encoding="utf-8")
    assert "`Net AMOUNT`" not in gold
    assert "default Net AMOUNT" not in overview
    assert "Net_Amount_2" in gold and "Net_Amount_2" in overview


# AC5: the six candidate columns ---------------------------------------------------------------


def test_ac5_committed_config_lists_the_six_candidates_in_the_expected_columns() -> None:
    settings = load_settings(env={})
    assert settings.net_sales.candidate_columns == SIX
    assert set(SIX) <= set(settings.ingest.expected_columns)
    assert settings.net_sales.field in settings.net_sales.candidate_columns


def test_ac5_a_field_outside_the_candidates_fails_even_if_it_is_a_known_column(load_with) -> None:
    with pytest.raises(ConfigError, match=r"net_sales\.field.*net_sales\.candidate_columns"):
        load_with(known(field="Other"))


def test_ac5_a_candidate_missing_from_expected_columns_fails_and_names_the_key(load_with) -> None:
    with pytest.raises(ConfigError, match=r"net_sales\.candidate_columns.*Nowhere_Col"):
        load_with(known(candidate_columns=[*SIX, "Nowhere_Col"]))


def test_ac5_candidates_may_be_narrowed(load_with) -> None:
    settings = load_with(known(candidate_columns=["Net_Amount_2", "Net_AMOUNT_3"]))
    assert settings.net_sales.candidate_columns == ["Net_Amount_2", "Net_AMOUNT_3"]


def test_ac5_narrowing_the_candidates_below_the_field_fails(load_with) -> None:
    with pytest.raises(ConfigError, match=r"net_sales\.field"):
        load_with(known(candidate_columns=["Net_AMOUNT_3"]))


def test_ac5_an_empty_candidate_list_fails_and_names_the_key(load_with) -> None:
    with pytest.raises(ConfigError, match=r"net_sales\.candidate_columns"):
        load_with({"net_sales": {"candidate_columns": []}})


def test_ac5_a_repeated_candidate_fails_and_names_the_key(load_with) -> None:
    with pytest.raises(ConfigError, match=r"net_sales\.candidate_columns.*Net_Amount_2"):
        load_with({"net_sales": {"candidate_columns": [*SIX, "Net_Amount_2"]}})


def test_ac5_the_silver_amount_columns_are_the_configured_candidates() -> None:
    assert tuple(load_settings(env={}).net_sales.candidate_columns) == AMOUNT_COLUMNS


# AC6: the quantity column ---------------------------------------------------------------------


def test_ac6_committed_config_names_the_quantity_column() -> None:
    settings = load_settings(env={})
    assert settings.net_sales.quantity_field == "Quantity(PCS)"
    assert settings.net_sales.quantity_field in settings.ingest.expected_columns


def test_ac6_a_quantity_column_missing_from_expected_columns_fails(load_with) -> None:
    with pytest.raises(ConfigError, match=r"net_sales\.quantity_field.*Qty_Nowhere"):
        load_with(known(quantity_field="Qty_Nowhere"))


@pytest.mark.parametrize("value", ["", None])
def test_ac6_an_empty_quantity_field_fails_and_names_the_key(load_with, value) -> None:
    with pytest.raises(ConfigError, match=r"net_sales\.quantity_field"):
        load_with({"net_sales": {"quantity_field": value}})


# Hash: a business decision changes the config hash --------------------------------------------


def test_ac7_changing_the_field_changes_the_config_hash(load_with) -> None:
    a = load_with({"net_sales": {"field": "Net_Amount_2"}}, name="a")
    b = load_with({"net_sales": {"field": "Net_AMOUNT_3"}}, name="b")
    assert config_hash(a) != config_hash(b)


def test_ac7_changing_the_candidates_or_the_quantity_column_changes_the_hash(load_with) -> None:
    base = load_with(known(), name="base")
    narrower = load_with(known(candidate_columns=["Net_Amount_2"]), name="narrow")
    other_qty = load_with(known(quantity_field="Other"), name="qty")
    assert len({config_hash(base), config_hash(narrower), config_hash(other_qty)}) == 3
