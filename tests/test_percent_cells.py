"""Percentages stored as fractions. Excel shows 0.123 formatted as ``0.0%`` as "12.3%", and INSTAT's tables are full of them; the clean
data holds 12.3. This is the one place where a number in the table is not the number in the cell, so each case is pinned."""

from __future__ import annotations

import pytest

from instatkit.export.xlsx_writer import Style
from instatkit.export.xlsx_writer import Workbook as Writer

from .conftest import process_workbook_bytes

PERCENT = Style(fmt="0.0%")
YEARS = [2019, 2020, 2021, 2022]


def workbook(rows, title_en="Share of households with internet (%)", formatted=lambda i, j: True):
    wb = Writer()
    ws = wb.active
    ws["A1"], ws["A2"] = "Familjet me internet sipas rajonit (%)", title_en
    ws.cell(4, 1, "Rajoni / Region")
    for j, y in enumerate(YEARS):
        ws.cell(4, 2 + j, y)
    for i, (name, values) in enumerate(rows):
        ws.cell(5 + i, 1, name)
        for j, v in enumerate(values):
            cell = ws.cell(5 + i, 2 + j, v)
            if formatted(i, j):
                cell.style = PERCENT
    return wb.save()


def tidy(data):
    pf = process_workbook_bytes(data)
    assert pf.ok and len(pf.tables) == 1, pf.errors
    t = pf.tables[0].table
    return dict(zip(t.df["src_ref"], t.df["value"])), t


ROWS = [("Tirana", [0.123, 0.5, 0.75, 0.999]), ("Durres", [0.07, 0.2, 0.3, 0.4])]


def test_fractions_shown_as_percentages_are_stored_as_percentages():
    values, table = tidy(workbook(ROWS))
    assert values["B5"] == 12.3 and values["C5"] == 50.0 and values["E5"] == 99.9
    assert values["B6"] == 7.0                                                  # 0.07 * 100 is 7.000000000000001 in floating point
    assert set(table.df["unit"].dropna()) == {"%"}


def test_the_source_reference_still_names_the_cell_that_holds_the_fraction():
    values, _ = tidy(workbook(ROWS))
    assert sorted(values) == ["B5", "B6", "C5", "C6", "D5", "D6", "E5", "E6"]


def test_the_same_fractions_without_a_percent_format_are_left_alone():
    values, _ = tidy(workbook(ROWS, formatted=lambda i, j: False))
    assert values["B5"] == 0.123 and values["B6"] == 0.07


def test_numbers_formatted_as_percent_but_larger_than_one_and_a_half_are_not_fractions():
    rows = [("Tirana", [12.5, 50, 75, 99]), ("Durres", [7, 20, 30, 40])]
    values, _ = tidy(workbook(rows))
    assert values["B5"] == 12.5 and values["E5"] == 99


def test_one_and_a_half_is_still_a_fraction_and_a_little_more_is_not():
    assert tidy(workbook([("Tirana", [1.5, 0.5, 0.75, 0.9]), ("Durres", [0.07, 0.2, 0.3, 0.4])]))[0]["B5"] == 150.0
    assert tidy(workbook([("Tirana", [1.6, 0.5, 0.75, 0.9]), ("Durres", [0.07, 0.2, 0.3, 0.4])]))[0]["B5"] == 1.6


def test_four_fifths_of_the_cells_must_carry_the_percent_format():
    four_of_five = lambda i, j: (i, j) != (1, 3) and (i, j) != (0, 3)           # 6 of 8 formatted: not enough  # noqa: E731
    assert tidy(workbook(ROWS, formatted=four_of_five))[0]["B5"] == 0.123
    rows = [("Tirana", [0.123, 0.5, 0.75, 0.999]), ("Durres", [0.07, 0.2, 0.3, 0.4]), ("Vlora", [0.1, 0.2, 0.3, 0.4]),
            ("Fier", [0.1, 0.2, 0.3, 0.4]), ("Korca", [0.1, 0.2, 0.3, 0.4])]    # 20 cells
    assert tidy(workbook(rows, formatted=lambda i, j: (i, j) != (4, 3) and (i, j) != (3, 3) and (i, j) != (2, 3) and (i, j) != (1, 3)))[0]["B5"] == 12.3   # 16 of 20
    assert tidy(workbook(rows, formatted=lambda i, j: (i, j) not in {(4, 3), (3, 3), (2, 3), (1, 3), (0, 3)}))[0]["B5"] == 0.123              # 15 of 20


@pytest.mark.parametrize("title", ["Population (persons)", "Average wage (ALL)"])
def test_percent_formatted_cells_in_a_table_of_something_else_are_left_alone(title):
    values, _ = tidy(workbook(ROWS, title_en=title))
    assert values["B5"] == 0.123
