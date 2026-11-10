"""The Excel 2003 XML reader on documents written by hand, so that every position and every flag is known: where ``ss:Index`` and
``ss:MergeAcross`` put a cell, which cells are percentages through a style and its parent, hidden rows, columns and sheets, the type of each
value, and what is kept of a damaged document."""

from __future__ import annotations

import datetime

import pytest

from instatkit import config
from instatkit.excel import spreadsheetml
from instatkit.excel.grid import read_workbook
from instatkit.excel.raw import UnreadableWorkbook

NS = 'xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"'


def doc(body: str, styles: str = "", props: str = "") -> bytes:
    return f'<?xml version="1.0"?><Workbook {NS}>{props}{styles}{body}</Workbook>'.encode()


def sheet(name: str, rows: str, options: str = "", columns: str = "") -> str:
    return f'<Worksheet ss:Name="{name}"><Table>{columns}{rows}</Table>{options}</Worksheet>'


def cell(value, kind="String", **attrs) -> str:
    a = "".join(f' ss:{k}="{v}"' for k, v in attrs.items())
    return f'<Cell{a}><Data ss:Type="{kind}">{value}</Data></Cell>'


def parse(xml: bytes):
    return spreadsheetml.parse(xml)


def test_cells_continue_after_the_previous_one_and_an_index_jumps():
    rows = ('<Row>' + cell("a") + cell("b") + cell("c", Index=5) + cell("d") + '</Row>'
            '<Row ss:Index="4">' + cell("e") + '</Row>' + '<Row>' + cell("f", Index=2) + '</Row>')
    s = parse(doc(sheet("S", rows))).sheets[0]
    assert s.rows[0][:6] == ["a", "b", None, None, "c", "d"]
    assert s.rows[3][0] == "e" and s.rows[4][1] == "f"                   # the row after row 4 is row 5, whatever its first cell says
    assert len(s.rows) == 5


def test_a_merged_cell_pushes_the_next_one_to_the_right_and_records_the_range():
    rows = ('<Row>' + cell("title", MergeAcross=2, MergeDown=1) + cell("x") + '</Row>'
            '<Row ss:Index="3">' + cell("y") + '</Row>')
    s = parse(doc(sheet("S", rows))).sheets[0]
    assert s.rows[0][0] == "title" and s.rows[0][3] == "x"
    assert s.merged == [(0, 0, 1, 2)]


def test_a_bad_index_or_span_falls_back_instead_of_failing():
    """Unreadable positions mean 'the next one'; a span that is not positive merges nothing."""
    rows = '<Row ss:Index="abc">' + cell("a", Index="x") + cell("b", MergeAcross="-4") + '</Row>'
    s = parse(doc(sheet("S", rows))).sheets[0]
    assert s.rows == [["a", "b"]] and s.merged == []


@pytest.mark.parametrize("kind, text, expected", [
    ("String", " keep spaces ", " keep spaces "),
    ("Number", "12.5", 12.5),
    ("Number", "oops", "oops"),
    ("Number", "  ", None),
    ("Boolean", "1", True), ("Boolean", "true", True), ("Boolean", "0", False), ("Boolean", "False", False),
    ("DateTime", "2023-04-30T00:00:00.000", datetime.datetime(2023, 4, 30)),
    ("DateTime", "2023-04-30T10:30:00Z", datetime.datetime(2023, 4, 30, 10, 30)),
    ("DateTime", "1899-12-31T06:00:00.000", datetime.time(6, 0)),
    ("DateTime", "not a date", "not a date"),
    ("Error", "#DIV/0!", "#DIV/0!"),
])
def test_each_type_of_value(kind, text, expected):
    s = parse(doc(sheet("S", "<Row>" + cell(text, kind) + "</Row>"))).sheets[0]
    assert (s.rows[0][0] if s.rows else None) == expected


def test_a_comment_is_not_a_value():
    rows = '<Row><Cell><Comment><Data ss:Type="String">a note</Data></Comment><Data ss:Type="String">real</Data></Cell></Row>'
    assert parse(doc(sheet("S", rows))).sheets[0].rows[0][0] == "real"


STYLES = ('<Styles><Style ss:ID="p"><NumberFormat ss:Format="0.0%"/></Style><Style ss:ID="word"><NumberFormat ss:Format="Percent"/></Style>'
          '<Style ss:ID="child" ss:Parent="p"/><Style ss:ID="grandchild" ss:Parent="child"/><Style ss:ID="plain"><NumberFormat ss:Format="0.00"/></Style>'
          '<Style ss:ID="loop" ss:Parent="loop"/></Styles>')


def test_percent_styles_are_found_directly_by_name_and_through_their_parents():
    row = "<Row>" + "".join(cell("0.5", "Number", StyleID=s) for s in ("p", "word", "child", "grandchild", "plain", "loop", "missing")) + "</Row>"
    s = parse(doc(sheet("S", row), STYLES)).sheets[0]
    assert s.pct == {(0, 0), (0, 1), (0, 2), (0, 3)}


def test_only_numbers_can_be_percentages():
    row = "<Row>" + cell("half", "String", StyleID="p") + "</Row>"
    assert parse(doc(sheet("S", row), STYLES)).sheets[0].pct == set()


def test_hidden_rows_columns_and_sheets():
    columns = '<Column ss:Index="2" ss:Hidden="1" ss:Span="1"/><Column/>'
    rows = '<Row>' + cell("a") + '</Row><Row ss:Hidden="1">' + cell("b") + '</Row>'
    body = (sheet("Shown", rows, columns=columns) +
            sheet("Gone", "<Row>" + cell("x") + "</Row>", options="<WorksheetOptions><Visible>SheetHidden</Visible></WorksheetOptions>") +
            sheet("Deep", "<Row>" + cell("y") + "</Row>", options="<WorksheetOptions><Visible>SheetVeryHidden</Visible></WorksheetOptions>") +
            sheet("Fine", "<Row>" + cell("z") + "</Row>", options="<WorksheetOptions><Visible>SheetVisible</Visible></WorksheetOptions>"))
    book = parse(doc(body))
    shown, gone, deep, fine = book.sheets
    assert shown.hidden_rows == {1} and shown.hidden_cols == {1, 2}
    assert [s.visible for s in book.sheets] == [True, False, False, True]


def test_sheets_without_a_name_are_numbered():
    body = "<Worksheet><Table><Row>" + cell("a") + "</Row></Table></Worksheet>" + sheet("Named", "<Row>" + cell("b") + "</Row>")
    assert [s.name for s in parse(doc(body)).sheets] == ["Sheet1", "Named"]


def test_document_properties_are_kept_and_other_titles_are_not():
    props = ("<DocumentProperties><Title> Wages </Title><Author>INSTAT</Author><Created>2024-01-02T03:04:05Z</Created>"
             "<LastSaved>2024-02-03T00:00:00Z</LastSaved><Company>Elsewhere</Company></DocumentProperties>")
    assert parse(doc(sheet("S", "<Row>" + cell("a") + "</Row>"), props=props)).props == {
        "title": "Wages", "creator": "INSTAT", "created": "2024-01-02T03:04:05Z", "modified": "2024-02-03T00:00:00Z"}
    other = "<CustomDocumentProperties><Title>not this</Title></CustomDocumentProperties>"
    assert parse(doc(sheet("S", "<Row>" + cell("a") + "</Row>"), props=other)).props == {}


def test_a_document_cut_off_in_the_middle_keeps_what_was_read():
    xml = doc(sheet("One", "<Row>" + cell("a") + "</Row>") + sheet("Two", "<Row>" + cell("b") + "</Row>"))
    cut = xml[:xml.index(b"</Worksheet>", xml.index(b"Two"))]                          # ends inside the second sheet
    book = parse(cut)
    assert [s.name for s in book.sheets] == ["One", "Two"]
    assert book.notes == ["The XML spreadsheet is damaged or ends abruptly. Everything that could be recovered was kept."]


def test_a_document_that_is_not_xml_at_all_is_refused_with_the_reason():
    with pytest.raises(UnreadableWorkbook, match="The Excel 2003 XML file could not be read"):
        parse(b"<Workbook")


def test_too_many_sheets_are_refused(monkeypatch):
    monkeypatch.setattr(config, "MAX_SHEETS", 2)
    body = "".join(sheet(f"S{i}", "<Row>" + cell("a") + "</Row>") for i in range(3))
    with pytest.raises(UnreadableWorkbook, match="too many sheets"):
        parse(doc(body))


def test_the_pieces_arrive_in_chunks_without_changing_the_result():
    rows = "".join("<Row>" + cell(f"row {i}") + cell(str(i), "Number") + "</Row>" for i in range(6000))
    s = parse(doc(sheet("Big", rows))).sheets[0]                                         # larger than one 64 KB chunk
    assert len(s.rows) == 6000 and s.rows[5999] == ["row 5999", 5999.0]


def test_through_the_workbook_reader_and_the_file_name_does_not_matter():
    xml = doc(sheet("S", "<Row>" + cell("a") + cell("1.5", "Number") + "</Row>"))
    for name in ("t.xls", "t.xml", "t.xlsx"):
        wb = read_workbook(xml, name)
        assert wb.format == "spreadsheetml" and wb.sheets[0].cells[0] == ["a", 1.5]
