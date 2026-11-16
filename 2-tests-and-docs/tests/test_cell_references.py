"""Every number in the clean data says which cell of the original file it came from. This opens the original file again with a reader that
is not the program's own (openpyxl), looks each of those cells up and compares: any number that points at the wrong cell fails."""

from __future__ import annotations

import io
import math
import re

import openpyxl
import pytest
from openpyxl.utils import column_index_from_string

from instatkit import demo

from .conftest import process_workbook_bytes
from .test_stack import PLACES, blocks, sheets

ADDRESS = re.compile(r"^(?:(?P<sheet>.+)!)?(?P<column>[A-Z]+)(?P<row>\d+)$")


def cell_for(book, table_sheet: str, ref: str):
    m = ADDRESS.match(ref)
    assert m, f"{ref!r} is not a cell reference"
    return book[m.group("sheet") or table_sheet].cell(int(m.group("row")), column_index_from_string(m.group("column"))).value


def as_number(cell) -> float | None:
    """What a person reads in the cell: a number, or text such as ``61 500`` (INSTAT writes some numbers as text)."""
    if isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        return float(cell)
    if isinstance(cell, str):
        try:
            return float(re.sub(r"[\s ]", "", cell).replace(",", "."))
        except ValueError:
            return None
    return None


def assert_every_number_points_at_its_cell(data: bytes) -> int:
    book = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    pf = process_workbook_bytes(data)
    assert pf.ok and pf.tables, pf.errors
    checked = 0
    for pt in pf.tables:
        t = pt.table
        for ref, value in zip(t.df["src_ref"], t.df["value"]):
            if value is None or (isinstance(value, float) and math.isnan(value)):
                continue
            cell = as_number(cell_for(book, t.sheet, str(ref)))
            assert cell is not None, (t.sheet, ref, value)
            assert cell == pytest.approx(value, rel=1e-9), (t.sheet, ref, value, cell)
            checked += 1
    return checked


@pytest.mark.parametrize("name", list(demo.DEMOS))
def test_every_number_in_a_demo_points_at_the_cell_it_came_from(name):
    assert assert_every_number_points_at_its_cell(demo.DEMOS[name][2]()) > 10


def test_with_several_sheets_the_reference_names_the_sheet_and_the_cell_in_it():
    assert assert_every_number_points_at_its_cell(sheets(PLACES, scope=True)) == 27           # 3 places x 3 age groups x 3 years


def test_repeated_blocks_on_one_sheet_point_at_their_own_rows():
    assert assert_every_number_points_at_its_cell(blocks(["Males", "Females"])) > 0
