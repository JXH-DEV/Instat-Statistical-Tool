"""Read ``.xlsx`` / ``.xls`` / Excel 2003 XML / ``.csv`` bytes into plain in-memory :class:`Grid` objects.

Everything downstream (layout detection, tidying) works on Grids, so it does not care which format a file came in.
The format readers live in their own modules and are imported only when a file of that kind arrives; all of them fill
the capped :class:`~instatkit.excel.raw.SheetBuilder`, so no input can make a sheet grow without bound.
"""

from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from dataclasses import dataclass, field
from datetime import time, timedelta

from .. import config
from ..i18n import num, tr
from .raw import ParsedBook, RawSheet, SheetBuilder, UnreadableWorkbook, format_problem

__all__ = ["Grid", "Workbook", "UnreadableWorkbook", "col_letter", "format_problem", "read_workbook", "sniff_format"]


@dataclass
class Grid:
    name: str
    cells: list[list[object]]
    merged: list[tuple[int, int, int, int]] = field(default_factory=list)  # (r0, c0, r1, c1) inclusive
    hidden_rows: frozenset[int] = frozenset()
    hidden_cols: frozenset[int] = frozenset()
    pct_cells: frozenset[tuple[int, int]] = frozenset()  # numeric cells formatted as percentages
    visible: bool = True
    truncated: bool = False
    origin: tuple[int, int] = (0, 0)  # (row, col) of cells[0][0] within the original sheet
    warnings: list[str] = field(default_factory=list)

    @property
    def n_rows(self) -> int:
        return len(self.cells)

    @property
    def n_cols(self) -> int:
        return len(self.cells[0]) if self.cells else 0

    def cell(self, r: int, c: int) -> object:
        if 0 <= r < self.n_rows and 0 <= c < self.n_cols:
            return self.cells[r][c]
        return None

    def a1(self, r: int, c: int) -> str:
        """Excel-style reference of a grid cell in the *original* sheet, e.g. ``D7``."""
        return f"{col_letter(c + self.origin[1])}{r + self.origin[0] + 1}"


@dataclass
class Workbook:
    sheets: list[Grid]
    format: str  # xlsx | xls | spreadsheetml (Excel 2003 XML) | csv
    sha256: str = ""
    size: int = 0
    filename: str | None = None
    properties: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def col_letter(c: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    s = ""
    c += 1
    while c:
        c, rem = divmod(c - 1, 26)
        s = chr(65 + rem) + s
    return s


def sniff_format(data: bytes, filename: str | None = None) -> str:
    """Identify what the bytes really are. Servers often return an HTML error page with status 200."""
    head = data[:16]
    if head.startswith(b"PK\x03\x04"):
        try:
            names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
        except (zipfile.BadZipFile, NotImplementedError):  # the latter: a zip written by something newer than zipfile reads
            return "corrupt"
        if "xl/workbook.xml" in names:
            return "xlsx"
        if "xl/workbook.bin" in names:
            return "xlsb"
        if "content.xml" in names and "mimetype" in names:
            return "ods"
        return "zip"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "xls"  # OLE2; may also be an encrypted OOXML file, xlrd will tell us
    stripped = data[:2048].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if stripped.startswith((b"<!doctype html", b"<html", b"<head", b"<body")):
        return "html"
    if stripped.startswith(b"<?xml") and b"urn:schemas-microsoft-com:office:spreadsheet" in data[:4096].lower():
        return "spreadsheetml"
    if filename and filename.lower().endswith((".csv", ".tsv", ".txt")):
        return "csv"
    if data and b"\x00" not in data[:1024] and (b"," in data[:1024] or b";" in data[:1024] or b"\t" in data[:1024]):
        return "csv"
    return "unknown"


def _reader(fmt: str):
    """The parser for a format, imported on demand (xlrd is only loaded for legacy .xls files)."""
    if fmt == "xlsx":
        from .xlsx import parse
    elif fmt == "xls":
        from .xls import parse
    elif fmt == "spreadsheetml":
        from .spreadsheetml import parse
    elif fmt == "csv":
        parse = _parse_csv
    else:
        raise UnreadableWorkbook(format_problem(fmt))
    return parse


def read_workbook(data: bytes, filename: str | None = None) -> Workbook:
    """Parse spreadsheet bytes into a :class:`Workbook`; raises :class:`UnreadableWorkbook`."""
    if not data:
        raise UnreadableWorkbook(tr("The file is empty."))
    fmt = sniff_format(data, filename)
    try:
        book: ParsedBook = _reader(fmt)(data)
    except UnreadableWorkbook:
        raise
    except Exception as exc:  # a damaged or hostile file can break a reader in ways no list of exceptions would cover
        raise UnreadableWorkbook(tr("The file could not be read ({error}); it may be damaged.", error=type(exc).__name__)) from exc
    wb = Workbook(sheets=[], format=fmt, sha256=hashlib.sha256(data).hexdigest(), size=len(data), filename=filename,
                  properties=dict(book.props), warnings=list(book.notes))
    wb.sheets = [g for g in map(_grid, book.sheets) if g.n_rows and g.n_cols]
    if not wb.sheets:
        raise UnreadableWorkbook(tr("The workbook has no data (every sheet is empty)."))
    return wb


def _plain(value: object) -> object:
    """Normalise a raw cell value: drop blank strings, stringify times, keep dates/numbers/strings."""
    if value is None:
        return None
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, (time, timedelta)):
        return str(value)
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return int(value)
    return value


def _clear_covered(body: list[list], merged: list[tuple[int, int, int, int]]) -> None:
    """A merged range shows only its top-left cell. Whatever else is stored under it is invisible in Excel (a header
    cell copied across leaves "09-25" under the merged "12-25") and must not be read as content."""
    budget = 200_000  # cells: bounds the work on a hostile file full of huge overlapping merges
    for r0, c0, r1, c1 in merged:
        area = (r1 - r0 + 1) * (c1 - c0 + 1)
        if area < 2 or area > budget or body[r0][c0] is None:
            continue
        budget -= area
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                if r != r0 or c != c0:
                    body[r][c] = None


def _grid(raw: RawSheet) -> Grid:
    """Trim empty borders, rectangularise and shift coordinates so the grid starts at its first content."""
    rows = [[_plain(v) for v in r] for r in raw.rows]
    used = [i for i, r in enumerate(rows) if any(v is not None for v in r)]
    if not used:
        return Grid(raw.name, [], visible=raw.visible)
    r0, r1 = used[0], used[-1]
    cols = [j for r in rows[r0:r1 + 1] for j, v in enumerate(r) if v is not None]
    c0, c1 = min(cols), max(cols)
    body = [r[c0:c1 + 1] for r in rows[r0:r1 + 1]]
    merged = [(max(a - r0, 0), max(b - c0, 0), min(c - r0, r1 - r0), min(d - c0, c1 - c0)) for a, b, c, d in raw.merged
              if c >= r0 and a <= r1 and d >= c0 and b <= c1]
    _clear_covered(body, merged)
    warnings = [tr("The sheet is larger than the reader limits (more than {rows} rows, {cols} columns or {cells} cells), so only the first "
                   "part was read.", rows=num(config.MAX_ROWS), cols=num(config.MAX_COLS), cells=num(config.MAX_CELLS))] if raw.truncated else []
    return Grid(
        name=raw.name, cells=body, merged=merged,
        hidden_rows=frozenset(r - r0 for r in raw.hidden_rows if r0 <= r <= r1),
        hidden_cols=frozenset(c - c0 for c in raw.hidden_cols if c0 <= c <= c1),
        pct_cells=frozenset((r - r0, c - c0) for r, c in raw.pct if r0 <= r <= r1 and c0 <= c <= c1),
        visible=raw.visible, truncated=raw.truncated, origin=(r0, c0), warnings=warnings)


def _decode_text(data: bytes) -> str:
    """UTF-8 (with or without a BOM), else Central European Windows text, else Latin-1, which accepts any bytes."""
    for enc in ("utf-8-sig", "cp1250"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _parse_csv(data: bytes) -> ParsedBook:
    text = _decode_text(data)
    try:
        dialect = csv.Sniffer().sniff(text[:8192].replace("\r\n", "\n").replace("\r", "\n"), delimiters=",;\t|")  # it splits lines on "\n" only
    except csv.Error:
        dialect = csv.excel
    sb = SheetBuilder("csv")
    for r, row in enumerate(csv.reader(io.StringIO(text, newline=""), dialect)):
        if r >= config.MAX_ROWS:
            sb.truncated = True
            break
        for c, v in enumerate(row[: config.MAX_COLS]):
            sb.put(r, c, v)
    return ParsedBook([sb.finish()])
