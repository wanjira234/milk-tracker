"""Reading a shop's price list as POS and stock systems export it (pure)."""
import io
from decimal import Decimal

import openpyxl
import pytest

from src import catalogue


def test_loose_column_names_stock_and_problems():
    rows = [["Item Code", "Item Name", "Pack Size", "Selling Price", "Qty On Hand"],
            ["A1", "Dairy meal", "70 kg bag", "2,550", "48"],
            ["A2", "Silage", "50 kg bag", "900", "0"],
            ["A3", "Hay", "", "KES 350", ""],
            ["A4", "Broken", "bag", "ask", "3"],
            ["A5", "dairy meal", "bag", "100", "1"],
            ["", "", "", "", ""]]
    products, problems = catalogue.parse_rows(rows)
    assert [(p["name"], p["unit"], p["price"], p["in_stock"], p["ref"]) for p in products] == [
        ("Dairy meal", "70 kg bag", Decimal("2550.00"), True, "A1"),
        ("Silage", "50 kg bag", Decimal("900.00"), False, "A2"),
        ("Hay", "each", Decimal("350.00"), True, "A3")]
    assert len(problems) == 2 and "isn't a number" in problems[0] and "listed twice" in problems[1]


def test_a_list_needs_names_and_prices():
    with pytest.raises(ValueError, match="name column and a price column"):
        catalogue.parse_rows([["Thing", "Cost?"], ["x", "1"]])
    with pytest.raises(ValueError, match="empty"):
        catalogue.parse_rows([])
    with pytest.raises(ValueError, match="at most"):
        catalogue.parse_rows([["Product", "Price"]] + [[f"p{i}", "1"] for i in range(catalogue.MAX_ROWS + 1)])


def test_csv_and_excel_files():
    rows = catalogue.read_file("list.csv", "﻿Product,Price,In stock\nLick,900,no\n".encode())
    assert catalogue.parse_rows(rows)[0][0]["in_stock"] is False
    wb = openpyxl.Workbook()
    wb.active.append(["Product", "Unit", "Price"])
    wb.active.append(["Dairy meal", "70 kg bag", 2600])
    buf = io.BytesIO()
    wb.save(buf)
    (p,), _ = catalogue.parse_rows(catalogue.read_file("list.xlsx", buf.getvalue()))
    assert p["price"] == Decimal("2600.00")
    with pytest.raises(ValueError, match=".csv or .xlsx"):
        catalogue.read_file("list.pdf", b"x")
    with pytest.raises(ValueError, match="too big"):
        catalogue.read_file("list.csv", b"x" * (catalogue.MAX_BYTES + 1))
