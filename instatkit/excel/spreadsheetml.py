"""Reader for Excel 2003 "XML Spreadsheet" (SpreadsheetML) documents, on expat callbacks (no lxml).

INSTAT publishes part of its legacy census tables under an ``.xls`` name although the bytes are a SpreadsheetML XML
document, which neither xlrd nor openpyxl can open. Positions follow the SpreadsheetML rules: a ``Row``/``Cell``/
``Column`` without ``ss:Index`` continues after the previous one, a cell with ``ss:MergeAcross`` pushes the next cell to
the right, and the cells a merge covers are simply not written.
"""

from __future__ import annotations

from datetime import datetime
from xml.etree import ElementTree as ET

from .. import config
from ..i18n import tr
from .raw import ParsedBook, SheetBuilder, UnreadableWorkbook
from .xmlparse import Target

_PROPS = {"Title": "title", "Author": "creator", "Created": "created", "LastSaved": "modified"}
_HIDDEN_SHEET = frozenset(("SheetHidden", "SheetVeryHidden"))


def _attr(attrib: dict, name: str) -> str | None:
    """Attribute by local name: the ``ss:`` prefix is a namespace, and some writers leave it out."""
    for key, value in attrib.items():
        if key == name or key.endswith("}" + name):
            return value
    return None


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def _typed(kind: str, text: str) -> object:
    """The value of a ``Data`` element (``ss:Type`` String / Number / DateTime / Boolean / Error)."""
    if kind == "String":
        return text
    text = text.strip()
    if not text:
        return None
    if kind == "Number":
        try:
            return float(text)
        except ValueError:
            return text
    if kind == "DateTime":
        try:
            stamp = datetime.fromisoformat(text.rstrip("Zz"))
        except ValueError:
            return text
        return stamp.time() if stamp.year <= 1900 else stamp  # 1899-12-31 / 1900-01-00 is Excel's "time of day"
    if kind == "Boolean":
        return text.lower() in ("1", "true")
    return text


class _Target(Target):
    """Expat target: cells go straight into a :class:`SheetBuilder`; no tree is built."""

    def __init__(self) -> None:
        super().__init__()
        self.sheets: list[SheetBuilder] = []
        self.props: dict[str, str] = {}
        self.sb: SheetBuilder | None = None  # the worksheet being read
        self._fmt: dict[str, str] = {}  # style id -> number format
        self._parent: dict[str, str] = {}  # style id -> parent style id
        self._style = ""
        self._stack: list[str] = []
        self._col = self._row_ptr = self._row = self._cell_ptr = 0
        self._cell: tuple[int, int, int, str | None] | None = None  # column, merge across, merge down, style id
        self._kind = "String"
        self._value: object = None
        self._buf: list[str] | None = None
        self._comment = 0

    # expat callbacks
    def start(self, tag: str, attrib: dict) -> None:
        n = self._names[tag]
        self._stack.append(n)
        if n == "Worksheet":
            if len(self.sheets) >= config.MAX_SHEETS:
                raise UnreadableWorkbook(tr("This workbook has too many sheets to be read safely."))
            self.sb = SheetBuilder(_attr(attrib, "Name") or f"Sheet{len(self.sheets) + 1}")
            self._col = self._row_ptr = 0
        elif n == "Style":
            self._style = _attr(attrib, "ID") or ""
            if parent := _attr(attrib, "Parent"):
                self._parent[self._style] = parent
        elif n == "NumberFormat" and self._style:
            self._fmt[self._style] = _attr(attrib, "Format") or ""
        elif n in _PROPS or n == "Visible":
            self._buf = []
        elif self.sb is not None:
            self._start_in_sheet(n, attrib, self.sb)

    def _start_in_sheet(self, n: str, attrib: dict, sb: SheetBuilder) -> None:
        if n == "Column":
            first = _int(_attr(attrib, "Index"), self._col + 1) - 1
            span = max(0, _int(_attr(attrib, "Span"), 0))
            if _attr(attrib, "Hidden") == "1":
                sb.hide_cols(first, first + span)
            self._col = first + span + 1
        elif n == "Row":
            self._row = max(0, _int(_attr(attrib, "Index"), self._row_ptr + 1) - 1)
            self._row_ptr = self._row + 1 + max(0, _int(_attr(attrib, "Span"), 0))
            self._cell_ptr = 0
            if _attr(attrib, "Hidden") == "1":
                sb.hide_row(self._row)
        elif n == "Cell":
            col = max(0, _int(_attr(attrib, "Index"), self._cell_ptr + 1) - 1)
            across, down = max(0, _int(_attr(attrib, "MergeAcross"), 0)), max(0, _int(_attr(attrib, "MergeDown"), 0))
            self._cell_ptr = col + across + 1
            self._cell, self._value = (col, across, down, _attr(attrib, "StyleID")), None
        elif n == "Comment":
            self._comment += 1
        elif n == "Data" and not self._comment:
            self._kind, self._buf = _attr(attrib, "Type") or "String", []

    def data(self, text: str) -> None:
        if self._buf is not None:
            self._buf.append(text)

    def end(self, tag: str) -> None:
        n = self._names[tag]
        self._stack.pop()
        parent = self._stack[-1] if self._stack else ""
        sb = self.sb
        if n == "Worksheet" and sb is not None:
            self.sheets.append(sb)
            self.sb = None
        elif n in _PROPS and self._buf is not None:
            text, self._buf = "".join(self._buf).strip(), None
            if parent == "DocumentProperties" and text:
                self.props[_PROPS[n]] = text
        elif n == "Visible" and self._buf is not None:
            text, self._buf = "".join(self._buf).strip(), None
            if sb is not None:
                sb.visible = text not in _HIDDEN_SHEET
        elif n == "Data" and self._buf is not None and not self._comment:
            self._value, self._buf = _typed(self._kind, "".join(self._buf)), None
        elif n == "Comment":
            self._comment -= 1
        elif n == "Cell" and sb is not None and self._cell is not None:
            col, across, down, style = self._cell
            self._cell = None
            if self._value is not None:
                sb.put(self._row, col, self._value, isinstance(self._value, float) and self._is_pct(style))
            sb.merge(self._row, col, self._row + down, col + across)

    def close(self) -> None:
        if self.sb is not None:  # truncated document: keep the sheet that was being read
            self.sheets.append(self.sb)
            self.sb = None

    # helpers
    def _is_pct(self, style: str | None) -> bool:
        for _ in range(8):  # ss:Parent inheritance
            if not style:
                return False
            if style in self._fmt:
                return "%" in self._fmt[style] or self._fmt[style].strip().lower() == "percent"
            style = self._parent.get(style)
        return False


def parse(data: bytes) -> ParsedBook:
    """Parse a SpreadsheetML document into raw sheets, document properties and reader notes."""
    target = _Target()
    parser = ET.XMLParser(target=target)
    notes: list[str] = []
    try:
        for i in range(0, len(data), 1 << 16):
            parser.feed(data[i:i + (1 << 16)])
        parser.close()
    except ET.ParseError as exc:
        if not target.sheets and target.sb is None:
            raise UnreadableWorkbook(tr("The Excel 2003 XML file could not be read: {error}", error=exc)) from exc
        notes.append(tr("The XML spreadsheet is damaged or ends abruptly. Everything that could be recovered was kept."))
        target.close()
    return ParsedBook([sb.finish() for sb in target.sheets], target.props, notes)
