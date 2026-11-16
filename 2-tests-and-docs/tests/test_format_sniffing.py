"""What a file is, judged from its bytes and not from its name or what a server claimed, and what the user is told for each kind that cannot
be read. A server that answers an error page with status 200 is the case this protects against."""

from __future__ import annotations

import io
import zipfile

import pytest

from instatkit import config
from instatkit.excel import grid as grid_mod
from instatkit.excel.grid import read_workbook, sniff_format
from instatkit.excel.raw import UnreadableWorkbook, format_problem


def zipped(*names: str, content: bytes = b"x") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in names:
            z.writestr(name, content)
    return buf.getvalue()


# --- by content ---
@pytest.mark.parametrize("data, expected", [
    (zipped("xl/workbook.xml"), "xlsx"),
    (zipped("xl/workbook.bin"), "xlsb"),
    (zipped("content.xml", "mimetype"), "ods"),
    (zipped("content.xml"), "zip"),                                                         # an OpenDocument file needs both
    (zipped("readme.txt"), "zip"),
    (b"PK\x03\x04 but not a zip at all", "corrupt"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100, "xls"),
    (b"<!DOCTYPE html><html></html>", "html"),
    (b"  \r\n<html><body>Not found</body></html>", "html"),
    (b"\xef\xbb\xbf<HTML>", "html"),
    (b"<head><title>x</title></head>", "html"),
    (b"<body>x</body>", "html"),
    (b'<?xml version="1.0"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"></Workbook>', "spreadsheetml"),
    (b'<?xml version="1.0"?><other/>', "unknown"),
    (b"a,b\n1,2\n", "csv"),
    (b"a;b\n1;2\n", "csv"),
    (b"a\tb\n1\t2\n", "csv"),
    (b"\x00\x01\x02 binary,with a comma", "unknown"),
    (b"just words", "unknown"),
    (b"", "unknown"),
])
def test_what_a_file_is_depends_on_its_bytes(data, expected):
    assert sniff_format(data) == expected


@pytest.mark.parametrize("name", ["a.csv", "a.CSV", "a.tsv", "a.txt"])
def test_a_text_file_with_a_data_extension_is_csv_even_without_separators(name):
    assert sniff_format(b"justonecolumn\n1\n2\n", name) == "csv"
    assert sniff_format(b"justonecolumn\n1\n2\n", "a.dat") == "unknown"


def test_the_extension_never_overrules_the_content():
    assert sniff_format(zipped("xl/workbook.xml"), "report.csv") == "xlsx"
    assert sniff_format(b"<html></html>", "report.xlsx") == "html"
    assert sniff_format(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 50, "report.xlsx") == "xls"


def test_a_marker_far_into_a_spreadsheetml_header_is_still_found_but_not_beyond_4096_bytes():
    marker = b"urn:schemas-microsoft-com:office:spreadsheet"
    inside = b'<?xml version="1.0"?>' + b" " * 3000 + marker
    outside = b'<?xml version="1.0"?>' + b" " * 5000 + marker
    assert sniff_format(inside) == "spreadsheetml" and sniff_format(outside) == "unknown"


# --- what the user is told ---
@pytest.mark.parametrize("data, needle", [
    (zipped("xl/workbook.bin"), ".xlsb"),
    (zipped("content.xml", "mimetype"), "OpenDocument"),
    (zipped("readme.txt"), "zip"),
    (b"PK\x03\x04 but not a zip at all", "damaged"),
    (b"<html><body>Not found</body></html>", "web page"),
    (b"\x00\x01\x02binary", "excel or csv"),
])
def test_each_kind_that_cannot_be_read_has_its_own_explanation(data, needle):
    with pytest.raises(UnreadableWorkbook) as caught:
        read_workbook(data, "file.xlsx")
    assert needle.lower() in str(caught.value).lower()
    assert str(caught.value) == format_problem(sniff_format(data, "file.xlsx"))


def test_an_empty_file_is_said_to_be_empty():
    with pytest.raises(UnreadableWorkbook) as caught:
        read_workbook(b"", "empty.xlsx")
    assert str(caught.value) == "The file is empty."


def test_a_format_nobody_thought_of_gets_the_general_explanation():
    assert format_problem("something-new") == format_problem("unknown")


def test_a_workbook_in_which_every_sheet_is_empty_is_refused():
    with pytest.raises(UnreadableWorkbook) as caught:
        read_workbook(b"\n\n\n", "t.csv")
    assert str(caught.value) == "The workbook has no data (every sheet is empty)."


# --- text files ---
@pytest.mark.parametrize("payload, expected", [
    ("Shkodër".encode(), "Shkodër"),                                       # utf-8
    (b"\xef\xbb\xbfShkod\xc3\xabr", "Shkodër"),                            # utf-8 with a byte order mark: the mark is dropped
    ("Shkodër".encode("cp1250"), "Shkodër"),                               # Central European Windows text
    (b"caf\x81 d\x8d", "caf\x81 d\x8d"),                                   # undefined in cp1250 and not utf-8: every byte is still a letter
])
def test_text_is_decoded_as_utf8_then_as_central_european_windows_text_then_byte_for_byte(payload, expected):
    assert grid_mod._decode_text(payload) == expected


def test_a_csv_with_one_column_and_no_separator_is_still_read():
    book = read_workbook(b"Region\nTirana\nDurres\n", "t.csv")
    [sheet] = book.sheets
    assert sheet.n_rows == 3 and sheet.n_cols == 1 and sheet.cell(1, 0) == "Tirana"


def test_a_pipe_delimited_file_is_read_as_columns():
    book = read_workbook(b"a|b|c\n1|2|3\n4|5|6\n", "t.csv")
    assert book.sheets[0].n_cols == 3 and book.sheets[0].cell(2, 2) == "6"                      # text: numbers are read later


def test_a_csv_longer_than_the_limits_is_cut_and_says_so(monkeypatch):
    monkeypatch.setattr(config, "MAX_ROWS", 5)
    monkeypatch.setattr(config, "MAX_COLS", 3)
    text = "\n".join(",".join(str(r * 10 + c) for c in range(6)) for r in range(10)) + "\n"
    [sheet] = read_workbook(text.encode(), "big.csv").sheets
    assert (sheet.n_rows, sheet.n_cols) == (5, 3) and sheet.truncated


def test_a_csv_within_the_limits_is_not_marked_as_cut(monkeypatch):
    monkeypatch.setattr(config, "MAX_ROWS", 5)
    [sheet] = read_workbook(b"a,b\n1,2\n3,4\n5,6\n7,8\n", "ok.csv").sheets                         # exactly five rows
    assert sheet.n_rows == 5 and not sheet.truncated
