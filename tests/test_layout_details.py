"""Small layouts that sit on the edge of what the reader recognises, each made here so the right answer is known: when a header column is a
category and when it is a measure, a row of column numbers, a year written once above a header, and the user's manual corrections."""

from __future__ import annotations

import pytest

from instatkit.excel import grid as grid_mod
from instatkit.excel.layout import Overrides
from instatkit.excel.tidy import extract_tables
from instatkit.export.xlsx_writer import Workbook as Writer


def read(data, overrides=None):
    result = extract_tables(grid_mod.read_workbook(data, "test.xlsx"), overrides=overrides)
    assert len(result.tables) == 1, result.skipped
    return result.tables[0]


def values_by_cell(table):
    return dict(zip(table.df["src_ref"], table.df["value"]))


def sectors(header, annotation=None, title=True):
    wb = Writer()
    ws = wb.active
    r = 1
    if title:
        ws["A1"] = "Activity of enterprises by sector"
        r = 3
    ws.cell(r, 1, "Sector")
    for j, h in enumerate(header):
        ws.cell(r, 2 + j, h)
    r += 1
    if annotation:
        for j, a in enumerate(annotation):
            ws.cell(r, 2 + j, a)
        r += 1
    for i, name in enumerate(["Industry", "Trade", "Transport", "Services"]):
        ws.cell(r + i, 1, name)
        for j in range(len(header)):
            ws.cell(r + i, 2 + j, 100.5 + 10 * i + j)
    return wb.save()


# --- header columns: categories or different measures ---
def test_columns_with_different_names_are_different_measures():
    t = read(sectors(("Enterprises", "Turnover", "Employees")))
    assert list(t.dim_columns) == ["dim_1"] and sorted(set(t.df["measure"])) == ["Employees", "Enterprises", "Turnover"]


def test_columns_next_to_a_total_are_its_categories():
    t = read(sectors(("Total", "Enterprises", "Employees")))
    assert list(t.dim_columns) == ["dim_1", "dim_2"] and t.dim_info["dim_2"]["source"] == "column"
    assert set(t.df["dim_2"]) == {"Total", "Enterprises", "Employees"} and set(t.df["measure"]) == {"Activity of enterprises by sector"}


# --- a row of column numbers ---
def test_a_row_of_three_column_numbers_under_the_header_is_not_data():
    t = read(sectors(("Enterprises", "Turnover", "Employees"), annotation=(1, 2, 3)))
    assert len(t.df) == 12 and min(t.df["value"]) == 100.5
    assert any("column numbers" in r for r in t.spec.reasons)


def test_a_row_of_numbers_that_is_not_a_run_from_one_is_data():
    t = read(sectors(("Enterprises", "Turnover", "Employees"), annotation=(5, 6, 7)))
    assert len(t.df) == 15 and {5.0, 6.0, 7.0} <= set(t.df["value"])


# --- a year written once above the header ---
def test_a_year_in_a_merged_cell_above_a_text_header_is_the_period_of_the_columns_below():
    wb = Writer()
    ws = wb.active
    ws["A1"] = "Turnover by municipality"
    ws.cell(3, 1, "Municipality")
    ws.cell(3, 2, 2023)
    ws.merge_cells("B3:C3")
    ws.cell(4, 2, "Males")
    ws.cell(4, 3, "Females")
    for i, name in enumerate(["Berat", "Fier", "Vlore"]):
        ws.cell(5 + i, 1, name)
        ws.cell(5 + i, 2, 100.5 + i)
        ws.cell(5 + i, 3, 200.5 + i)
    t = read(wb.save())
    assert set(t.df["period"]) == {"2023"} and len(t.df) == 6
    assert values_by_cell(t)["B5"] == 100.5 and values_by_cell(t)["C7"] == 202.5


# --- the user's corrections ---
@pytest.fixture(scope="module")
def turnover():
    wb = Writer()
    ws = wb.active
    ws["A1"] = "Turnover by sector"
    ws["A2"] = "Notes: provisional"
    ws.cell(4, 1, "Sector")
    for j, h in enumerate(["2020", "2021", "2022"]):
        ws.cell(4, 2 + j, h)
    for i, name in enumerate(["Industry", "Trade", "Transport", "Services", "Other"]):
        ws.cell(5 + i, 1, name)
        for j in range(3):
            ws.cell(5 + i, 2 + j, 100.5 + 10 * i + j)
    return wb.save()


def test_without_corrections_the_header_is_found_and_every_row_is_data(turnover):
    t = read(turnover)
    assert len(t.df) == 15 and sorted(set(t.df["period"])) == ["2020", "2021", "2022"] and values_by_cell(t)["B5"] == 100.5


def test_the_first_data_row_can_be_set_by_hand(turnover):
    t = read(turnover, {"Sheet": Overrides(first_data_row=5)})                       # 0-based: the sixth row of the sheet
    assert len(t.df) == 12 and "B5" not in values_by_cell(t) and values_by_cell(t)["B6"] == 110.5


def test_the_number_of_label_columns_can_be_set_by_hand(turnover):
    t = read(turnover, {"Sheet": Overrides(n_label_cols=2)})                         # the first numeric column becomes a label
    assert list(t.dim_columns) == ["dim_1", "dim_2"] and sorted(set(t.df["period"])) == ["2021", "2022"] and len(t.df) == 10


def test_the_layout_can_be_forced_to_a_table_of_categories(turnover):
    t = read(turnover, {"Sheet": Overrides(orientation="cross_section")})
    assert set(t.df["period"]) == {""} and sorted(set(t.df["measure"])) == ["2020", "2021", "2022"]


def test_a_header_row_that_is_already_the_header_changes_nothing(turnover):
    assert read(turnover, {"Sheet": Overrides(header_rows=[3])}).df.equals(read(turnover).df)


@pytest.mark.parametrize("rows", [[99], [-1], [2]], ids=["below the sheet", "above the sheet", "an empty row"])
def test_a_header_row_that_does_not_exist_or_is_empty_is_ignored_not_a_crash(turnover, rows):
    t = read(turnover, {"Sheet": Overrides(header_rows=rows)})
    assert len(t.df) == 15 and values_by_cell(t)["B5"] == 100.5


def test_setting_only_the_last_data_row_keeps_the_header_the_program_found(turnover):
    t = read(turnover, {"Sheet": Overrides(last_data_row=7)})                        # 0-based: the eighth row of the sheet, "Services"
    assert sorted(set(t.df["period"])) == ["2020", "2021", "2022"] and len(t.df) == 12
    assert "B9" not in values_by_cell(t) and values_by_cell(t)["B5"] == 100.5


def test_setting_only_the_first_data_row_keeps_the_last_row_the_program_found(turnover):
    t = read(turnover, {"Sheet": Overrides(first_data_row=6)})
    assert sorted(set(t.df["period"])) == ["2020", "2021", "2022"] and len(t.df) == 9
    assert "B6" not in values_by_cell(t) and values_by_cell(t)["B9"] == 140.5
