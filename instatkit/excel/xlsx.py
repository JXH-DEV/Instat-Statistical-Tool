"""Streaming ``.xlsx`` reader on the standard library (zipfile + expat callbacks), no openpyxl.

No element tree is ever built: expat calls back for each tag and the cells go straight into a
:class:`~instatkit.excel.raw.SheetBuilder`, so memory follows the number of cells kept, not the size of the XML
(openpyxl creates an object per cell, which is slow and heavy on an old laptop). Merged ranges, hidden
rows/columns, sheet visibility, percent formats, real dates and document properties are read. Hostile files are
bounded: no DOCTYPE/entities, one size budget for all the XML of a package, capped entry and sheet counts, and the
sparse-cell caps of :mod:`.raw`.
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
import zlib
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

from .. import config
from ..i18n import tr
from .raw import ParsedBook, SheetBuilder, UnreadableWorkbook, format_problem
from .xmlparse import Target

_META_BYTES = 8_000_000  # the workbook, relationship, style and property parts: a real one is a small fraction of this
_DATE_IDS = frozenset([*range(14, 23), *range(27, 37), *range(45, 48), *range(50, 59)])
_PCT_IDS = frozenset((9, 10))
_NOISE = re.compile(r'"[^"]*"|\\.|\[[^\]]*\]|_.|\*.')  # quoted text, escapes, [colour]/[locale] tags, padding
_REF = re.compile(r"([A-Z]+)(\d+):([A-Z]+)(\d+)$")
_EPOCH_1900, _EPOCH_1904 = datetime(1899, 12, 30), datetime(1904, 1, 1)
_TRUE = frozenset(("1", "true"))


def _col(ref: str) -> int:
    """Zero-based column of an A1 reference (``'AB12'`` -> 27)."""
    n = 0
    for ch in ref:
        if ch < "A":
            break
        n = n * 26 + ord(ch) - 64
    return n - 1


class _Package:
    """An opened ``.xlsx`` zip. Its XML parts are read through expat targets within one size budget for the whole
    package, so neither one huge part nor many references to the same part can keep the computer busy."""

    def __init__(self, data: bytes) -> None:
        self.zf = zipfile.ZipFile(io.BytesIO(data))
        if len(self.zf.infolist()) > config.MAX_ZIP_ENTRIES:
            raise UnreadableWorkbook(tr("This workbook has too many parts to be read safely."))
        self.names = self.zf.NameToInfo
        self.budget = config.MAX_XML_BYTES

    def feed(self, name: str, target: Target, limit: int | None = None) -> object:
        """Run ``target`` over one part (at most ``limit`` bytes uncompressed) and return what it collected."""
        info = self.zf.getinfo(name)  # the reader never yields more than the size declared here
        self.budget -= info.file_size
        if self.budget < 0 or info.file_size > (limit or config.MAX_XML_BYTES):
            raise UnreadableWorkbook(tr("This workbook is too large to be read safely on this computer."))
        parser = ET.XMLParser(target=target)
        with self.zf.open(info) as f:
            while chunk := f.read(1 << 16):
                parser.feed(chunk)
        return parser.close()


class _Collect(Target):
    """Every element as ``(name, attributes, text, parent name)``, in document order of their end tags."""

    def __init__(self) -> None:
        super().__init__()
        self.out: list[tuple[str, dict, str, str]] = []
        self._stack: list[list] = []

    def start(self, tag: str, attrib: dict) -> None:
        self._stack.append([self._names[tag], attrib, [], self._stack[-1][0] if self._stack else ""])

    def data(self, text: str) -> None:
        self._stack[-1][2].append(text)

    def end(self, tag: str) -> None:
        name, attrib, text, parent = self._stack.pop()
        self.out.append((name, attrib, "".join(text), parent))

    def close(self) -> list[tuple[str, dict, str, str]]:
        return self.out


class _SharedStrings(Target):
    """The shared string table; rich-text runs are joined and phonetic runs (``rPh``) skipped."""

    def __init__(self) -> None:
        super().__init__()
        self.strings: list[str] = []
        self._buf: list[str] | None = None
        self._parts: list[str] = []
        self._rph = 0

    def start(self, tag: str, attrib: dict) -> None:
        n = self._names[tag]
        if n == "si":
            self._parts = []
        elif n == "rPh":
            self._rph += 1
        elif n == "t" and not self._rph:
            self._buf = []

    def data(self, text: str) -> None:
        if self._buf is not None:
            self._buf.append(text)

    def end(self, tag: str) -> None:
        n = self._names[tag]
        if n == "t" and self._buf is not None:
            self._parts.append("".join(self._buf))
            self._buf = None
        elif n == "rPh":
            self._rph -= 1
        elif n == "si":
            self.strings.append("".join(self._parts))

    def close(self) -> list[str]:
        return self.strings


def _format_kind(fmt_id: int, code: str | None) -> str:
    """``'date'``, ``'pct'`` or ``''`` for a number format (built-in id, or custom code when there is one)."""
    if code is None:
        return "date" if fmt_id in _DATE_IDS else "pct" if fmt_id in _PCT_IDS else ""
    bare = _NOISE.sub("", code).lower()
    if "%" in bare:
        return "pct"
    return "date" if re.search(r"[ymdhs]", bare) else ""


def _cell_kinds(pkg: _Package, name: str) -> list[str]:
    """Per cell-format index (the ``s`` attribute of a cell): is it a date or a percentage format?"""
    elements = pkg.feed(name, _Collect(), _META_BYTES)
    custom = {int(a.get("numFmtId", "0")): a.get("formatCode", "") for n, a, _t, _p in elements if n == "numFmt"}
    ids = [int(a.get("numFmtId", "0")) for n, a, _t, p in elements if n == "xf" and p == "cellXfs"]
    return [_format_kind(i, custom.get(i)) for i in ids]


def _serial(x: float, epoch: datetime) -> object:
    """An Excel date serial as ``datetime`` (``time`` for a bare fraction of a day); out-of-range values stay numbers."""
    try:
        if 0 <= x < 1:
            return (datetime.min + timedelta(seconds=round(x * 86400))).time()
        return epoch + timedelta(seconds=round(x * 86400))
    except (OverflowError, ValueError):
        return x


class _Sheet(Target):
    """Expat target for one worksheet: cells, merges and hidden rows/columns go straight into the builder."""

    def __init__(self, sb: SheetBuilder, shared: list[str], kinds: list[str], epoch: datetime) -> None:
        super().__init__()
        self.sb, self.shared, self.kinds, self.epoch = sb, shared, kinds, epoch
        self.row = -1
        self._skip = False
        self._next_col = 0
        self._cell: tuple[int, str, str | None] | None = None
        self._v: str | None = None
        self._buf: list[str] | None = None
        self._inline: list[str] = []
        self._in_is = self._rph = False

    def start(self, tag: str, attrib: dict) -> None:
        n = self._names[tag]
        if n == "c":
            ref = attrib.get("r")
            c = _col(ref) if ref else self._next_col
            self._next_col = c + 1
            self._cell = None if self._skip else (c, attrib.get("t", "n"), attrib.get("s"))
            self._v = None
        elif n == "v":
            self._buf = []
        elif n == "row":
            self.row = int(attrib["r"]) - 1 if "r" in attrib else self.row + 1
            self._next_col = 0
            self._skip = self.row >= config.MAX_ROWS
            if not self._skip and attrib.get("hidden") in _TRUE:
                self.sb.hide_row(self.row)
        elif n == "is":
            self._in_is, self._inline = True, []
        elif n == "rPh":
            self._rph = True
        elif n == "t" and self._in_is and not self._rph:
            self._buf = []
        elif n == "col" and attrib.get("hidden") in _TRUE:
            self.sb.hide_cols(int(attrib.get("min", "1")) - 1, int(attrib.get("max", "1")) - 1)
        elif n == "mergeCell":
            m = _REF.match(attrib.get("ref", ""))
            if m:
                self.sb.merge(int(m.group(2)) - 1, _col(m.group(1)), int(m.group(4)) - 1, _col(m.group(3)))

    def data(self, text: str) -> None:
        if self._buf is not None:
            self._buf.append(text)

    def end(self, tag: str) -> None:
        n = self._names[tag]
        if n == "v":
            self._v, self._buf = "".join(self._buf or ()), None
        elif n == "t" and self._buf is not None:
            self._inline.append("".join(self._buf))
            self._buf = None
        elif n == "is":
            self._in_is, self._v = False, "".join(self._inline)
        elif n == "rPh":
            self._rph = False
        elif n == "c" and self._v is not None:
            if self._cell is None:  # a value beyond the row cap is dropped (empty styled rows are free)
                self.sb.truncated = True
            else:
                c, t, s = self._cell
                value, pct = self._convert(t, s, self._v)
                self.sb.put(self.row, c, value, pct)

    def _convert(self, t: str, s: str | None, raw: str) -> tuple[object, bool]:
        if t == "s":
            i = int(raw)
            return (self.shared[i] if 0 <= i < len(self.shared) else None), False
        if t in ("str", "inlineStr", "e"):
            return raw, False
        if t == "b":
            return raw.strip() in _TRUE, False
        if t == "d":
            try:
                return datetime.fromisoformat(raw.strip().rstrip("Zz")), False
            except ValueError:
                return raw, False
        try:
            x = float(raw)
        except ValueError:
            return raw, False
        kind = self.kinds[int(s)] if s is not None and 0 <= int(s) < len(self.kinds) else ""
        return (_serial(x, self.epoch), False) if kind == "date" else (x, kind == "pct")

    def close(self) -> None:
        return None


def parse(data: bytes) -> ParsedBook:
    """Read every worksheet of an ``.xlsx`` package into raw sheets (see :mod:`.raw`)."""
    try:
        pkg = _Package(data)
        root_rels = _relationships(pkg, "")
        book = next((p for t, p in root_rels.values() if t == "officeDocument"), "xl/workbook.xml")
        rels = _relationships(pkg, book)
        shared_part = next((p for t, p in rels.values() if t == "sharedStrings"), "")
        styles_part = next((p for t, p in rels.values() if t == "styles"), "")
        shared = pkg.feed(shared_part, _SharedStrings()) if shared_part in pkg.names else []
        kinds = _cell_kinds(pkg, styles_part) if styles_part in pkg.names else []
        epoch, sheets = _EPOCH_1900, []
        for name, attrib, _text, _parent in pkg.feed(book, _Collect(), _META_BYTES):
            if name == "workbookPr" and attrib.get("date1904") in _TRUE:
                epoch = _EPOCH_1904
            elif name == "sheet":
                rid = next((v for k, v in attrib.items() if k.endswith("}id")), "")
                sheets.append((attrib.get("name", ""), attrib.get("state", "visible") == "visible", rid))
        if len(sheets) > config.MAX_SHEETS:
            raise UnreadableWorkbook(tr("This workbook has too many sheets to be read safely."))
        out = []
        for name, visible, rid in sheets:
            kind, part = rels.get(rid, ("", ""))
            if kind == "worksheet" and part in pkg.names:
                sb = SheetBuilder(name, visible)
                pkg.feed(part, _Sheet(sb, shared, kinds, epoch))
                out.append(sb.finish())
        return ParsedBook(out, _properties(pkg))
    except UnreadableWorkbook:
        raise
    except (zipfile.BadZipFile, zlib.error) as exc:
        raise UnreadableWorkbook(format_problem("corrupt")) from exc
    except KeyError as exc:
        raise UnreadableWorkbook(tr("This is not a complete Excel workbook (the part {name} is missing).", name=exc)) from exc
    except (ET.ParseError, ValueError, IndexError) as exc:
        raise UnreadableWorkbook(tr("The workbook is damaged and could not be read ({error}).", error=type(exc).__name__)) from exc


def _relationships(pkg: _Package, part: str) -> dict[str, tuple[str, str]]:
    """Relationship id -> (type, absolute part name) for ``part`` (``''`` is the package itself)."""
    folder, base = posixpath.split(part)
    rel_part = posixpath.join(folder, "_rels", f"{base}.rels")
    if rel_part not in pkg.names:
        return {}
    out = {}
    for name, a, _text, _parent in pkg.feed(rel_part, _Collect(), _META_BYTES):
        if name == "Relationship" and a.get("TargetMode") != "External":
            target = a.get("Target", "")
            full = target[1:] if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
            out[a.get("Id", "")] = (a.get("Type", "").rpartition("/")[2], full)
    return out


def _properties(pkg: _Package) -> dict[str, str]:
    if "docProps/core.xml" not in pkg.names:
        return {}
    keep = ("title", "creator", "created", "modified")
    return {n: t.strip() for n, _a, t, _p in pkg.feed("docProps/core.xml", _Collect(), _META_BYTES) if n in keep and t.strip()}
