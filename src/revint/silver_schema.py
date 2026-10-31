"""The silver column facts the settings need to check names (spec 01 S1, S2, S7 to S10).

Kept apart from revint.silver so revint.config can use them without a circular import.
revint.silver re-exports COLUMN_TYPES. Tests compare these names with the real silver table,
so a flag added to the SQL without being added here fails a test.
"""

from __future__ import annotations

_DATES = ("Date", "SCJ_FISCAL_MONTH")
_INTEGERS = ("Year", "Quantity(PCS)", "UOM")
_DECIMALS = (
    "FOB",
    "TOTAL_FOB_IN_AMOUNT",
    "Selling_Price",
    "Selling_Amount",
    "RBD_DISCOUNT_AMOUNT",
    "Change_to_Ctn",
    "PRICE",
    "NET_AMOUNT_1",
    "DISCOUNT_1",
    "AMOUNT_AF_DIS",
    "Discount_2",
    "Net_Amount_2",
    "Back_Margin_3%",
    "Net_AMOUNT_3",
    "CT_5%",
    "TAX_AMOUNT",
    "UnitPrice",
    "Original_price",
    "Diff_Price",
    "Diff_Amount",
    "Discount(%)_1",
    "Discount(%)_2",
    "DiscountAmount",
)

# The type given to a source column; columns not listed here are text. The SQL file
# 02_silver_sales.sql lists the same columns; a test compares the two.
COLUMN_TYPES: dict[str, str] = {
    **dict.fromkeys(_DATES, "date"),
    **dict.fromkeys(_INTEGERS, "integer"),
    **dict.fromkeys(_DECIMALS, "decimal"),
}

# The true/false flag columns of silver_sales: the rule flags, the two exclusion marks and one
# f_bad_<column> per typed column (S2). void_flag is a number, not one of them.
SILVER_FLAG_COLUMNS: tuple[str, ...] = (
    "f_stray_row",
    "f_zero_value_with_qty",
    "f_negative_qty",
    "f_negative_value",
    "f_blank_void",
    "f_unmapped_void",
    "f_unmapped_label",
    "is_duplicate",
    "is_excluded",
    *(f"f_bad_{name}" for name in COLUMN_TYPES),
)
