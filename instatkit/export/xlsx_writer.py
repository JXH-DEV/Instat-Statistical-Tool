"""A minimal ``.xlsx`` writer on the standard library (zipfile), no openpyxl.

It writes exactly what this tool needs: text (inline strings, so there is no shared-string table to hold in memory),
numbers, booleans, real dates, a handful of cell styles, merged ranges, column widths, a frozen header row and an
autofilter. Rows can be streamed from a generator, so a large export never sits in memory as cell objects.

The :class:`Workbook` / :class:`Sheet` calls mirror the small part of openpyxl the demo builders use
(``ws["A1"] = v``, ``ws.cell(r, c, v)``, ``ws.merge_cells(...)``), which keeps those builders readable.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from xml.sax.saxutils import escape

from ..excel.grid import col_letter

_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")  # characters XML 1.0 cannot carry
_A1 = re.compile(r"([A-Za-z]+)(\d+)$")
_EPOCH = datetime(1899, 12, 30)
MAX_ROWS = 1_048_576
MAX_TEXT = 32_767  # characters in one Excel cell


@dataclass(frozen=True)
class Style:
    bold: bool = False
    color: str | None = None  # font colour, RRGGBB
    fill: str | None = None  # background colour, RRGGBB
    fmt: str | None = None  # number format code
    wrap: bool = False


class _Cell:
    __slots__ = ("value", "style")

    def __init__(self, value: object = None, style: Style | None = None) -> None:
        self.value, self.style = value, style

    @property
    def fill(self) -> str | None:
        return self.style.fill if self.style else None

    @fill.setter
    def fill(self, rgb: str) -> None:  # a styled but empty cell, as real INSTAT sheets have in their "ghost" columns
        self.style = Style(fill=rgb)


class _Styles:
    """Registry of the distinct cell styles used; index 0 is the default style."""

    def __init__(self) -> None:
        self._index: dict[Style, int] = {Style(): 0}

    def index(self, style: Style | None) -> int:
        if style is None:
            return 0
        return self._index.setdefault(style, len(self._index))

    def xml(self) -> str:
        styles = list(self._index)
        fonts = list(dict.fromkeys((s.bold, s.color) for s in styles))
        fills = list(dict.fromkeys(s.fill for s in styles if s.fill))
        fmts = list(dict.fromkeys(s.fmt for s in styles if s.fmt))
        font_xml = "".join(
            "<font>" + ("<b/>" if b else "") + '<sz val="11"/>' + (f'<color rgb="FF{c}"/>' if c else "") + '<name val="Calibri"/></font>'
            for b, c in fonts)
        fill_xml = '<fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>' + "".join(
            f'<fill><patternFill patternType="solid"><fgColor rgb="FF{rgb}"/><bgColor indexed="64"/></patternFill></fill>' for rgb in fills)
        fmt_xml = "".join(f'<numFmt numFmtId="{164 + i}" formatCode="{escape(code, {chr(34): "&quot;"})}"/>' for i, code in enumerate(fmts))
        xfs = []
        for s in styles:
            font = fonts.index((s.bold, s.color))
            fill = 2 + fills.index(s.fill) if s.fill else 0
            fmt = 164 + fmts.index(s.fmt) if s.fmt else 0
            align = '<alignment vertical="top" wrapText="1"/>' if s.wrap else ""
            xfs.append(f'<xf numFmtId="{fmt}" fontId="{font}" fillId="{fill}" borderId="0" xfId="0" applyNumberFormat="1" '
                       'applyFont="1" applyFill="1"' + (f' applyAlignment="1">{align}</xf>' if align else "/>"))
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/'
                'spreadsheetml/2006/main">' + (f'<numFmts count="{len(fmts)}">{fmt_xml}</numFmts>' if fmts else "") +
                f'<fonts count="{len(fonts)}">{font_xml}</fonts><fills count="{2 + len(fills)}">{fill_xml}</fills>'
                '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                f'<cellXfs count="{len(xfs)}">{"".join(xfs)}</cellXfs>'
                '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')


def _serial(d: date | datetime) -> float | None:
    """Excel's date serial, or ``None`` for NaT and other values that are not a real date."""
    try:
        if not isinstance(d, datetime):
            d = datetime(d.year, d.month, d.day)
        x = (d - _EPOCH).total_seconds() / 86400
    except (TypeError, ValueError, AttributeError):
        return None
    return x if x == x else None


def _text(value: str) -> str:
    return escape(_ILLEGAL.sub("", value)[:MAX_TEXT])


def _cell_xml(ref: str, value: object, s: int, dates: int) -> str:
    """One ``<c>`` element; ``''`` for values that are not written (None, NaN)."""
    attr = f' s="{s}"' if s else ""
    if value is None:
        return f'<c r="{ref}"{attr}/>' if s else ""
    if isinstance(value, bool):
        return f'<c r="{ref}"{attr} t="b"><v>{int(value)}</v></c>'
    if isinstance(value, (int, float)):
        if value != value or value in (float("inf"), float("-inf")):  # NaN / infinity have no spreadsheet form
            return ""
        return f'<c r="{ref}"{attr}><v>{value!r}</v></c>'
    if isinstance(value, (date, datetime)):  # a pandas Timestamp is a datetime; NaT is one too, but has no serial
        serial = _serial(value)
        return "" if serial is None else f'<c r="{ref}" s="{dates}"><v>{serial!r}</v></c>'
    text = str(value)
    if not text:
        return ""
    keep = ' xml:space="preserve"' if text != text.strip() or "\n" in text or "  " in text else ""
    return f'<c r="{ref}"{attr} t="inlineStr"><is><t{keep}>{_text(text)}</t></is></c>'


class Sheet:
    """One worksheet. Fill it cell by cell (``cell``/``[]``), or stream rows with :meth:`rows_from`."""

    def __init__(self, title: str) -> None:
        self.title = title
        self.cells: dict[tuple[int, int], _Cell] = {}
        self.merges: list[str] = []
        self.widths: dict[int, float] = {}
        self.freeze_header = False
        self.autofilter = False
        self.column_styles: dict[int, Style] = {}  # style of every body cell in a streamed column
        self.header_style: Style | None = None
        self._stream: Iterable[list] | None = None
        self._n_cols = 0
        self._last_row = 1

    # cell API (1-based, like a spreadsheet)
    def cell(self, row: int, column: int, value: object = None) -> _Cell:
        c = self.cells.setdefault((row, column), _Cell())
        if value is not None:
            c.value = value
        return c

    def __setitem__(self, ref: str, value: object) -> None:
        m = _A1.match(ref)
        if not m:
            raise ValueError(f"not a cell reference: {ref!r}")
        col = 0
        for ch in m.group(1).upper():
            col = col * 26 + ord(ch) - 64
        self.cell(int(m.group(2)), col, value)

    def merge_cells(self, ref: str | None = None, *, start_row: int = 0, start_column: int = 0, end_row: int = 0,
                    end_column: int = 0) -> None:
        self.merges.append(ref or f"{col_letter(start_column - 1)}{start_row}:{col_letter(end_column - 1)}{end_row}")

    # streaming API (header + rows from an iterable, for exports)
    def rows_from(self, header: list[str], rows: Iterable[list]) -> None:
        self.cell(1, 1)  # reserve the header row
        for j, h in enumerate(header, 1):
            self.cell(1, j, h)
        self._n_cols, self._stream = len(header), rows

    # serialisation
    def _xml_rows(self, styles: _Styles, dates: int) -> Iterator[str]:
        by_row: dict[int, dict[int, _Cell]] = {}
        for (r, c), cell in self.cells.items():
            by_row.setdefault(r, {})[c] = cell
        body_styles = [styles.index(self.column_styles.get(j)) for j in range(self._n_cols)]
        for r in sorted(by_row):
            parts = []
            for c in sorted(by_row[r]):
                cell = by_row[r][c]
                style = self.header_style if (self._stream is not None and r == 1) else cell.style
                parts.append(_cell_xml(f"{col_letter(c - 1)}{r}", cell.value, styles.index(style), dates))
            yield f'<row r="{r}">{"".join(parts)}</row>'
            if r == 1 and self._stream is not None:
                for i, row in enumerate(self._stream, 2):
                    if i > MAX_ROWS:
                        break
                    self._last_row = i
                    yield f'<row r="{i}">' + "".join(
                        _cell_xml(f"{col_letter(j)}{i}", v, body_styles[j], dates) for j, v in enumerate(row[: self._n_cols])) + "</row>"

    def xml_chunks(self, styles: _Styles, dates: int) -> Iterator[str]:
        yield ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/'
               'spreadsheetml/2006/main">')
        if self.freeze_header:
            yield ('<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
                   'state="frozen"/></sheetView></sheetViews>')
        if self.widths:
            yield "<cols>" + "".join(f'<col min="{c}" max="{c}" width="{w:g}" customWidth="1"/>' for c, w in sorted(self.widths.items())) + "</cols>"
        yield "<sheetData>"
        batch: list[str] = []
        for row in self._xml_rows(styles, dates):
            batch.append(row)
            if len(batch) >= 500:
                yield "".join(batch)
                batch.clear()
        yield "".join(batch) + "</sheetData>"
        if self.autofilter and self._n_cols:
            yield f'<autoFilter ref="A1:{col_letter(self._n_cols - 1)}{self._last_row}"/>'
        if self.merges:
            yield f'<mergeCells count="{len(self.merges)}">' + "".join(f'<mergeCell ref="{m}"/>' for m in self.merges) + "</mergeCells>"
        yield "</worksheet>"


class Workbook:
    def __init__(self, title: str = "INSTAT Explorer") -> None:
        self.title = title
        self.sheets: list[Sheet] = [Sheet("Sheet")]  # like a fresh spreadsheet: one sheet to start with

    @property
    def active(self) -> Sheet:
        return self.sheets[0]

    def create_sheet(self, title: str) -> Sheet:
        self.sheets.append(Sheet(title))
        return self.sheets[-1]

    def save(self) -> bytes:
        styles = _Styles()
        dates = styles.index(Style(fmt="yyyy-mm-dd"))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            n = len(self.sheets)
            zf.writestr("[Content_Types].xml", (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.'
                          f'spreadsheetml.worksheet+xml"/>' for i in range(1, n + 1)) + "</Types>"))
            zf.writestr("_rels/.rels", (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                "</Relationships>"))
            zf.writestr("docProps/core.xml", (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
                'metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>' + _text(self.title) +
                "</dc:title><dc:creator>INSTAT Explorer</dc:creator></cp:coreProperties>"))
            zf.writestr("xl/workbook.xml", (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                + "".join(f'<sheet name="{_text(s.title)}" sheetId="{i}" r:id="rId{i}"/>' for i, s in enumerate(self.sheets, 1)) + "</sheets></workbook>"))
            zf.writestr("xl/_rels/workbook.xml.rels", (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                          f'Target="worksheets/sheet{i}.xml"/>' for i in range(1, n + 1))
                + f'<Relationship Id="rId{n + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
                  'Target="styles.xml"/></Relationships>'))
            for i, sheet in enumerate(self.sheets, 1):
                with zf.open(f"xl/worksheets/sheet{i}.xml", "w") as part:
                    for chunk in sheet.xml_chunks(styles, dates):
                        part.write(chunk.encode("utf-8"))
            zf.writestr("xl/styles.xml", styles.xml())  # last: the styles are only known once every sheet was written
        return buf.getvalue()
