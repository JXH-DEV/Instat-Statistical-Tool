"""The ``.xlsx`` reader on packages assembled by hand (so every cell type, format, relationship and limit is known) and on workbooks written by
openpyxl, an independent writer: what each cell holds, which cells are dates or percentages, merges, hidden rows, columns and sheets, the
epoch, the size limits, and the words used when a package is damaged or incomplete."""

from __future__ import annotations

import datetime
import io
import zipfile

import pytest

from instatkit import config
from instatkit.excel import xlsx
from instatkit.excel.grid import read_workbook
from instatkit.excel.raw import UnreadableWorkbook

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"


def rels(*items: tuple[str, str, str]) -> str:
    inner = "".join(f'<Relationship Id="{i}" Type="{TYPE}{t}" Target="{target}"/>' for i, t, target in items)
    return f'<Relationships xmlns="{PKG}">{inner}</Relationships>'


def package(sheets, *, shared: str = "", styles: str = "", workbook_pr: str = "", core: str = "", extra: dict | None = None,
            compression: int = zipfile.ZIP_STORED) -> bytes:
    """``sheets`` are ``(name, state, xml)`` triples, ``xml`` being the children of ``<worksheet>``."""
    sheets = [(s if len(s) == 3 else (s[0], "", s[1])) for s in sheets]
    items = [(f"rId{i}", "worksheet", f"worksheets/sheet{i}.xml") for i, _ in enumerate(sheets, 1)]
    parts = {"_rels/.rels": rels(("rId1", "officeDocument", "xl/workbook.xml")),
             "xl/workbook.xml": (f'<workbook xmlns="{MAIN}" xmlns:r="{REL}">{workbook_pr}<sheets>' + "".join(
                 f'<sheet name="{n}" sheetId="{i}"' + (f' state="{st}"' if st else "") + f' r:id="rId{i}"/>' for i, (n, st, _x) in enumerate(sheets, 1))
                 + "</sheets></workbook>")}
    for i, (_n, _st, body) in enumerate(sheets, 1):
        parts[f"xl/worksheets/sheet{i}.xml"] = f'<worksheet xmlns="{MAIN}">{body}</worksheet>'
    if shared:
        items.append(("rIdS", "sharedStrings", "sharedStrings.xml"))
        parts["xl/sharedStrings.xml"] = f'<sst xmlns="{MAIN}">{shared}</sst>'
    if styles:
        items.append(("rIdT", "styles", "styles.xml"))
        parts["xl/styles.xml"] = f'<styleSheet xmlns="{MAIN}">{styles}</styleSheet>'
    parts["xl/_rels/workbook.xml.rels"] = rels(*items)
    if core:
        parts["docProps/core.xml"] = f'<cp:coreProperties xmlns:cp="http://x/cp" xmlns:dc="http://x/dc" xmlns:dcterms="http://x/dcterms">{core}</cp:coreProperties>'
    parts.update(extra or {})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as z:
        for name, text in parts.items():
            z.writestr(name, text)
    return buf.getvalue()


def one(body: str, **kwargs):
    return xlsx.parse(package([("S", body)], **kwargs)).sheets[0]


def rows_of(cells: str, **kwargs):
    return one(f"<sheetData>{cells}</sheetData>", **kwargs)


def c(ref: str, value: str, t: str = "", s: str = "") -> str:
    return f'<c r="{ref}"' + (f' t="{t}"' if t else "") + (f' s="{s}"' if s else "") + f"><v>{value}</v></c>"


# --- values ---
def test_each_type_of_cell():
    shared = "<si><t>Tiranë</t></si>"
    cells = ("<row r=\"1\">" + c("A1", "0", "s") + '<c r="B1" t="inlineStr"><is><t>inline</t></is></c>' + c("C1", "from a formula", "str")
             + c("D1", "#N/A", "e") + c("E1", "1", "b") + c("F1", "0", "b") + c("G1", "12.5") + c("H1", "2023-04-30T00:00:00Z", "d")
             + c("I1", "not a date", "d") + c("J1", "abc") + c("K1", " 1 ", "b") + c("L1", "true", "b") + c("M1", "1.5e3") + "</row>")
    got = rows_of(cells, shared=shared).rows[0]
    assert got == ["Tiranë", "inline", "from a formula", "#N/A", True, False, 12.5, datetime.datetime(2023, 4, 30), "not a date", "abc",
                   True, True, 1500.0]


def test_a_cell_without_a_stored_value_is_empty():
    sheet = rows_of('<row r="1"><c r="A1"><f>SUM(B1:B2)</f></c><c r="B1"/>' + c("C1", "5") + "</row>")
    assert sheet.rows == [[None, None, 5.0]]


def test_cells_and_rows_without_references_follow_one_another():
    cells = ("<row>" + "<c><v>1</v></c><c><v>2</v></c>" + "</row>" + '<row r="4"><c r="C4"><v>3</v></c><c><v>4</v></c></row>' + "<row><c><v>5</v></c></row>")
    rows = rows_of(cells).rows
    assert rows[0][:2] == [1.0, 2.0]
    assert rows[3] == [None, None, 3.0, 4.0]                              # the cell after C4 is D4
    assert rows[4][0] == 5.0 and len(rows) == 5                           # the row after row 4 is row 5
    assert rows[1] == rows[2] == [None] * 4


def test_references_in_lower_columns_come_back_to_the_left():
    assert rows_of('<row r="1">' + c("C1", "3") + c("A1", "1") + "</row>").rows == [[1.0, None, 3.0]]


def test_columns_are_counted_in_letters():
    sheet = rows_of('<row r="1">' + c("Z1", "1") + c("AA1", "2") + c("AB1", "3") + "</row>")
    assert sheet.rows[0][25:] == [1.0, 2.0, 3.0]


def test_a_row_numbered_zero_has_no_place_in_the_grid():
    sheet = rows_of('<row r="0">' + c("A0", "9") + '</row><row r="1">' + c("B1", "1") + "</row>")
    assert sheet.rows == [[None, 1.0]]


def test_the_row_element_gives_the_row_and_the_reference_only_the_column():
    assert rows_of('<row r="2">' + c("B7", "5") + "</row>").rows == [[None, None], [None, 5.0]]


def test_shared_strings_join_rich_text_and_skip_phonetic_runs():
    shared = ("<si><t>plain</t></si><si><r><t>Ri</t></r><r><rPr/><t>ch</t></r></si>"
              "<si><t>Tokyo</t><rPh sb=\"0\" eb=\"1\"><t>to-kyo</t></rPh></si><si/>")
    cells = ('<row r="1">' + "".join(c(f"{col}1", str(i), "s") for i, col in enumerate("ABCD")) + c("E1", "99", "s") + c("F1", "-1", "s")
             + c("G1", "7") + "</row>")
    assert rows_of(cells, shared=shared).rows[0] == ["plain", "Rich", "Tokyo", "", None, None, 7.0]   # an index outside the table is no text


def test_inline_rich_text_joins_its_runs_and_skips_phonetic_runs():
    cell = '<c r="A1" t="inlineStr"><is><r><t>ab</t></r><r><t>cd</t></r><rPh><t>zz</t></rPh></is></c>'
    next_cell = '<c r="B1" t="inlineStr"><is><t>after</t></is></c>'
    assert rows_of(f'<row r="1">{cell}{next_cell}</row>').rows == [["abcd", "after"]]


# --- number formats ---
def styled(fmt_id: int, code: str | None, value: str = "45000"):
    numfmts = f'<numFmts count="1"><numFmt numFmtId="{fmt_id}" formatCode="{code}"/></numFmts>' if code is not None else ""
    styles = numfmts + f'<cellXfs count="1"><xf numFmtId="{fmt_id}"/></cellXfs>'
    return rows_of('<row r="1">' + c("A1", value, s="0") + "</row>", styles=styles)


@pytest.mark.parametrize("fmt_id, code, kind", [
    (0, None, ""), (1, None, ""), (49, None, ""),
    (9, None, "pct"), (10, None, "pct"),
    (14, None, "date"), (15, None, "date"), (22, None, "date"), (27, None, "date"), (36, None, "date"), (45, None, "date"), (47, None, "date"),
    (50, None, "date"), (58, None, "date"),
    (23, None, ""), (26, None, ""), (37, None, ""), (44, None, ""), (48, None, ""), (49, None, ""), (13, None, ""),
    (164, "0.0%", "pct"), (165, "0%", "pct"), (166, "0.00\\%", ""),     # an escaped percent sign is text: it does not scale the value
    (167, "yyyy\\-mm", "date"), (168, "dd/mm/yyyy", "date"), (169, "h:mm", "date"), (170, "[$-409]mmmm d", "date"), (171, "ss", "date"),
    (172, '0.00&quot; days&quot;', ""),                                    # quoted text is not a date code
    (173, "[Red]0.00", ""),                                                # nor is a colour tag
    (174, '0.00&quot;%&quot;', ""),                                        # nor a quoted percent sign
    (175, "#,##0_d", ""),                                                  # nor is padding
    (176, "#,##0*s0", ""),                                                 # nor a repeat character
    (177, "General", ""), (178, "0.00", ""),
])
def test_a_cell_format_is_a_date_a_percentage_or_neither(fmt_id, code, kind):
    sheet = styled(fmt_id, code)
    if kind == "date":
        assert sheet.rows == [[datetime.datetime(2023, 3, 15)]] and not sheet.pct
    elif kind == "pct":
        assert sheet.rows == [[45000.0]] and sheet.pct == {(0, 0)}
    else:
        assert sheet.rows == [[45000.0]] and not sheet.pct


def test_a_style_that_does_not_exist_is_a_plain_number():
    xfs = '<cellXfs count="1"><xf numFmtId="14"/></cellXfs>'
    sheet = rows_of('<row r="1">' + c("A1", "7", s="1") + c("B1", "8", s="-1") + c("C1", "9", s="0") + "</row>", styles=xfs)
    assert sheet.rows[0][:2] == [7.0, 8.0] and isinstance(sheet.rows[0][2], datetime.datetime)
    assert not sheet.pct


def test_a_workbook_without_styles_has_no_dates_or_percentages():
    assert rows_of('<row r="1">' + c("A1", "45000", s="0") + "</row>").rows == [[45000.0]]


def test_text_in_a_date_cell_stays_text_and_a_number_cell_keeps_its_value():
    styles = '<cellXfs count="1"><xf numFmtId="14"/></cellXfs>'
    assert rows_of('<row r="1">' + c("A1", "abc", s="0") + c("B1", "xyz", "str", s="0") + "</row>", styles=styles).rows == [["abc", "xyz"]]


@pytest.mark.parametrize("serial, expected", [
    ("0.5", datetime.time(12, 0)), ("0.75", datetime.time(18, 0)), ("0", datetime.time(0, 0)), ("0.999988425925926", datetime.time(23, 59, 59)),
    ("1", datetime.datetime(1899, 12, 31)), ("60", datetime.datetime(1900, 2, 28)), ("-1", datetime.datetime(1899, 12, 29)),
    ("45000.5", datetime.datetime(2023, 3, 15, 12, 0)),
])
def test_serial_numbers_become_dates_and_times_of_day(serial, expected):
    styles = '<cellXfs count="1"><xf numFmtId="22"/></cellXfs>'
    assert rows_of('<row r="1">' + c("A1", serial, s="0") + "</row>", styles=styles).rows == [[expected]]


@pytest.mark.parametrize("serial", ["1e12", "-1e12", "1e300", "inf", "-inf", "nan"])
def test_a_serial_that_is_not_a_date_stays_a_number(serial):
    styles = '<cellXfs count="1"><xf numFmtId="14"/></cellXfs>'
    value = rows_of('<row r="1">' + c("A1", serial, s="0") + "</row>", styles=styles).rows[0][0]
    assert isinstance(value, float) and (value != value or abs(value) >= 1e12)


@pytest.mark.parametrize("flag", ["1", "true"])
def test_the_1904_epoch_moves_every_date(flag):
    styles = '<cellXfs count="1"><xf numFmtId="14"/></cellXfs>'
    sheet = rows_of('<row r="1">' + c("A1", "1000", s="0") + "</row>", styles=styles, workbook_pr=f'<workbookPr date1904="{flag}"/>')
    assert sheet.rows == [[datetime.datetime(1904, 1, 1) + datetime.timedelta(days=1000)]]
    other = rows_of('<row r="1">' + c("A1", "1000", s="0") + "</row>", styles=styles, workbook_pr='<workbookPr date1904="0"/>')
    assert other.rows == [[datetime.datetime(1899, 12, 30) + datetime.timedelta(days=1000)]]


# --- structure: merges, hidden rows and columns, row and column limits ---
def test_merged_ranges():
    merges = '<mergeCells count="5"><mergeCell ref="A1:C2"/><mergeCell ref="AA1:AB1"/><mergeCell ref="B5"/><mergeCell ref="bad"/><mergeCell ref="D4:D4"/></mergeCells>'
    sheet = one('<sheetData><row r="1">' + c("A1", "x") + "</row></sheetData>" + merges)
    assert sheet.merged == [(0, 0, 1, 2), (0, 26, 0, 27)]


def test_hidden_rows_and_columns():
    cols = '<cols><col min="2" max="3" hidden="1"/><col min="5" max="5" hidden="true"/><col min="7" max="7"/><col min="9" max="9" hidden="0"/><col hidden="1"/></cols>'
    rows = ('<sheetData><row r="1">' + c("A1", "1") + '</row><row r="2" hidden="1">' + c("A2", "2") + '</row><row r="3" hidden="true"/>'
            '<row r="4" hidden="0">' + c("A4", "4") + "</row></sheetData>")
    sheet = one(cols + rows)
    assert sheet.hidden_rows == {1, 2} and sheet.hidden_cols == {0, 1, 2, 4}


def test_sheets_can_be_visible_hidden_or_very_hidden():
    book = xlsx.parse(package([("A", "", "<sheetData/>"), ("B", "hidden", "<sheetData/>"), ("C", "veryHidden", "<sheetData/>"), ("D", "visible", "<sheetData/>")]))
    assert [(s.name, s.visible) for s in book.sheets] == [("A", True), ("B", False), ("C", False), ("D", True)]


def test_values_beyond_the_row_cap_are_dropped_and_the_sheet_says_so(monkeypatch):
    monkeypatch.setattr(config, "MAX_ROWS", 3)
    rows = "".join(f'<row r="{i}">' + c(f"A{i}", str(i)) + "</row>" for i in range(1, 6))
    sheet = rows_of(rows)
    assert sheet.rows == [[1.0], [2.0], [3.0]] and sheet.truncated


def test_empty_styled_rows_beyond_the_cap_cost_nothing(monkeypatch):
    monkeypatch.setattr(config, "MAX_ROWS", 3)
    sheet = rows_of('<row r="1">' + c("A1", "1") + '</row><row r="9" hidden="1"><c r="A9" s="0"/></row>')
    assert sheet.rows == [[1.0]] and not sheet.truncated and sheet.hidden_rows == set()


def test_the_row_after_the_cap_is_not_counted_from_the_cap_either(monkeypatch):
    monkeypatch.setattr(config, "MAX_ROWS", 3)
    sheet = rows_of('<row r="3">' + c("A3", "3") + "</row><row>" + c("A4", "4") + "</row>")
    assert sheet.rows[2] == [3.0] and sheet.truncated and len(sheet.rows) == 3


def test_columns_beyond_the_cap_are_dropped_and_the_sheet_says_so(monkeypatch):
    monkeypatch.setattr(config, "MAX_COLS", 3)
    sheet = rows_of('<row r="1">' + "".join(c(f"{col}1", str(i)) for i, col in enumerate("ABCDE")) + "</row>")
    assert sheet.rows == [[0.0, 1.0, 2.0]] and sheet.truncated


def test_a_sparse_sheet_cannot_ask_for_a_huge_grid(monkeypatch):
    monkeypatch.setattr(config, "MAX_CELLS", 50)
    sheet = rows_of('<row r="1">' + c("A1", "1") + c("Z1", "2") + "</row>" + '<row r="40">' + c("A40", "3") + "</row>")
    assert sheet.truncated and len(sheet.rows) * len(sheet.rows[0]) <= 50


# --- the package: relationships, properties, limits ---
def test_the_workbook_is_found_through_the_package_relationships():
    rows = f'<worksheet xmlns="{MAIN}"><sheetData><row r="1">' + c("A1", "1") + "</row></sheetData></worksheet>"
    data = package([], extra={
        "_rels/.rels": rels(("a", "officeDocument", "docs/book.xml")),
        "docs/book.xml": f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets><sheet name="Moved" r:id="x1"/></sheets></workbook>',
        "docs/_rels/book.xml.rels": rels(("x1", "worksheet", "../sheets/one.xml")),
        "sheets/one.xml": rows})
    sheet = xlsx.parse(data).sheets[0]
    assert sheet.name == "Moved" and sheet.rows == [[1.0]]


def test_absolute_targets_external_links_and_other_sheet_types_are_handled():
    body = f'<worksheet xmlns="{MAIN}"><sheetData><row r="1">' + c("A1", "1") + "</row></sheetData></worksheet>"
    data = package([], extra={
        "xl/workbook.xml": (f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets><sheet name="Abs" r:id="a"/><sheet name="Out" r:id="e"/>'
                            '<sheet name="Chart" r:id="c"/><sheet name="Orphan" r:id="nothing"/><sheet name="Missing" r:id="m"/></sheets></workbook>'),
        "xl/_rels/workbook.xml.rels": (f'<Relationships xmlns="{PKG}"><Relationship Id="a" Type="{TYPE}worksheet" Target="/xl/s/abs.xml"/>'
                                      f'<Relationship Id="e" Type="{TYPE}worksheet" Target="https://example.org/x.xml" TargetMode="External"/>'
                                      f'<Relationship Id="c" Type="{TYPE}chartsheet" Target="s/abs.xml"/>'
                                      f'<Relationship Id="m" Type="{TYPE}worksheet" Target="s/none.xml"/></Relationships>'),
        "xl/s/abs.xml": body})
    assert [s.name for s in xlsx.parse(data).sheets] == ["Abs"]


def test_a_package_without_any_relationships_is_read_from_the_usual_places():
    data = package([("S", '<sheetData/>')], extra={"_rels/.rels": rels()})
    assert [s.name for s in xlsx.parse(data).sheets] == ["S"]


def test_properties():
    core = ("<dc:title> Wages </dc:title><dc:creator>INSTAT</dc:creator><dcterms:created>2024-01-02T03:04:05Z</dcterms:created>"
            "<dcterms:modified>2024-02-03T00:00:00Z</dcterms:modified><dc:description>not kept</dc:description><dc:subject>  </dc:subject>")
    book = xlsx.parse(package([("S", "<sheetData/>")], core=core))
    assert book.props == {"title": "Wages", "creator": "INSTAT", "created": "2024-01-02T03:04:05Z", "modified": "2024-02-03T00:00:00Z"}
    assert xlsx.parse(package([("S", "<sheetData/>")])).props == {}


def test_too_many_parts_are_refused(monkeypatch):
    monkeypatch.setattr(config, "MAX_ZIP_ENTRIES", 6)
    ok = package([("S", "<sheetData/>")])
    assert xlsx.parse(ok)
    with pytest.raises(UnreadableWorkbook, match="too many parts"):
        xlsx.parse(package([("S", "<sheetData/>")], extra={f"pad{i}.txt": "x" for i in range(10)}))


def test_too_many_sheets_are_refused(monkeypatch):
    monkeypatch.setattr(config, "MAX_SHEETS", 2)
    assert len(xlsx.parse(package([("A", "<sheetData/>"), ("B", "<sheetData/>")])).sheets) == 2
    with pytest.raises(UnreadableWorkbook, match="too many sheets"):
        xlsx.parse(package([("A", "<sheetData/>"), ("B", "<sheetData/>"), ("C", "<sheetData/>")]))


def test_one_size_budget_covers_the_whole_package(monkeypatch):
    """Reading the same sheet through three relationships must cost three times its size, not once."""
    body = f'<worksheet xmlns="{MAIN}"><sheetData>' + "".join(f'<row r="{i}">' + c(f"A{i}", "1") + "</row>" for i in range(1, 40)) + "</sheetData></worksheet>"
    shared = {"xl/worksheets/big.xml": body}

    def book(n: int) -> bytes:
        names = "".join(f'<sheet name="S{i}" r:id="r{i}"/>' for i in range(n))
        links = tuple((f"r{i}", "worksheet", "worksheets/big.xml") for i in range(n))
        return package([], extra={**shared, "xl/workbook.xml": f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>{names}</sheets></workbook>',
                                  "xl/_rels/workbook.xml.rels": rels(*links)})

    def sizes(data: bytes) -> tuple[int, int]:
        z = zipfile.ZipFile(io.BytesIO(data))
        meta = sum(z.getinfo(n).file_size for n in ("_rels/.rels", "xl/_rels/workbook.xml.rels", "xl/workbook.xml"))
        return meta, z.getinfo("xl/worksheets/big.xml").file_size

    meta, big = sizes(book(2))
    assert big > 1000
    monkeypatch.setattr(config, "MAX_XML_BYTES", meta + 2 * big + 1)
    assert len(xlsx.parse(book(2)).sheets) == 2                                              # two reads fit exactly
    with pytest.raises(UnreadableWorkbook, match="too large"):
        xlsx.parse(book(3))


def test_one_part_larger_than_the_metadata_limit_is_refused(monkeypatch):
    monkeypatch.setattr(xlsx, "_META_BYTES", 60)
    with pytest.raises(UnreadableWorkbook, match="too large"):
        xlsx.parse(package([("S", "<sheetData/>")]))


def test_one_sheet_larger_than_the_xml_limit_is_refused(monkeypatch):
    data = package([("S", "<sheetData>" + "".join(f'<row r="{i}">' + c(f"A{i}", "1") + "</row>" for i in range(1, 30)) + "</sheetData>")])
    monkeypatch.setattr(config, "MAX_XML_BYTES", 1500)
    with pytest.raises(UnreadableWorkbook, match="too large"):
        xlsx.parse(data)


@pytest.mark.parametrize("part", ["xl/workbook.xml", "xl/worksheets/sheet1.xml", "xl/styles.xml", "xl/sharedStrings.xml", "_rels/.rels"])
def test_no_part_may_declare_entities(part):
    good = package([("S", "<sheetData/>")], shared="<si><t>a</t></si>", styles="<cellXfs/>")
    z = zipfile.ZipFile(io.BytesIO(good))
    bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><root xmlns="' + MAIN + '"><a>&a;</a></root>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as out:
        for name in z.namelist():
            out.writestr(name, bomb if name == part else z.read(name))
    with pytest.raises(UnreadableWorkbook):
        xlsx.parse(buf.getvalue())


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "1e999"])
def test_a_cell_that_holds_nan_or_infinity_cannot_break_the_pages(bad):
    """Python reads 'nan' and 'inf' as numbers although Excel never writes them; JSON has neither, and a browser would refuse the page."""
    import json

    from instatkit.pipeline import process_bytes
    from instatkit.web import api
    from instatkit.web.common import dumps

    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    values = ["10", "12", "14", bad, "13", "15", "17", "16", "14", "12", "11", "10"]
    head = '<row r="1"><c r="A1" t="inlineStr"><is><t>Month</t></is></c><c r="B1" t="inlineStr"><is><t>Arrivals (thousand)</t></is></c></row>'
    body = "".join(f'<row r="{i}"><c r="A{i}" t="inlineStr"><is><t>{months[i - 2]} 2023</t></is></c>' + c(f"B{i}", v) + "</row>" for i, v in enumerate(values, 2))
    pf = process_bytes(package([("S", f"<sheetData>{head}{body}</sheetData>")]), "t.xlsx")
    assert pf.tables
    for pt in pf.tables:
        for reply in (api.summary(pf, pt), api.explore(pt, {})):
            json.loads(dumps(reply), parse_constant=lambda name: pytest.fail(f"{name} reached the page"))


# --- damage ---
def test_what_is_not_a_zip_is_called_damaged():
    with pytest.raises(UnreadableWorkbook, match="damaged and cannot be opened"):
        xlsx.parse(b"PK\x03\x04 this is not a zip file at all")


def test_a_zip_with_flipped_bytes_is_called_damaged():
    data = bytearray(package([("S", '<sheetData><row r="1">' + c("A1", "1") + "</row></sheetData>")], compression=zipfile.ZIP_DEFLATED))
    info = zipfile.ZipFile(io.BytesIO(bytes(data))).getinfo("xl/worksheets/sheet1.xml")
    start = info.header_offset + 30 + len(info.filename) + len(info.extra)
    for k in range(start, start + info.compress_size):
        data[k] ^= 0xFF
    with pytest.raises(UnreadableWorkbook, match="damaged and cannot be opened"):
        xlsx.parse(bytes(data))


@pytest.mark.parametrize("data", [b"", b"PK\x05\x06" + b"\x00" * 18], ids=["empty", "empty-zip"])
def test_nothing_to_read_is_refused(data):
    with pytest.raises(UnreadableWorkbook):
        xlsx.parse(data)


@pytest.mark.parametrize("parts", [{}, {"a.txt": "x"}, {"_rels/.rels": rels(("r1", "officeDocument", "xl/workbook.xml"))}])
def test_a_package_without_a_workbook_names_the_missing_part(parts):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in parts.items():
            z.writestr(k, v)
    with pytest.raises(UnreadableWorkbook) as info:
        xlsx.parse(buf.getvalue())
    assert str(info.value) == "This is not a complete Excel workbook (the part xl/workbook.xml is missing)."


@pytest.mark.parametrize("cut", ["workbook", "sheet", "styles", "shared"])
def test_xml_that_is_cut_off_is_called_damaged(cut):
    good = package([("S", '<sheetData><row r="1">' + c("A1", "1") + "</row></sheetData>")], shared="<si><t>a</t></si>", styles="<cellXfs/>")
    name = {"workbook": "xl/workbook.xml", "sheet": "xl/worksheets/sheet1.xml", "styles": "xl/styles.xml", "shared": "xl/sharedStrings.xml"}[cut]
    z = zipfile.ZipFile(io.BytesIO(good))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as out:
        for n in z.namelist():
            out.writestr(n, z.read(n)[:-25] if n == name else z.read(n))
    with pytest.raises(UnreadableWorkbook) as info:
        xlsx.parse(buf.getvalue())
    assert str(info.value) == "The workbook is damaged and could not be read (ParseError)."


@pytest.mark.parametrize("body", [
    '<sheetData><row r="abc"><c r="A1"><v>1</v></c></row></sheetData>',
    '<sheetData><row r="1"><c r="A1" t="s"><v>x</v></c></row></sheetData>',
    '<cols><col min="x" max="2" hidden="1"/></cols>',
    '<sheetData><row r="1"><c r="A1" s="x"><v>1</v></c></row></sheetData>',
])
def test_a_value_that_is_not_what_it_should_be_is_called_damaged(body):
    with pytest.raises(UnreadableWorkbook) as info:
        one(body, styles='<cellXfs count="1"><xf numFmtId="0"/></cellXfs>')
    assert str(info.value) == "The workbook is damaged and could not be read (ValueError)."


# --- through openpyxl, an independent writer ---
openpyxl = pytest.importorskip("openpyxl")


def written(build) -> bytes:
    wb = openpyxl.Workbook()
    build(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_a_workbook_written_by_openpyxl():
    def build(wb):
        ws = wb.active
        ws.title = "Data"
        ws["A1"], ws["B1"], ws["C1"], ws["D1"] = "Tiranë", 12.5, True, datetime.datetime(2023, 4, 30)
        ws["E1"] = datetime.time(10, 30)
        ws["A2"], ws["B2"] = 0.255, 3
        ws["A2"].number_format = "0.0%"
        ws["B2"].number_format = "0.00"
        ws.merge_cells("A4:C5")
        ws["A4"] = "Title"
        ws.row_dimensions[2].hidden = True
        ws.column_dimensions["D"].hidden = True
        ws.column_dimensions.group("F", "H", hidden=True)
        hidden = wb.create_sheet("Hidden")
        hidden.sheet_state = "hidden"
        hidden["A1"] = "x"
        very = wb.create_sheet("Very")
        very.sheet_state = "veryHidden"
        very["A1"] = "y"
        wb.properties.title, wb.properties.creator = "Wages", "INSTAT"

    book = xlsx.parse(written(build))
    data, hidden, very = book.sheets
    assert data.rows[0][:5] == ["Tiranë", 12.5, True, datetime.datetime(2023, 4, 30), datetime.time(10, 30)]
    assert data.rows[1][:2] == [0.255, 3.0] and data.pct == {(1, 0)}
    assert data.merged == [(3, 0, 4, 2)] and data.hidden_rows == {1} and data.hidden_cols == {3, 5, 6, 7}
    assert (data.visible, hidden.visible, very.visible) == (True, False, False)
    assert book.props["title"] == "Wages" and book.props["creator"] == "INSTAT" and book.props["created"][:2] == "20"


def test_dates_written_in_the_1904_system_come_back_as_the_same_dates():
    def build(wb):
        wb.epoch = openpyxl.utils.datetime.CALENDAR_MAC_1904
        wb.active["A1"] = datetime.datetime(2023, 4, 30, 6, 0)
        wb.active["A2"] = datetime.datetime(1905, 1, 1)

    sheet = xlsx.parse(written(build)).sheets[0]
    assert sheet.rows == [[datetime.datetime(2023, 4, 30, 6, 0)], [datetime.datetime(1905, 1, 1)]]


def test_through_the_workbook_reader_the_file_name_does_not_matter():
    data = written(lambda wb: wb.active.__setitem__("A1", "x"))
    for name in ("t.xlsx", "t.xlsm", "noextension", "t.XLS"):
        wb = read_workbook(data, name)
        assert wb.format == "xlsx" and wb.sheets[0].cells[0][0] == "x"
