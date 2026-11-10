"""The old ``.xls`` reader on files written by an independent writer (xlwt): what a cell holds, which cells are percentages, merges and
hidden rows, and what is said when xlrd cannot open the file."""

from __future__ import annotations

import datetime
import io

import pytest

from instatkit import config
from instatkit.excel import xls
from instatkit.excel.grid import read_workbook
from instatkit.excel.raw import UnreadableWorkbook

xlwt = pytest.importorskip("xlwt")
xlrd = pytest.importorskip("xlrd")


def save(book) -> bytes:
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def sheet_of(book, index=0):
    return read_workbook(save(book), "t.xls").sheets[index]


def test_text_numbers_booleans_and_dates():
    book = xlwt.Workbook()
    sh = book.add_sheet("Data")
    date_style = xlwt.easyxf(num_format_str="YYYY-MM-DD")
    sh.write(0, 0, "Tiranë")
    sh.write(0, 1, 12.5)
    sh.write(0, 2, True)
    sh.write(0, 3, datetime.datetime(2023, 4, 30), date_style)
    sh.write(1, 0, 7)
    g = sheet_of(book)
    assert g.cells[0][:4] == ["Tiranë", 12.5, True, datetime.datetime(2023, 4, 30)]
    assert g.cells[1][0] == 7.0 and g.visible and not g.truncated


def test_a_date_that_is_not_a_real_date_stays_a_number():
    """An absurdly large serial is refused by xlrd; dropping the cell would lose a number the table may rest on."""
    book = xlwt.Workbook()
    sh = book.add_sheet("Data")
    for c, serial in enumerate((1e9, 1e12, 61)):
        sh.write(0, c, serial, xlwt.easyxf(num_format_str="YYYY-MM-DD"))
    g = sheet_of(book)
    assert g.cells[0][:2] == [1e9, 1e12] and g.cells[0][2] == datetime.datetime(1900, 3, 1)


def test_only_the_cells_formatted_as_percent_are_percentages():
    book = xlwt.Workbook()
    sh = book.add_sheet("Data")
    sh.write(0, 0, 0.25, xlwt.easyxf(num_format_str="0.0%"))
    sh.write(0, 1, 0.25)
    sh.write(0, 2, 0.5, xlwt.easyxf(num_format_str="0%"))
    sh.write(0, 3, 3, xlwt.easyxf(num_format_str="0.00"))
    assert sheet_of(book).pct_cells == {(0, 0), (0, 2)}


def test_merged_cells_hidden_rows_and_hidden_columns():
    book = xlwt.Workbook()
    sh = book.add_sheet("Data")
    sh.write_merge(0, 0, 0, 2, "Title across three columns")
    for r in range(1, 5):
        for c in range(4):
            sh.write(r, c, r * 10 + c)
    sh.row(2).hidden = True
    sh.col(3).hidden = True
    g = sheet_of(book)
    assert g.merged == [(0, 0, 0, 2)]
    assert g.hidden_rows == {2} and g.hidden_cols == {3}


def test_sheets_keep_their_order_and_names():
    book = xlwt.Workbook()
    for name in ("First", "Second", "Third"):
        book.add_sheet(name).write(0, 0, name)
    wb = read_workbook(save(book), "t.xls")
    assert [g.name for g in wb.sheets] == ["First", "Second", "Third"]
    assert wb.format == "xls"


def test_rows_beyond_the_cap_are_cut_and_the_sheet_says_so(monkeypatch):
    monkeypatch.setattr(config, "MAX_ROWS", 5)
    book = xlwt.Workbook()
    sh = book.add_sheet("Data")
    for r in range(8):
        sh.write(r, 0, r)
    g = sheet_of(book)
    assert g.truncated and g.n_rows == 5


def test_columns_beyond_the_cap_are_cut(monkeypatch):
    monkeypatch.setattr(config, "MAX_COLS", 3)
    book = xlwt.Workbook()
    sh = book.add_sheet("Data")
    for c in range(6):
        sh.write(0, c, c)
    g = sheet_of(book)
    assert g.truncated and g.n_cols == 3


def test_a_format_without_formatting_info_is_read_with_a_note(monkeypatch):
    """The oldest BIFF versions cannot give formats: the values are read and the reader says what is lost."""
    real = xlrd.open_workbook
    calls = []

    def fake(*args, **kwargs):
        calls.append(kwargs.get("formatting_info"))
        if kwargs.get("formatting_info"):
            raise NotImplementedError("formatting_info=True not yet implemented")
        return real(*args, **kwargs)

    monkeypatch.setattr(xlrd, "open_workbook", fake)
    book = xlwt.Workbook()
    book.add_sheet("Data").write_merge(0, 0, 0, 1, "A")
    parsed = xls.parse(save(book))
    assert calls == [True, None]
    assert parsed.sheets[0].rows[0][0] == "A" and parsed.sheets[0].merged == []
    assert parsed.notes == ["Merged cells and formats cannot be read from this old .xls file."]


@pytest.mark.parametrize("message, expected", [
    ("Workbook is encrypted", "The workbook is password-protected."),
    ("needs a PASSWORD", "The workbook is password-protected."),
    ("Unsupported format, or corrupt file", "The old .xls file could not be read: Unsupported format, or corrupt file"),
])
def test_what_xlrd_refuses_is_explained(monkeypatch, message, expected):
    def refuse(*args, **kwargs):
        raise xlrd.XLRDError(message)

    monkeypatch.setattr(xlrd, "open_workbook", refuse)
    with pytest.raises(UnreadableWorkbook) as info:
        xls.parse(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    assert str(info.value) == expected


def test_any_other_failure_names_only_its_kind(monkeypatch):
    def explode(*args, **kwargs):
        raise MemoryError("secret path C:/somewhere")

    monkeypatch.setattr(xlrd, "open_workbook", explode)
    with pytest.raises(UnreadableWorkbook) as info:
        xls.parse(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    assert str(info.value) == "The old .xls file could not be read (MemoryError)."
