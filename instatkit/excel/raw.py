"""What every spreadsheet reader produces: sparse cells, merges and flags under the reader caps.

``xlsx``, ``xls`` and ``spreadsheetml`` all fill a :class:`SheetBuilder`; :mod:`.grid` turns the result into a
trimmed, rectangular :class:`~instatkit.excel.grid.Grid`. Keeping the caps in one place means no reader can be
talked into building a huge sheet in memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import config
from ..i18n import N_, tr


class UnreadableWorkbook(Exception):
    """The bytes are not a spreadsheet we can read (the message is fit to show the user)."""


_FORMAT_PROBLEMS = {
    "html": N_("The server sent a web page instead of a spreadsheet (a broken link, or the request was blocked)."),
    "corrupt": N_("This looks like a zip file, but it is damaged and cannot be opened."),
    "xlsb": N_("Binary Excel files (.xlsb) are not supported. Save the file as .xlsx and try again."),
    "ods": N_("OpenDocument spreadsheets (.ods) are not supported. Save the file as .xlsx and try again."),
    "zip": N_("This zip file does not contain an Excel workbook."),
    "unknown": N_("This does not look like an Excel or CSV file."),
}


def format_problem(fmt: str) -> str:
    """Why a file of a sniffed format cannot be read, in words fit to show the user."""
    return tr(_FORMAT_PROBLEMS.get(fmt, _FORMAT_PROBLEMS["unknown"]))


@dataclass(slots=True)
class RawSheet:
    name: str
    rows: list[list[object]]
    merged: list[tuple[int, int, int, int]] = field(default_factory=list)  # (r0, c0, r1, c1) inclusive
    hidden_rows: set[int] = field(default_factory=set)
    hidden_cols: set[int] = field(default_factory=set)
    pct: set[tuple[int, int]] = field(default_factory=set)  # numeric cells formatted as percentages
    visible: bool = True
    truncated: bool = False


@dataclass(slots=True)
class ParsedBook:
    sheets: list[RawSheet]
    props: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class SheetBuilder:
    """Collects the cells of one sheet, dropping whatever falls outside the row, column and cell caps."""

    def __init__(self, name: str, visible: bool = True) -> None:
        self.name = name
        self.visible = visible
        self.cells: dict[tuple[int, int], object] = {}
        self.merged: list[tuple[int, int, int, int]] = []
        self.hidden_rows: set[int] = set()
        self.hidden_cols: set[int] = set()
        self.pct: set[tuple[int, int]] = set()
        self.truncated = False

    def put(self, r: int, c: int, value: object, pct: bool = False) -> None:
        if value is None or r < 0 or c < 0:  # a malformed reference such as r="0" or "A0" has no place in the grid
            return
        if r >= config.MAX_ROWS or c >= config.MAX_COLS or len(self.cells) >= config.MAX_CELLS:
            self.truncated = True
            return
        self.cells[(r, c)] = value
        if pct:
            self.pct.add((r, c))

    def merge(self, r0: int, c0: int, r1: int, c1: int) -> None:
        if r0 < config.MAX_ROWS and c0 < config.MAX_COLS and (r1 > r0 or c1 > c0):
            self.merged.append((r0, c0, min(r1, config.MAX_ROWS - 1), min(c1, config.MAX_COLS - 1)))

    def hide_row(self, r: int) -> None:
        if r < config.MAX_ROWS:
            self.hidden_rows.add(r)

    def hide_cols(self, c0: int, c1: int) -> None:
        self.hidden_cols.update(range(max(c0, 0), min(c1 + 1, config.MAX_COLS)))

    def finish(self) -> RawSheet:
        """Dense rows. Sparse positions must not blow up the grid, so the cell cap applies to its area too."""
        if not self.cells:
            return RawSheet(self.name, [], visible=self.visible)
        n_rows = max(r for r, _ in self.cells) + 1
        width = max(c for _, c in self.cells) + 1
        truncated = self.truncated
        if n_rows * width > config.MAX_CELLS:
            n_rows, truncated = max(1, config.MAX_CELLS // width), True
        rows: list[list[object]] = [[None] * width for _ in range(n_rows)]
        for (r, c), v in self.cells.items():
            if r < n_rows:
                rows[r][c] = v
        return RawSheet(self.name, rows, self.merged, self.hidden_rows, self.hidden_cols, self.pct, self.visible, truncated)
