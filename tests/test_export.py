"""The files people take away: HTML report, Excel workbook, CSV, SQLite and the ZIP. They are opened with independent
readers (openpyxl, sqlite3, csv, an HTML parser), the way Excel, a database or a browser would."""

from __future__ import annotations

import csv
import io
import re
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from contextlib import closing
from datetime import UTC, date, datetime
from html.parser import HTMLParser

import numpy as np
import pytest

from instatkit import demo, i18n
from instatkit.export.bundle import bundle_bytes
from instatkit.export.excel_export import excel_bytes
from instatkit.export.html_report import build_report
from instatkit.export.tables import sqlite_bytes, tidy_csv, wide_csv
from instatkit.export.xlsx_writer import Workbook, _cell_xml, _text, sheet_names
from instatkit.pipeline import SourceInfo, process_bytes

from .conftest import process_demo

openpyxl = pytest.importorskip("openpyxl")
DEMOS = list(demo.DEMOS)
FORBIDDEN = set("[]:*?/\\")


@pytest.mark.parametrize("lang", ["en", "sq"])
@pytest.mark.parametrize("name", DEMOS)
def test_workbook_opens_like_excel_would(name, lang):
    pf = process_demo(name, lang)
    with i18n.using(lang):
        book = openpyxl.load_workbook(io.BytesIO(excel_bytes(pf)))
    assert len(book.sheetnames) == len({n.lower() for n in book.sheetnames})
    for sheet in book.sheetnames:
        assert 0 < len(sheet) <= 31 and not FORBIDDEN & set(sheet), sheet
    data = book[book.sheetnames[1]]
    header = [c.value for c in data[1]]
    assert "value" in header and "period" in header
    col = header.index("value") + 1
    values = [r[col - 1].value for r in data.iter_rows(min_row=2) if r[col - 1].value is not None]
    assert values and all(isinstance(v, int | float) for v in values), "numbers must be stored as numbers, not text"
    assert data.max_row - 1 == len(pf.tables[0].table.localized_df())
    assert data.freeze_panes == "A2" and data.auto_filter.ref


def test_workbook_dates_are_real_dates():
    pf = process_demo("cpi")
    book = openpyxl.load_workbook(io.BytesIO(excel_bytes(pf)))
    data = book[book.sheetnames[1]]
    header = [c.value for c in data[1]]
    ps = header.index("period_start")
    assert isinstance(data.cell(2, ps + 1).value, str)        # exported as ISO text so that every program reads it the same


@pytest.mark.parametrize("name", DEMOS)
def test_csv_has_bom_and_round_trips(name):
    pf = process_demo(name)
    for pt in pf.tables:
        for raw, df in ((tidy_csv(pt), pt.table.localized_df()), (wide_csv(pt), pt.table.to_wide())):
            assert raw.startswith(b"\xef\xbb\xbf"), "Excel on Windows needs the BOM to show ë and ç"
            rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
            assert len(rows) - 1 == len(df)
            assert len(rows[0]) >= 3


def test_csv_keeps_albanian_letters():
    pf = process_demo("wages", "sq")
    with i18n.using("sq"):
        text = tidy_csv(pf.tables[0]).decode("utf-8-sig")
    assert "Bujqësia" in text and "Meshkuj" in text


@pytest.mark.parametrize("name", DEMOS)
def test_sqlite_matches_the_tables(name):
    pf = process_demo(name)
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.deserialize(sqlite_bytes(pf))
        assert conn.execute("select count(*) from datasets").fetchone()[0] == len(pf.tables)
        for pt in pf.tables:
            n = conn.execute("select count(*) from observations where dataset_id=?", (pt.dataset_id,)).fetchone()[0]
            assert n == len(pt.table.df)
            s = conn.execute("select count(*) from series where dataset_id=?", (pt.dataset_id,)).fetchone()[0]
            assert s == pt.table.df["series_id"].nunique()
            total = conn.execute("select sum(value) from observations where dataset_id=?", (pt.dataset_id,)).fetchone()[0]
            assert total == pytest.approx(float(pt.table.df["value"].sum()))
        assert conn.execute("pragma integrity_check").fetchone()[0] == "ok"


@pytest.mark.parametrize("name", ["cpi", "gdp", "wages"])
def test_zip_bundle(name):
    pf = process_demo(name)
    with zipfile.ZipFile(io.BytesIO(bundle_bytes(pf))) as z:
        assert z.testzip() is None
        names = set(z.namelist())
        assert {"report.html", "workbook.xlsx", "data.sqlite"} <= names
        for i in range(1, len(pf.tables) + 1):
            assert {f"table{i}-tidy.csv", f"table{i}-wide.csv", f"table{i}-briefing.md"} <= names
        openpyxl.load_workbook(io.BytesIO(z.read("workbook.xlsx")))


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.errors, self.scripts, self.links = [], [], [], []
        self.tag_names, self.attr_names = set(), set()
        self._void = {"meta", "br", "hr", "img", "link", "input"}

    def handle_starttag(self, tag, attrs):
        self.tag_names.add(tag)
        self.attr_names.update(name for name, _v in attrs)
        if tag == "script":
            self.scripts.append(dict(attrs))
        if tag == "a":
            self.links.append(dict(attrs).get("href"))
        if tag not in self._void:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag in self._void:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append((tag, list(self.stack[-3:])))
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
        else:
            self.stack.pop()


@pytest.mark.parametrize("lang", ["en", "sq"])
@pytest.mark.parametrize("name", DEMOS)
def test_report_is_well_formed_and_offline(name, lang):
    with i18n.using(lang):
        html = build_report(process_demo(name, lang))
    tags = _Tags()
    tags.feed(html)
    assert tags.errors == [] and tags.stack == [], (tags.errors[:3], tags.stack)
    assert html.startswith("<!doctype html>") and f'lang="{lang}"' in html
    assert not re.search(r'(?:src|href)="https?://', html), "a report must not load anything from the internet"
    assert len(tags.scripts) == 1 and "src" not in tags.scripts[0]            # only the embedded hover script
    assert "INSTAT" in html


def _hostile_workbook():
    evil = '<script>alert(1)</script>'
    wb = Workbook()
    ws = wb.active
    ws["A1"] = f"Title {evil} & \"quoted\" <b>bold</b>"
    ws["A2"] = "Hostile table"
    ws.cell(4, 1, "Region")
    for j, h in enumerate([" 01-23", " 02-23", " 03-23"], 2):
        ws.cell(4, j, h)
    for i, name in enumerate([f"A{evil}", 'B" onmouseover="x', "C & D <i>x</i>", "=HYPERLINK(\"http://evil\")"], 5):
        ws.cell(i, 1, name)
        for j in range(2, 5):
            ws.cell(i, j, float(i * j))
    return wb.save()


def test_hostile_text_is_escaped_everywhere():
    pf = process_bytes(_hostile_workbook(), 'bad"<name>.xlsx', source=SourceInfo('bad"<name>.xlsx', "", 1, "upload"))
    assert pf.ok, pf.errors
    html = build_report(pf)
    assert "<script>alert" not in html
    tags = _Tags()
    tags.feed(html)
    assert len(tags.scripts) == 1 and tags.errors == []
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    # parsed the way a browser would: no tag, handler or attribute came out of the data
    assert not {"b", "i"} & tags.tag_names and not {a for a in tags.attr_names if a.startswith("on")}
    book = openpyxl.load_workbook(io.BytesIO(excel_bytes(pf)))
    assert book.sheetnames
    # an Excel formula typed as a label is stored as text in the workbook, so it can never run
    values = [c.value for row in book[book.sheetnames[1]].iter_rows() for c in row if isinstance(c.value, str)]
    assert any(v.startswith("=HYPERLINK") for v in values)
    cells = [c for row in book[book.sheetnames[1]].iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("=")]
    assert all(c.data_type == "s" for c in cells)


# --- the hand-written XLSX writer -----------------------------------------------------------------------------------

def test_numpy_numbers_are_written_as_numbers():
    """numpy scalars are written as numbers, not as their repr or as text."""
    assert _cell_xml("A1", np.float64(1.5), 0, 1) == '<c r="A1"><v>1.5</v></c>'
    assert _cell_xml("A1", np.int64(7), 0, 1) == '<c r="A1"><v>7</v></c>'
    assert _cell_xml("A1", np.float32(0.5), 0, 1) == '<c r="A1"><v>0.5</v></c>'
    assert _cell_xml("A1", float("nan"), 0, 1) == "" and _cell_xml("A1", np.float64("inf"), 0, 1) == ""
    assert _cell_xml("A1", True, 0, 1) == '<c r="A1" t="b"><v>1</v></c>'
    assert 't="inlineStr"' in _cell_xml("A1", "text", 0, 1) and _cell_xml("A1", "", 0, 1) == ""


def test_illegal_characters_and_long_text_are_made_safe():
    assert _text("a\x00b\x0bc\ud800d") == "abcd"
    assert len(_text("x" * 40_000)) == 32_767
    xml = _cell_xml("A1", "  padded & <tagged>\n", 0, 1)
    ET.fromstring(f'<root xmlns="x">{xml}</root>')
    assert 'xml:space="preserve"' in xml


def test_timezone_aware_datetimes_are_kept():
    aware = datetime(2024, 3, 1, 12, 0, tzinfo=UTC)
    assert _cell_xml("A1", aware, 0, 5).startswith('<c r="A1" s="5"><v>45352.5')
    assert _cell_xml("A1", date(2024, 3, 1), 0, 5) == '<c r="A1" s="5"><v>45352.0</v></c>'


def test_sheet_names_follow_excel_rules():
    names = sheet_names(["Data", "data", "A/B:C*D?[E]", "x" * 50, "'quoted'", "", "x" * 50])
    assert len(names) == len({n.lower() for n in names})
    for n in names:
        assert 0 < len(n) <= 31 and not FORBIDDEN & set(n) and not n.startswith("'") and not n.endswith("'")


def test_workbook_xml_is_valid_with_awkward_sheet_titles():
    wb = Workbook()
    wb.active.title = 'Tabela "A" & <B>'
    wb.create_sheet("Data").cell(1, 1, 1)
    wb.create_sheet("data").cell(1, 1, 2)
    wb.create_sheet("x" * 60).cell(1, 1, 3)
    with zipfile.ZipFile(io.BytesIO(wb.save())) as z:
        for part in z.namelist():
            ET.fromstring(z.read(part))                              # every part is well-formed XML
        sheets = [e.get("name") for e in ET.fromstring(z.read("xl/workbook.xml")).iter() if e.tag.endswith("}sheet")]
    assert len(sheets) == 4 and len({s.lower() for s in sheets}) == 4 and all(len(s) <= 31 for s in sheets)
    openpyxl.load_workbook(io.BytesIO(wb.save()))


def test_streamed_rows_and_formats():
    wb = Workbook()
    ws = wb.active
    ws.rows_from(["a", "b"], ([i, i * 0.5] for i in range(1, 2001)))
    ws.freeze_header = ws.autofilter = True
    book = openpyxl.load_workbook(io.BytesIO(wb.save()))
    sheet = book.active
    assert sheet.max_row == 2001 and sheet["B2001"].value == 1000.0 and sheet.auto_filter.ref == "A1:B2001"
