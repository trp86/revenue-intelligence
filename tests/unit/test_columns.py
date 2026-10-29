"""Story #31: final column names for the RAW SCJ SALES header (spec 01 B3)."""

from __future__ import annotations

import pytest

from revint.ingest.columns import final_column_names, normalise_name

# The raw header of the real sheet, in source order (Excel row 7, columns A to BW).
# Spaces at the ends are kept exactly as they appear in the file.
REAL_HEADER = [
    "OrderReference", "VoucherNo", "CustomerCode", "Customer", "SalemanName",
    "SALES MAN RBD", "KAM", "SalePlanDay", "Date", "SCJ FISCAL YEAR ",
    "SCJ FISCAL HALF YEAR", "QTR ", "Year", "Month", "SWE ZIN MONTH ",
    "SCJ FISCAL MONTH ", "PaymentType", "Paid", "Void", "SAP CODE",
    "SCJ CODE", "Product Decription", "SCJ CODE", "UOM", "FOB",
    "TOTAL FOB IN AMOUNT", "Internal Category", "SCJ VOLVAL FILE", "FRAGRANCES", "Size",
    "Actual Brands", "SCJ SEGMENT ", "Actual Brands", "Sticker (Individual/Shared)", "Sticker Size",
    "Selling Price", "Selling Amount", "RBD DISCOUNT AMOUNT", "Quantity(PCS)", "Change to Ctn",
    "PRICE", "NET AMOUNT", "DISCOUNT 1", "AMOUNT AF DIS", "Discount 2",
    "Net Amount", "Back Margin 3%", "Net AMOUNT", "CT 5%", "TAX AMOUNT",
    "price LEVEL ပြန်ေရွးရန်", "UnitPrice",
    "Original price", "Diff Price", "Diff Amount",
    "Discount(%)", "Discount(%)", "DiscountAmount", "Tax", "SaleTeam",
    "PaymentTerm", "Channel Type", "RBD CHANNEL BREAKDOWN", "Channel Category", "SCJ CHAIN 2",
    "SCJ CHANNEL", "Chain Type", "Chain Name", "DC ", "TOWNSHIP",
    "CITY/TOWN", "Branch Name", "SCJ CITIES", "Branch Type", "Region",
]


# normalise_name: trim the ends, inner spaces become underscores ----------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Net Amount", "Net_Amount"),
        ("QTR ", "QTR"),
        (" QTR", "QTR"),
        ("  SCJ FISCAL YEAR  ", "SCJ_FISCAL_YEAR"),
        ("Change to Ctn", "Change_to_Ctn"),
        ("Quantity(PCS)", "Quantity(PCS)"),
        ("Back Margin 3%", "Back_Margin_3%"),
        ("CITY/TOWN", "CITY/TOWN"),
        ("Sticker (Individual/Shared)", "Sticker_(Individual/Shared)"),
        ("OrderReference", "OrderReference"),
        ("", ""),
    ],
)
def test_normalise_trims_the_ends_and_replaces_inner_spaces(raw: str, expected: str) -> None:
    assert normalise_name(raw) == expected


def test_normalise_replaces_each_space_not_each_run_of_spaces() -> None:
    assert normalise_name("A  B") == "A__B"


def test_normalise_keeps_non_ascii_characters() -> None:
    assert normalise_name("price LEVEL ပြ") == "price_LEVEL_ပြ"


def test_normalise_trims_non_breaking_and_tab_whitespace_at_the_ends() -> None:
    assert normalise_name(" QTR\t") == "QTR"


# final_column_names: suffixes for names equal ignoring case ---------------------


def test_unique_names_get_no_suffix() -> None:
    assert final_column_names(["A", "B", "C"]) == ["A", "B", "C"]


def test_names_equal_exactly_are_suffixed_in_source_order() -> None:
    assert final_column_names(["SCJ CODE", "X", "SCJ CODE"]) == ["SCJ_CODE_1", "X", "SCJ_CODE_2"]


def test_names_equal_only_ignoring_case_are_suffixed_and_keep_their_own_case() -> None:
    names = final_column_names(["NET AMOUNT", "Net Amount", "Net AMOUNT"])
    assert names == ["NET_AMOUNT_1", "Net_Amount_2", "Net_AMOUNT_3"]


def test_names_equal_after_trimming_are_suffixed() -> None:
    assert final_column_names(["QTR ", "QTR"]) == ["QTR_1", "QTR_2"]


def test_names_equal_after_underscore_replacement_are_suffixed() -> None:
    assert final_column_names(["A B", "A_B"]) == ["A_B_1", "A_B_2"]


def test_the_result_has_the_same_length_and_no_name_repeats_ignoring_case() -> None:
    names = final_column_names(["a", "A", "b", "a", "B"])
    assert len(names) == 5
    assert len({n.casefold() for n in names}) == 5


def test_a_suffixed_name_never_collides_with_an_existing_name() -> None:
    names = final_column_names(["A", "A", "A_1"])
    assert len({n.casefold() for n in names}) == 3
    assert "A_1" in names, "the original A_1 keeps its name"


def test_an_empty_header_cell_is_refused() -> None:
    with pytest.raises(ValueError, match="column 2"):
        final_column_names(["A", "  ", "C"])


def test_allow_blank_keeps_empty_cells_as_empty_names_and_never_suffixes_them() -> None:
    names = final_column_names(["A", "", "A", " ", "B"], allow_blank=True)
    assert names == ["A_1", "", "A_2", "", "B"]


def test_allow_blank_gives_the_same_names_as_the_strict_form_when_nothing_is_blank() -> None:
    raw = ["SCJ CODE", "x", "SCJ CODE", "NET AMOUNT", "Net Amount"]
    assert final_column_names(raw, allow_blank=True) == final_column_names(raw)


def test_no_header_cells_gives_an_empty_list() -> None:
    assert final_column_names([]) == []


# the real header ------------------------------------------------------------------


def test_the_real_header_has_75_columns_and_75_distinct_names() -> None:
    names = final_column_names(REAL_HEADER)
    assert len(REAL_HEADER) == 75
    assert len(names) == 75
    assert len({n.casefold() for n in names}) == 75


def test_the_real_header_matches_the_maintainers_decisions() -> None:
    names = final_column_names(REAL_HEADER)
    by_position = {i + 1: n for i, n in enumerate(names)}
    # trailing spaces trimmed, inner spaces become underscores
    assert by_position[10] == "SCJ_FISCAL_YEAR"
    assert by_position[12] == "QTR"
    assert by_position[69] == "DC"
    assert by_position[40] == "Change_to_Ctn"
    assert by_position[39] == "Quantity(PCS)"
    # exact repeats
    assert (by_position[21], by_position[23]) == ("SCJ_CODE_1", "SCJ_CODE_2")
    assert (by_position[31], by_position[33]) == ("Actual_Brands_1", "Actual_Brands_2")
    assert (by_position[56], by_position[57]) == ("Discount(%)_1", "Discount(%)_2")
    # names that differ only by case: net sales is column 46
    assert (by_position[42], by_position[46], by_position[48]) == (
        "NET_AMOUNT_1",
        "Net_Amount_2",
        "Net_AMOUNT_3",
    )


def test_only_the_repeated_names_get_a_suffix() -> None:
    names = final_column_names(REAL_HEADER)
    # A suffix was added exactly where the final name differs from the plain normalised name.
    # (Names such as DISCOUNT_1 from "DISCOUNT 1" end in a digit naturally and are not suffixed.)
    suffixed = [n for n, raw in zip(names, REAL_HEADER, strict=True) if n != normalise_name(raw)]
    assert suffixed == [
        "SCJ_CODE_1", "SCJ_CODE_2",
        "Actual_Brands_1", "Actual_Brands_2",
        "NET_AMOUNT_1", "Net_Amount_2", "Net_AMOUNT_3",
        "Discount(%)_1", "Discount(%)_2",
    ]


def test_names_that_end_in_a_digit_naturally_are_not_suffixed() -> None:
    names = final_column_names(REAL_HEADER)
    assert "DISCOUNT_1" in names and "Discount_2" in names and "SCJ_CHAIN_2" in names


def test_the_real_header_names_have_no_spaces() -> None:
    assert not [n for n in final_column_names(REAL_HEADER) if " " in n]
