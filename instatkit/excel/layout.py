"""Work out the structure of a messy sheet: titles, header band, label columns, periods, notes.

The engine is heuristic but transparent: every decision is recorded on the returned :class:`TableSpec`
(which rows are titles/header/data/notes, which columns are labels/attributes/values, how confident we
are and why), so the UI can show "how this file was read" and the user can override it.

All indices are 0-based positions in the :class:`~instatkit.excel.grid.Grid`.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime

from ..i18n import num, tn, tr
from ..semantics import glossary
from ..semantics.numbers import looks_numeric, parse_number
from ..semantics.periods import (
    Period,
    infer_date_freq,
    infer_frequency,
    parse_period,
    sub_period,
)
from ..semantics.textnorm import clean_text, detect_language, sentence_case, split_bilingual, strip_leading_marker
from ..semantics.units import UnitInfo, parse_units, subject_unit
from .grid import Grid

DIM_TAGS = {"sex", "county", "municipality", "age", "urban_rural", "education", "status", "country", "continent",
            "month", "sector", "ownership", "period_word", "marital"}


@dataclass
class ColumnSpec:
    col: int
    kind: str  # label | code | attr | attr_text | value | period
    name: str = ""
    path_sq: list[str] = field(default_factory=list)  # non-period header levels
    path_en: list[str] = field(default_factory=list)
    period: Period | None = None
    measure: str | None = None  # a column whose header is shorter than its siblings' is a different measure ("Total children")


@dataclass
class RowSpec:
    row: int
    labels: list[str] = field(default_factory=list)  # display labels (English when known), one per label column
    labels_orig: list[str] = field(default_factory=list)  # as written in the file
    code: str | None = None
    level: int | None = None
    parent_code: str | None = None
    is_total: bool = False
    section: str | None = None
    period: Period | None = None  # when periods run down the rows


@dataclass
class TableSpec:
    sheet: str
    orientation: str
    title_rows: list[int]
    header_rows: list[int]
    data_rows: list[int]
    note_rows: list[int]
    annotation_rows: list[int]
    section_rows: list[int]
    columns: list[ColumnSpec]
    rows: list[RowSpec]
    titles: list[str] = field(default_factory=list)
    title_sq: str | None = None
    title_en: str | None = None
    measure_sq: str | None = None
    measure_en: str | None = None
    notes: list[str] = field(default_factory=list)
    units: UnitInfo = field(default_factory=UnitInfo)
    period_hint: Period | None = None
    header_is_dimension: bool = True
    freq: str | None = None
    confidence: float = 1.0
    warnings: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    label_header: list[str] = field(default_factory=list)  # header text of each non-code label column
    origin: tuple[int, int] = (0, 0)
    header_constants: list[str] = field(default_factory=list)  # header text shared by every value column
    header_level_names: list[str] = field(default_factory=list)  # banner text above each remaining header level ("Sex")
    header_pair: bool = False  # the header is a pair of rows, one Albanian and one English
    scope: list[tuple[str, str]] = field(default_factory=list)  # ("Prefecture", "Berat"): a line that scopes the whole table

    @property
    def value_cols(self) -> list[ColumnSpec]:
        return [c for c in self.columns if c.kind == "value"]

    @property
    def label_cols(self) -> list[int]:
        return [c.col for c in self.columns if c.kind in ("label", "code")]


_NOTE_RE = re.compile(r"^\s*(?:\*|•|\(\d\)|\d\)|sh[eë]nim|note|notes|burimi|source|sources|p\s*[-=:]|\(p\))", re.I)
_FORMULA_RE = re.compile(r"^\s*\(?\s*\d+\s*(?:[=+\-*/]\s*\(?\s*\d+\s*\)?)+\s*\)?\s*$")
_CODE_HEADER_RE = re.compile(
    r"(?i)(?<![a-z])(kodi|code|nve|nace|coicop|isic|sitc|hs|isco|nr\.?|no\.?|cpa|prodcom|ecoicop)(?![a-z])")
_TABLE_PREFIX_RE = re.compile(  # "Tab.7 ", "Tab. 1.10 ", "Table 2.17: " and the bare census numbering "1.1.1 "
    r"(?i)^\s*(?:(?:tab(?:ela|le|\.)?|table)\s*\.?\s*\d+(?:\.\d+)*[a-z]?\s*[.:)\-–]?\s+|\d{1,2}(?:\.\d{1,2}){1,3}\s+(?=[^\W\d_]))")
_DOTTED_CODE_RE = re.compile(r"^\d{1,2}(?:\.\d{1,2})*\.?$")
_ALPHA_CODE_RE = re.compile(r"^[A-Z]{1,2}\d{0,2}$")


def _is_year_like(v: object) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return float(v).is_integer() and 1900 <= v <= 2100
    if isinstance(v, str):
        return bool(re.fullmatch(r"(?:19|20)\d{2}\**", clean_text(v)))
    return False


def _year_value(v: object) -> int:
    digits = re.sub(r"\D", "", str(int(v)) if isinstance(v, (int, float)) else clean_text(v))
    return int(digits[:4])


def _is_formula_text(v: object) -> bool:
    """``(3=1-2)`` and ``6=(3+4-5)`` are column formulas; a bare ``12-21`` is a month header, not arithmetic."""
    return isinstance(v, str) and bool(_FORMULA_RE.match(v)) and ("=" in v or "(" in v)


def _is_annotation_row(values: list[object]) -> bool:
    """Column-number / formula helper rows such as ``(3=1-2)``, ``4``, ``6=(3+4-5)`` or ``1 2 3 4``."""
    if any(isinstance(v, str) and not _is_formula_text(v) for v in values):
        return False
    formulas = sum(1 for v in values if isinstance(v, str))
    ints = [int(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)
            and float(v).is_integer() and 0 <= v <= 60]
    if formulas and formulas + len(ints) == len(values):
        return True
    if len(ints) == len(values) and len(values) >= 3:
        ints.sort()
        return ints == list(range(ints[0], ints[0] + len(ints))) and ints[0] in (0, 1, 2)
    return False


def _looks_like_codes(values: list[str]) -> bool:
    vals = [v for v in values if v and not glossary.is_total_label(v) and glossary.tag_of(v) != "sex"]
    if len(vals) < 2:
        return False
    dotted = sum(1 for v in vals if _DOTTED_CODE_RE.match(v) and ("." in v or len(v) == 6))
    alpha = sum(1 for v in vals if _ALPHA_CODE_RE.match(v))
    return max(dotted, alpha) / len(vals) >= 0.8


_OPEN_CLASS = re.compile(r"(?i)^\s*\d+\s*(?:\+|e\s+lart|and\s+over|and\s+older|or\s+more)\s*$")  # '85+', '85 e lart'
_AGE_BAND_HEADER = re.compile(r"^\s*(\d{1,3})\s*[-–]\s*(\d{1,3})\s*$")


def _is_age_band_run(texts: list[str]) -> bool:
    """Header texts like ``12-19, 20-29, 30-39 ... 70 +``: consecutive class limits, not month-year pairs (``12-19``
    would otherwise read as December 2019). Each band starts where the previous one ended."""
    bands = []
    for t in texts:
        m = _AGE_BAND_HEADER.match(t)
        if m:
            bands.append((int(m.group(1)), int(m.group(2))))
    if len(bands) < 3 or any(b < a for a, b in bands):
        return False
    chained = sum(1 for (a1, b1), (a2, _b2) in zip(bands, bands[1:]) if a2 in (b1, b1 + 1))
    return chained >= max(2, len(bands) - 2)


class _Work:
    """The grid plus a merge-spread copy, with hidden rows/columns masked out."""

    def __init__(self, grid: Grid):
        self.g = grid
        self.R, self.C = grid.n_rows, grid.n_cols
        hr, hc = grid.hidden_rows, grid.hidden_cols
        self.raw = [[None if (r in hr or c in hc) else grid.cells[r][c] for c in range(self.C)] for r in range(self.R)]
        self.spread = [row[:] for row in self.raw]
        self.banner_rows: set[int] = set()
        for r0, c0, r1, c1 in grid.merged:
            if r0 >= self.R or c0 >= self.C or self.raw[r0][c0] is None:
                continue
            width = c1 - c0 + 1
            only_cell = sum(v is not None for v in self.raw[r0]) == 1
            if r0 == r1 and c0 == 0 and only_cell and width >= max(3, int(0.75 * self.C)):
                self.banner_rows.add(r0)  # a title spanning the whole table, not a header group
                continue
            if (r1 - r0 + 1) * width > 5000:
                continue
            for r in range(r0, min(r1, self.R - 1) + 1):
                for c in range(c0, min(c1, self.C - 1) + 1):
                    if (r, c) != (r0, c0) and self.raw[r][c] is None:
                        self.spread[r][c] = self.raw[r0][c0]
        self.hidden_count = len(hr) + len(hc)
        # anchors of real merges (more than one cell): a header group or a label spanning rows is merged, a title is not
        self.merge_anchor = {(r0, c0): (r1, c1) for r0, c0, r1, c1 in grid.merged if r1 > r0 or c1 > c0}

    def txt(self, r: int, c: int) -> str:
        """Cell text with newlines kept: ``'Përqindja\\nCoverage ratio'`` is a bilingual label, split later.
        Real Excel dates become ISO dates so the period parser sees ``2024-03-01``, not ``2024-03-01 00:00:00``."""
        v = self.spread[r][c]
        if v is None:
            return ""
        if isinstance(v, datetime):
            return v.date().isoformat() if (v.hour, v.minute, v.second) == (0, 0, 0) else v.isoformat(sep=" ")
        if isinstance(v, date):
            return v.isoformat()
        return clean_text(v, keep_newlines=True)

    def raw_txt(self, r: int, c: int) -> str:
        v = self.raw[r][c]
        return clean_text(v) if v is not None else ""

    def nonempty_cols(self, r: int) -> list[int]:
        return [c for c, v in enumerate(self.raw[r]) if v is not None]

    def row_text(self, r: int) -> str:
        return clean_text(" ".join(clean_text(v) for v in self.raw[r] if v is not None))

    def inside_merge(self, r: int) -> bool:
        return any(r0 < r <= r1 for r0, _c0, r1, _c1 in self.g.merged)


def _row_kind(values: list[object]) -> str:
    """E empty | T title (one text cell) | S stray number | Y year header | A annotation | D data | H header."""
    cells = [v for v in values if v is not None]
    n = len(cells)
    if n == 0:
        return "E"
    if n == 1:
        return "T" if isinstance(cells[0], str) and not looks_numeric(cells[0]) else "S"
    numeric = [v for v in cells if looks_numeric(v) and not (isinstance(v, str) and parse_number(v).is_marker)]
    if len(numeric) >= 2 and all(_is_year_like(v) for v in numeric) and len(numeric) >= max(2, n // 2):
        years = [_year_value(v) for v in numeric]
        descents = sum(1 for a, b in zip(years, years[1:]) if b < a)
        # non-decreasing, or the same run of years repeated side by side (Males 2022 2023 | Females 2022 2023)
        if descents == 0 or (descents <= 3 and years[0] == min(years) and len(numeric) >= 4):
            return "Y"
    if _is_annotation_row(cells):
        return "A"
    n_num = sum(1 for v in cells if looks_numeric(v))
    density = n_num / n
    if n_num >= 1 and ((n_num >= 2 and density >= 0.34) or density >= 0.5):
        return "D"
    return "H"


def _reclassify_lone_year_headers(w: _Work, kinds: list[str]) -> None:
    """``['Municipality', 2023]`` right above a text header row is a header with one (merged) year."""
    for r, k in enumerate(kinds):
        if k != "D":
            continue
        cells = [v for v in w.raw[r] if v is not None]
        numeric = [v for v in cells if looks_numeric(v)]
        if len(numeric) != 1 or not _is_year_like(numeric[0]) or len(cells) > 3:
            continue
        nxt = next((kinds[j] for j in range(r + 1, w.R) if kinds[j] != "E"), None)
        if nxt == "H":
            kinds[r] = "Y"


def _int_sequence(values: list[object], min_len: int = 5) -> list[int] | None:
    """The cells as 0/1-based consecutive integers (single years of age, class numbers), else ``None``."""
    ints = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer()]
    if len(ints) < min_len or len(ints) != len([v for v in values if looks_numeric(v)]):
        return None
    seq = [int(v) for v in ints]
    return seq if seq[0] in (0, 1) and seq[-1] <= 120 and all(b - a == 1 for a, b in zip(seq, seq[1:])) else None


def _reclassify_sequence_headers(w: _Work, kinds: list[str]) -> None:
    """``['Region', 0, 1, 2, ..., 7]`` is a header (single years of age) when no text header sits above it and the
    next row is different data - not when it is just a data row that happens to count 1, 2, 3 ..."""
    for r, k in enumerate(kinds):
        if k != "D":
            continue
        cells = [v for v in w.raw[r] if v is not None]
        # "Total | 0 | 1 | 2 | 3 | 6+" (women by number of children) is a header even below a group title
        extras = [v for v in cells if isinstance(v, str)]
        total_first = (bool(extras) and any(glossary.is_total_label(v) for v in extras)
                       and all(glossary.is_total_label(v) or _OPEN_CLASS.match(v) for v in extras))
        seq = _int_sequence(cells, min_len=3 if total_first else 5)
        if seq is None or len(cells) - len(seq) > 2:
            continue
        prev = next((kinds[j] for j in range(r - 1, -1, -1) if kinds[j] != "E"), None)
        nxt = next((j for j in range(r + 1, w.R) if kinds[j] != "E"), None)
        if (prev in ("H", "Y", "D") and not total_first) or nxt is None or kinds[nxt] != "D":
            continue
        nxt_seq = _int_sequence([v for v in w.raw[nxt] if v is not None])
        if nxt_seq == seq:
            continue
        kinds[r] = "Y"


def _reclassify_lone_column_headers(w: _Work, kinds: list[str]) -> None:
    """A single text cell right of the row labels and straight above the first data row heads that column
    (``[None, 'Regjistrimi Census, 2001']`` over ``['Popullsia banuese', 3069275]``); it is not a title."""
    first_data = next((r for r, k in enumerate(kinds) if k == "D"), None)
    if first_data is None:
        return
    for r in range(first_data):
        if kinds[r] != "T" or r in w.banner_rows:
            continue
        cols = w.nonempty_cols(r)
        nxt = next((j for j in range(r + 1, w.R) if kinds[j] != "E"), None)
        if len(cols) != 1 or cols[0] == 0 or nxt != first_data:
            continue
        c, labels = cols[0], w.nonempty_cols(nxt)
        text = w.raw_txt(r, c)
        if (w.raw[nxt][c] is not None and looks_numeric(w.raw[nxt][c]) and labels and labels[0] < c
                and not _note_like(text) and not _is_unit_line(text)):
            kinds[r] = "H"


def _is_ordinal_column(w: _Work, data_rows: list[int], c: int, header: list[str]) -> bool:
    """Single years of age / class numbers counting 0, 1, 2 ... (or 6, 7, 8 ...) down the rows, with text total rows
    in between: row labels written as numbers, not a measure. A column headed by a period is a value column."""
    if not header or any(parse_period(t) is not None or looks_numeric(t) for t in header):
        return False
    vals = [w.raw[r][c] for r in data_rows if w.raw[r][c] is not None]
    nums = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer()]
    others = [v for v in vals if not (isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer())]
    if len(nums) < 5 or any(not (isinstance(v, str) and (glossary.is_total_label(v) or _OPEN_CLASS.match(v))) for v in others):
        return False
    seq = [int(v) for v in nums]
    steps = [b - a for a, b in zip(seq, seq[1:])]
    # a count-up per block (sex groups repeating ages 6, 7, 8 ...) restarts, so a few steps back are fine
    if sum(1 for s in steps if s == 1) < 0.85 * len(steps) or min(seq) < 0 or max(seq) > 130:
        return False
    return not (1900 <= seq[0] <= 2100)  # a run of years is a period axis, which has its own detection


def _note_like(text: str) -> bool:
    return bool(_NOTE_RE.match(text))


def _runs(kinds: list[str]) -> list[tuple[int, int]]:
    """Data-row runs, one per table. A header-like row between data rows starts a new table."""
    data = [i for i, k in enumerate(kinds) if k == "D"]
    if not data:
        return []
    runs = [[data[0], data[0]]]
    for prev, d in zip(data, data[1:]):
        if any(k in ("H", "Y") for k in kinds[prev + 1:d]):
            runs.append([d, d])
        else:
            runs[-1][1] = d
    return [(a, b) for a, b in runs]


def _split_gap(w: _Work, kinds: list[str], prev_last: int, first: int) -> tuple[list[int], list[int]]:
    """Rows between two tables: (notes that close the previous one, preamble that opens the next)."""
    rows = list(range(prev_last + 1, first))
    if prev_last < 0:
        return [], rows
    trailer: list[int] = []
    gap_seen = False
    for i, r in enumerate(rows):
        k = kinds[r]
        if k == "E":
            gap_seen = True
            continue
        if k in ("T", "S", "H", "Y", "A") and (_note_like(w.row_text(r)) or (not gap_seen and k in ("T", "S"))):
            trailer.append(r)
            continue
        return trailer, rows[i:]
    return trailer, []


def _find_header(w: _Work, kinds: list[str], pre: list[int]):
    """Walk up from the first data row: (annotation rows, section rows above data, header rows, title rows)."""
    annotation: list[int] = []
    skipped: list[int] = []
    j = len(pre) - 1
    while j >= 0 and kinds[pre[j]] in ("E", "A", "T", "S"):
        if kinds[pre[j]] == "A":
            annotation.append(pre[j])
        elif kinds[pre[j]] in ("T", "S"):
            skipped.append(pre[j])
        j -= 1
    header: list[int] = []
    while j >= 0 and kinds[pre[j]] in ("H", "Y"):
        cols = w.nonempty_cols(pre[j])
        # a short row of one or two cells holding a long sentence is a title ("Tab. 4 | Number of pupils by ..."),
        # unless those cells are merged over the columns/rows below them: then they are header groups
        if (header and len(cols) <= 2 and max(len(w.raw_txt(pre[j], c)) for c in cols) >= 30
                and len(w.nonempty_cols(header[-1])) >= 3 and not any((pre[j], c) in w.merge_anchor for c in cols)):
            break
        header.append(pre[j])
        j -= 1
        if j >= 1 and kinds[pre[j]] == "E" and kinds[pre[j - 1]] in ("H", "Y") and w.inside_merge(pre[j]):
            j -= 1
    header.reverse()
    titles = [r for r in pre[: j + 1] if kinds[r] != "E"]
    if not header and annotation:
        numbers = [r for r in annotation if len({v for v in w.raw[r] if isinstance(v, (int, float))}) >= 5]
        if numbers:  # a row of plain numbers is the only header there is (single years of age, class sizes ...)
            header = [min(numbers)]
            annotation = [r for r in annotation if r not in header]
    if header:
        return sorted(annotation), sorted(skipped), header, titles
    return sorted(annotation), [], [], sorted(set(titles) | set(skipped))


@dataclass
class _Profile:
    n: int = 0
    n_num: int = 0

    @property
    def numeric_frac(self) -> float:
        return self.n_num / self.n if self.n else 0.0


def _profile(w: _Work, col: int, rows: list[int]) -> _Profile:
    p = _Profile()
    for r in rows:
        v = w.raw[r][col]
        if v is None:
            continue
        p.n += 1
        p.n_num += looks_numeric(v)
    return p


def _header_stack(w: _Work, header_rows: list[int], col: int, lowest: set[int]) -> tuple[list[str], list[int]]:
    """Header texts for one column, top -> bottom, and the header row each came from. Merged cells are already
    spread; a group label above several sub-columns without a merge is carried right while every column in between
    has a sub-header."""
    out: list[str] = []
    rows: list[int] = []
    for r in header_rows:
        t = w.txt(r, col)
        if not t and r != header_rows[-1]:
            c = col - 1
            while c >= 0 and not w.txt(r, c):
                c -= 1
            if c >= 0 and all(k in lowest for k in range(c, col + 1)):
                t = w.txt(r, c)
        if t and (not out or out[-1] != t):
            out.append(t)
            rows.append(r)
    return out, rows


def _complete_total_paths(cols: list[ColumnSpec]) -> None:
    """A "Total" column beside group columns often has a shorter header (its cell is merged down the header rows).
    It totals the levels it lacks: each missing level takes the text every other column shares there (a banner such
    as "Marital status") and otherwise "Total". So ``['Total']`` beside ``['Marital status', 'Single']`` becomes
    ``['Marital status', 'Total']`` and ``[banner, 'Total']`` beside ``[banner, 'Albania', 'Male']`` becomes
    ``[banner, 'Total', 'Total']``. The paths are compared after Albanian/English pairing, so a label written on two
    header rows counts as one level."""
    full = max((len(c.path_en) for c in cols), default=0)
    peers = [c for c in cols if len(c.path_en) == full]
    if full < 2 or len(peers) < 2:
        return

    def shared(paths: list[list[str]]) -> list[str | None]:
        return [level.pop() if len(level := {p[j] for p in paths}) == 1 else None for j in range(full)]

    shared_sq, shared_en = shared([c.path_sq for c in peers]), shared([c.path_en for c in peers])
    for c in cols:
        n = len(c.path_en)
        if not 0 < n < full or not glossary.is_total_label(c.path_en[-1]):
            continue
        k = 0  # leading levels the column already has in common with the others (the banner)
        while k < n - 1 and c.path_en[k] == shared_en[k]:
            k += 1
        lead = full - (n - k)
        c.path_sq = [shared_sq[j] or c.path_sq[-1] for j in range(lead)] + c.path_sq[k:]
        c.path_en = [shared_en[j] or c.path_en[-1] for j in range(lead)] + c.path_en[k:]
        c.name = " | ".join(c.path_en or c.path_sq)


def _is_code_header(text: str) -> bool:
    return bool(_CODE_HEADER_RE.search(text or ""))


def _band_languages(w: _Work, header_rows: list[int], data_cols: list[int]) -> tuple[int, int] | None:
    """If the header band is two parallel rows (one Albanian, one English), return their order as
    ``(sq_index, en_index)`` within the band. Hierarchical bands (group over sub-header) return ``None``."""
    if len(header_rows) != 2:
        return None
    a, b = header_rows
    ca = [c for c in data_cols if w.raw[a][c] is not None]
    cb = [c for c in data_cols if w.raw[b][c] is not None]
    if not ca or not cb or len(set(ca) & set(cb)) / max(len(ca), len(cb)) < 0.8:
        return None
    ta = [clean_text(w.raw[a][c]) for c in ca]
    tb = [clean_text(w.raw[b][c]) for c in cb]
    if any(parse_period(t) for t in ta + tb):
        return None

    def count(ts: list[str]) -> tuple[int, int]:
        langs = [detect_language(t) for t in ts]
        return langs.count("sq"), langs.count("en")

    sqa, ena = count(ta)
    sqb, enb = count(tb)
    if sqa > ena and sqa >= 1 and enb >= sqb and (enb > 0 or sqb == 0):
        return 0, 1
    if sqb > enb and sqb >= 1 and ena >= sqa and (ena > 0 or sqa == 0):
        return 1, 0
    return None


def _bilingual_path(path: list[str], band: tuple[int, int] | None = None,
                    tail: tuple[int, int] | None = None) -> tuple[list[str], list[str]]:
    """Parallel Albanian / English label lists for a header stack.

    Two adjacent levels in different languages are one label written twice, not a hierarchy. When the whole
    header band is known to be a parallel sq/en pair (``band``), two-level stacks are paired outright; when only
    its last two rows are (``tail``), the stack's last two levels are, however short the Albanian words are."""
    if band is not None and len(path) == 2:
        return [clean_text(path[band[0]])], [clean_text(path[band[1]])]
    if tail is not None and len(path) >= 2:
        head_sq, head_en = _bilingual_path(path[:-2], band)
        sq, en = clean_text(path[-2 + tail[0]]), clean_text(path[-2 + tail[1]])
        return [*head_sq, sq], [*head_en, en]
    sq: list[str] = []
    en: list[str] = []
    i = 0
    while i < len(path):
        t = path[i]
        pair = split_bilingual(t)
        if pair:
            sq.append(pair[0])
            en.append(pair[1])
            i += 1
            continue
        if i + 1 < len(path):
            a, b = detect_language(t), detect_language(path[i + 1])
            if {a, b} == {"sq", "en"}:
                s, e = (t, path[i + 1]) if a == "sq" else (path[i + 1], t)
                sq.append(s)
                en.append(e)
                i += 2
                continue
        t = clean_text(t)
        sq.append(t)
        en.append(glossary.translate(t) or t)
        i += 1
    return sq, en


def _best_header(stack: list[str], band: tuple[int, int] | None = None) -> str:
    sq, en = _bilingual_path(stack, band)
    return " | ".join(en or sq)


def _split_label(text: str) -> tuple[str, str]:
    """(display, original): ``Gjithsej/Total`` -> ('Total', 'Gjithsej/Total'); Albanian -> glossary English."""
    orig = clean_text(text)
    pair = split_bilingual(text)
    if pair:
        return pair[1], orig
    return (glossary.translate(orig) or orig), orig


def _column_period(stack: list[str], hint: str | None) -> tuple[Period | None, set[int]]:
    """Period carried by a header stack and the levels it consumed (``['2023', 'Q1']`` -> 2023-Q1)."""
    from ..semantics.periods import combine_year_sub

    full = [(i, parse_period(t, hint=hint)) for i, t in enumerate(stack)]
    full = [(i, p) for i, p in full if p is not None]
    if not full:
        return None, set()
    i, p = full[-1]
    if p.freq == "A" and len(stack) > 1:
        for j, t in enumerate(stack):
            sub = sub_period(t) if j != i else None
            if sub:
                combined = combine_year_sub(p.year, sub, provisional=p.provisional)
                if combined:
                    return combined, {i, j}
    return p, {i}


def _hint(stacks: list[list[str]]) -> str | None:
    """The dominant period frequency in the header; a row of real dates is read as a whole (all 1st-of-month = monthly)."""
    freqs: Counter[str] = Counter()
    dates: list[date] = []
    for stack in stacks:
        for t in stack:
            p = parse_period(t)
            if p is None:
                continue
            if p.freq in "MQHA":
                freqs[p.freq] += 1
            elif p.freq == "D":
                dates.append(p.start)
    if len(dates) >= 2:
        f = infer_date_freq(dates)
        if f:
            freqs[f] += len(dates)
    return freqs.most_common(1)[0][0] if freqs else None


@dataclass
class Overrides:
    """Manual corrections to automatic detection. Indices are 0-based positions in the (trimmed) grid."""

    header_rows: list[int] | None = None
    first_data_row: int | None = None
    last_data_row: int | None = None
    n_label_cols: int | None = None
    orientation: str | None = None  # periods_in_columns | periods_in_rows | month_by_year | cross_section; None = automatic

    def is_empty(self) -> bool:
        return not (self.header_rows or self.first_data_row is not None or self.last_data_row is not None
                    or self.n_label_cols is not None or self.orientation)


@dataclass
class _Orient:
    orientation: str = "cross_section"
    period_col: int | None = None
    row_periods: dict = field(default_factory=dict)
    subs: dict = field(default_factory=dict)  # month/quarter names down the rows: row -> ('M', 3)
    years: dict = field(default_factory=dict)  # years down the rows (months across): row -> 2024
    kind: str = ""  # 'rows' | 'columns' for month_by_year


def _auto_orientation(w, data_rows, label_cols, remaining, stacks, col_period, period_cols, numeric_remaining, hint) -> _Orient:
    o = _Orient()
    if period_cols and len(period_cols) >= max(2, int(0.5 * len(numeric_remaining))):
        o.orientation = "periods_in_columns"
        if all(col_period[c].freq == "A" for c in period_cols):
            comp = _composite(w, data_rows, label_cols, remaining, stacks, col_period)
            if comp:
                o.period_col, payload, o.kind = comp
                o.orientation = "month_by_year"
                o.subs = payload if o.kind == "rows" else {}
    if o.orientation == "cross_section":
        comp = _composite(w, data_rows, label_cols, remaining, stacks, col_period)
        if comp:
            o.period_col, payload, o.kind = comp
            o.orientation = "month_by_year"
            if o.kind == "columns":
                o.years = payload
            else:
                o.subs = payload
        else:
            found = _period_column(w, data_rows, (label_cols + remaining)[:3], hint)
            if found is not None:
                o.period_col, o.row_periods = found
                o.orientation = "periods_in_rows"
    return o


def _forced_orientation(kind, w, data_rows, label_cols, remaining, stacks, col_period, period_cols, hint) -> _Orient | None:
    """The requested layout if it is actually possible for this table, else ``None``."""
    if kind == "cross_section":
        return _Orient()
    if kind == "periods_in_columns":
        return _Orient("periods_in_columns") if period_cols else None
    if kind == "periods_in_rows":
        found = _period_column(w, data_rows, (label_cols + remaining)[:3], hint, min_share=0.5)
        return _Orient("periods_in_rows", found[0], found[1]) if found else None
    if kind == "month_by_year":
        comp = _composite(w, data_rows, label_cols, remaining, stacks, col_period)
        if not comp:
            return None
        o = _Orient("month_by_year", comp[0], kind=comp[2])
        o.subs, o.years = (comp[1], {}) if comp[2] == "rows" else ({}, comp[1])
        return o
    return None


def _period_column(w: _Work, data_rows: list[int], candidates: list[int], hint: str | None, min_share: float = 0.8):
    """A column whose data cells are periods running down the rows (years, quarters, months)."""
    for c in candidates:
        found: dict[int, Period] = {}
        considered = 0
        for r in data_rows:
            v = w.raw[r][c]
            if v is None or glossary.is_total_label(clean_text(v)):
                continue
            considered += 1
            if isinstance(v, float) and not v.is_integer():
                continue
            p = parse_period(v, hint=hint)
            if p is not None:
                found[r] = p
        if considered >= 2 and len(found) >= min_share * considered:
            order = [p.sort_key for p in found.values()]
            if order == sorted(order) or order == sorted(order, reverse=True):
                return c, found
    return None


def _composite(w: _Work, data_rows: list[int], label_cols: list[int], remaining: list[int],
               stacks: dict[int, list[str]], col_period: dict[int, Period | None]):
    """Month/quarter names down the rows under year columns, or the transpose.

    Returns ``(period_col, payload, kind)``: ``kind == 'rows'`` when the sub-periods run down the rows
    (payload: row -> ('M', 3)), ``'columns'`` when years run down the rows (payload: row -> year).
    """
    year_cols = [c for c in remaining if col_period.get(c) is not None and col_period[c].freq == "A"]
    if len(year_cols) >= 2:
        for c in label_cols[:2]:
            subs: dict[int, tuple[str, int]] = {}
            considered = 0
            for r in data_rows:
                v = w.raw[r][c]
                if v is None or glossary.is_total_label(clean_text(v)):
                    continue
                considered += 1
                s = sub_period(clean_text(v))
                if s:
                    subs[r] = s
            if considered >= 3 and len(subs) >= 0.8 * considered:
                return c, subs, "rows"
    sub_cols = [c for c in remaining if any(sub_period(t) for t in stacks[c])]
    if len(sub_cols) >= 2:
        for c in (label_cols + remaining)[:3]:
            if c in sub_cols:
                continue
            years: dict[int, int] = {}
            considered = 0
            for r in data_rows:
                v = w.raw[r][c]
                if v is None:
                    continue
                considered += 1
                if _is_year_like(v):
                    years[r] = _year_value(v)
            if considered >= 2 and len(years) >= 0.8 * considered:
                return c, years, "columns"
    return None


def _title_fields(titles: list[str]) -> dict[str, str | None]:
    """Pair consecutive Albanian/English lines; the first pair is the dataset title, the last the measure."""
    out: dict[str, str | None] = {"title_sq": None, "title_en": None, "measure_sq": None, "measure_en": None}
    pairs: list[tuple[str | None, str | None]] = []
    i = 0
    while i < len(titles):
        t = titles[i]
        lang = detect_language(t)
        if i + 1 < len(titles) and {lang, detect_language(titles[i + 1])} == {"sq", "en"}:
            pairs.append((t, titles[i + 1]) if lang == "sq" else (titles[i + 1], t))
            i += 2
            continue
        pairs.append((None, t) if lang == "en" else (t, None))
        i += 1
    # parenthesised lines ("(2021 - 2025*, me çmime korente)") and bare unit lines are not titles
    body = [p for p in pairs if not all((x or "").startswith("(") or _is_unit_line(x or "") for x in p if x)]
    pairs = body or pairs
    if pairs:
        out["title_sq"], out["title_en"] = pairs[0]
    if len(pairs) > 1:
        out["measure_sq"], out["measure_en"] = pairs[-1]
    return out


_PLACE = r"[A-ZËÇ][\w'’-]*(?:\s+[A-ZËÇ][\w'’-]*){0,2}"
_SCOPE_RE = re.compile(
    rf"^(?:(?P<sq>(?i:qarku|bashkia|rrethi|komuna))\s+(?P<n_sq>{_PLACE})(?:\s*[|/]\s*(?P<en>(?i:prefecture|municipality|district|commune))\s+(?P<n_en>{_PLACE}))?"
    rf"|(?P<en2>(?i:prefecture|municipality|district|commune))\s+(?P<n_en2>{_PLACE}))$")
_SCOPE_KIND = {"qarku": "Prefecture", "prefecture": "Prefecture", "bashkia": "Municipality", "municipality": "Municipality",
               "rrethi": "District", "district": "District", "komuna": "Commune", "commune": "Commune"}


_PLACE_KIND = {"county": "Prefecture", "municipality": "Municipality"}


def _scope_line(text: str) -> tuple[str, str] | None:
    """``'Qarku Berat | Prefecture Berat'`` -> ``('Prefecture', 'Berat')``: a line under the title that says which place
    the whole table is about (INSTAT's per-prefecture sheets). A bare place name, the caption ``BERAT``, does the same."""
    text = clean_text(text)
    m = _SCOPE_RE.match(text)
    if not m:
        tag = glossary.tag_of(text)
        return (_PLACE_KIND[tag], glossary.translate(text) or text) if tag in _PLACE_KIND else None
    word = (m.group("en") or m.group("en2") or m.group("sq")).lower()
    return _SCOPE_KIND[word], (m.group("n_en") or m.group("n_en2") or m.group("n_sq")).strip()


def _is_unit_line(text: str) -> bool:
    """A short line that only states a unit, e.g. ``miliardë lekë/billion ALL`` or ``(në lekë)``."""
    if not text or len(text) > 45:
        return False
    u = parse_units(text)
    return bool(u.scale or (u.unit and not u.unit_weak)) and u.unit != "index"


def _period_from_titles(titles: list[str]) -> Period | None:
    for t in reversed(titles):
        rng = re.search(r"((?:19|20)\d{2})\s*[-–—]\s*((?:19|20)\d{2})", t)
        if rng:
            return parse_period(f"{rng.group(1)}-{rng.group(2)}")
        m = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", t)
        if m:
            return parse_period(m.group(1))
    return None


def _code_level(code: str, parents: list[tuple[str, int]]) -> tuple[int | None, str | None]:
    """Depth of a dotted hierarchical code (``01.`` -> 1, ``01.1.`` -> 2, ``01.1.1.`` -> 3) and its parent."""
    c = code.strip()
    if not _DOTTED_CODE_RE.match(c) or len(c) == 6 and "." not in c:
        return None, None
    depth = len([p for p in c.strip(".").split(".") if p])
    while parents and parents[-1][1] >= depth:
        parents.pop()
    parent = parents[-1][0] if parents else None
    parents.append((c, depth))
    return depth, parent


def _row_specs(w: _Work, data_rows: list[int], columns: list[ColumnSpec], label_cols: list[int],
               row_periods: dict[int, Period], section_rows: list[int]) -> list[RowSpec]:
    code_col = next((c.col for c in columns if c.kind == "code"), None)
    # a blank label cell repeats the one above only in a grouping column (a sex or age written once per block). In a
    # column that is filled in on almost every row, a blank is a gap: the NACE code of a "TOTAL OUTPUT" row is no code.
    fill_down = {c for c in label_cols[:-1] if c != code_col
                 and sum(1 for r in data_rows if not w.txt(r, c)) >= 0.25 * len(data_rows)}
    sections = sorted((r, strip_leading_marker(w.row_text(r))) for r in section_rows)
    si, current_section = 0, None
    last: dict[int, str] = {}
    parents: list[tuple[str, int]] = []
    specs: list[RowSpec] = []
    for r in data_rows:
        while si < len(sections) and sections[si][0] < r:
            current_section = sections[si][1] or current_section
            si += 1
        labels: list[str] = []
        origs: list[str] = []
        code: str | None = None
        for c in label_cols:
            t = w.txt(r, c)
            if c in fill_down:
                if t:
                    last[c] = t
                else:
                    t = last.get(c, "")
            if c == code_col:
                code = t or None
                continue
            disp, orig = _split_label(t) if t else ("", "")
            labels.append(disp)
            origs.append(orig)
        if not labels and code:
            labels, origs = [code], [code]
        is_total = any(glossary.is_total_label(x) for x in origs + labels if x)
        level = parent = None
        if code:
            level, parent = _code_level(code, parents)
        specs.append(RowSpec(r, labels, origs, code, level, parent, is_total, current_section, row_periods.get(r)))
    if not code_col:
        _indent_levels(w, specs, name_col=next((c for c in label_cols), None))
    return specs


def _indent_levels(w: _Work, specs: list[RowSpec], name_col: int | None) -> None:
    """Hierarchy written as indentation in the first label column (``'  Milk'``, ``'    Cheese'``)."""
    if name_col is None:
        return
    indents = {}
    for rs in specs:
        raw = w.raw[rs.row][name_col]
        indents[rs.row] = len(raw) - len(raw.lstrip(" \u00a0\t")) if isinstance(raw, str) else 0
    distinct = sorted(set(indents.values()))
    if len(distinct) < 2 or len(specs) < 4:
        return
    rank = {v: i + 1 for i, v in enumerate(distinct)}
    stack: list[tuple[int, str]] = []
    for rs in specs:
        lvl = rank[indents[rs.row]]
        while stack and stack[-1][0] >= lvl:
            stack.pop()
        rs.level = lvl
        rs.parent_code = stack[-1][1] if stack else None
        stack.append((lvl, rs.labels[0] if rs.labels else ""))


def _apply_row_overrides(w: _Work, kinds: list[str], ov: Overrides) -> None:
    """Force the data region and header rows chosen by the user."""
    if ov.first_data_row is not None or ov.last_data_row is not None:
        lo = ov.first_data_row if ov.first_data_row is not None else 0
        hi = ov.last_data_row if ov.last_data_row is not None else w.R - 1
        for r in range(w.R):
            if r < lo or r > hi:
                if kinds[r] == "D":
                    kinds[r] = "S"
            elif kinds[r] in ("H", "Y", "A", "S", "T") and any(looks_numeric(v) for v in w.raw[r] if v is not None):
                kinds[r] = "D"
    for r in ov.header_rows or []:
        if 0 <= r < w.R and kinds[r] != "E":
            kinds[r] = "H"


def analyze_grid(grid: Grid, overrides: Overrides | None = None) -> list[TableSpec]:
    """Detect every table on a sheet. Returns ``[]`` for text-only sheets (covers, contents).

    ``overrides`` applies the user's manual corrections (see :class:`Overrides`)."""
    w = _Work(grid)
    if not w.R or not w.C:
        return []
    kinds = ["E" if r in grid.hidden_rows else _row_kind(w.raw[r]) for r in range(w.R)]
    for r in w.banner_rows:
        kinds[r] = "T"
    _reclassify_lone_year_headers(w, kinds)
    _reclassify_sequence_headers(w, kinds)
    _reclassify_lone_column_headers(w, kinds)
    if overrides and not overrides.is_empty():
        _apply_row_overrides(w, kinds, overrides)
    runs = _runs(kinds)
    tables: list[TableSpec] = []
    prev_last = -1
    gaps: list[tuple[list[int], list[int]]] = []
    for first, _last in runs:
        gaps.append(_split_gap(w, kinds, prev_last, first))
        prev_last = _last
    for i, (first, last) in enumerate(runs):
        pre = gaps[i][1]
        if i + 1 < len(runs):
            notes = gaps[i + 1][0]
        else:
            notes = [r for r in range(last + 1, w.R) if kinds[r] != "E"]
        spec = _build_table(w, kinds, first, last, pre, notes, overrides if len(runs) == 1 else None)
        if spec is not None:
            tables.append(spec)
    if overrides and not overrides.is_empty() and len(runs) > 1:
        for spec in tables:
            spec.warnings.append(tr("Manual corrections only work on a sheet with one table, and this sheet has several."))
    return tables


def _build_table(w: _Work, kinds: list[str], first: int, last: int, pre: list[int], note_rows: list[int],
                 overrides: Overrides | None = None) -> TableSpec | None:
    warnings: list[str] = []
    reasons: list[str] = []
    annotation_rows, sections_above, header_rows, title_rows = _find_header(w, kinds, pre)
    if overrides and overrides.header_rows:
        header_rows = sorted(r for r in overrides.header_rows if 0 <= r < w.R)
        title_rows = [r for r in range(min(header_rows)) if kinds[r] not in ("E", "D") and r not in header_rows] if header_rows else title_rows
        reasons.append(tr("The header rows were set by hand."))
    data_rows = [r for r in range(first, last + 1) if kinds[r] == "D"]
    section_rows = [r for r in range(first, last + 1) if kinds[r] == "T"] + sections_above

    data_cols = sorted({c for r in data_rows for c in w.nonempty_cols(r)})
    if not data_cols:
        return None
    ghost = sorted({c for r in header_rows for c in w.nonempty_cols(r)} - set(data_cols))
    if ghost:
        warnings.append(tn(len(ghost), "{n} header cell above a column with no data was ignored.",
                           "{n} header cells above columns with no data were ignored."))

    prof = {c: _profile(w, c, data_rows) for c in data_cols}
    lowest = {c for c in data_cols if header_rows and w.txt(header_rows[-1], c)}
    split = {c: _header_stack(w, header_rows, c, lowest) if header_rows else ([], []) for c in data_cols}
    stacks = {c: texts for c, (texts, _rows) in split.items()}
    stack_rows = {c: rows for c, (_texts, rows) in split.items()}
    hint = _hint(list(stacks.values()))
    band = _band_languages(w, header_rows, data_cols)
    tail = _band_languages(w, header_rows[-2:], data_cols) if len(header_rows) >= 3 else None  # hierarchy above an sq/en pair
    if band:
        reasons.append(tr("The header is a pair of rows, one in Albanian and one in English."))
    elif tail:
        reasons.append(tr("The last two header rows are a pair, one in Albanian and one in English."))

    # leading label columns
    label_cols: list[int] = []
    for c in data_cols:
        if (prof[c].numeric_frac >= 0.6 and not _is_code_header(" ".join(stacks[c]))
                and not _is_ordinal_column(w, data_rows, c, stacks[c])):
            break
        label_cols.append(c)
    if overrides and overrides.n_label_cols is not None:
        label_cols = data_cols[: max(0, overrides.n_label_cols)]
        reasons.append(tr("The number of label columns was set by hand ({n}).", n=len(label_cols)))
    remaining = [c for c in data_cols if c not in label_cols]

    col_period: dict[int, Period | None] = {}
    consumed: dict[int, set[int]] = {}
    age_bands = _is_age_band_run([stacks[c][-1] for c in remaining if stacks[c]])
    if age_bands:
        hint = None
    for c in remaining:
        col_period[c], consumed[c] = (None, set()) if age_bands else _column_period(stacks[c], hint)
    period_cols = [c for c in remaining if col_period[c] is not None]
    numeric_remaining = [c for c in remaining if prof[c].numeric_frac >= 0.5]

    # orientation (automatic, unless the user asked for a specific layout)
    o = _auto_orientation(w, data_rows, label_cols, remaining, stacks, col_period, period_cols, numeric_remaining, hint)
    if overrides and overrides.orientation and overrides.orientation != o.orientation:
        forced = _forced_orientation(overrides.orientation, w, data_rows, label_cols, remaining, stacks, col_period, period_cols, hint)
        if forced is None:
            warnings.append(tr("The layout you asked for ('{layout}') does not fit this table, so the automatic reading was kept.",
                               layout=overrides.orientation))
        else:
            o = forced
            reasons.append(tr("The layout was set by hand."))
            if o.orientation == "cross_section":  # no time axis: ignore any period-looking headers
                col_period = dict.fromkeys(remaining)
                period_cols = []
    orientation, period_col, row_periods = o.orientation, o.period_col, o.row_periods
    composite_subs, composite_years, composite_kind = o.subs, o.years, o.kind
    if period_col is not None:
        if period_col in label_cols:
            label_cols.remove(period_col)
        remaining = [c for c in remaining if c != period_col]

    # column specs
    columns: list[ColumnSpec] = []
    for c in data_cols:
        stack = stacks[c]
        if c == period_col:
            columns.append(ColumnSpec(c, "period", name=_best_header(stack, band)))
        elif c in label_cols:
            texts = [w.txt(r, c) for r in data_rows if w.raw[r][c] is not None]
            kind = "code" if (_is_code_header(" ".join(stack)) or _looks_like_codes(texts)) else "label"
            columns.append(ColumnSpec(c, kind, name=_best_header(stack, band)))
        elif prof[c].numeric_frac >= 0.5:
            needs_period = orientation == "periods_in_columns" or (orientation == "month_by_year" and composite_kind == "rows")
            if needs_period and col_period.get(c) is None:
                columns.append(ColumnSpec(c, "attr", name=_best_header(stack, band)))
                continue
            kept = [i for i in range(len(stack)) if not (needs_period and i in consumed.get(c, ()))]
            paired = tail is not None and [stack_rows[c][i] for i in kept][-2:] == header_rows[-2:]
            sq, en = _bilingual_path([stack[i] for i in kept], band, tail if paired else None)
            columns.append(ColumnSpec(c, "value", name=" | ".join(en or sq), path_sq=sq, path_en=en,
                                      period=col_period.get(c)))
        else:
            columns.append(ColumnSpec(c, "attr_text", name=_best_header(stack, band)))
    value_specs = [c for c in columns if c.kind == "value"]
    if not value_specs:
        return None
    # only the first code column is "the" code; others are ordinary label dimensions
    codes = [c for c in columns if c.kind == "code"]
    for extra in codes[1:]:
        extra.kind = "label"
    _complete_total_paths(value_specs)

    if orientation in ("periods_in_rows", "cross_section"):
        _mark_ragged_measures(value_specs)
    core_specs = [c for c in value_specs if c.measure is None]
    header_constants, level_names = _drop_constant_levels(core_specs)
    if orientation == "periods_in_columns":
        _demote_repeated_periods(value_specs, warnings)
        value_specs = [c for c in columns if c.kind == "value"]

    # titles, units, notes
    titles, scope = _titles_and_scope(w, title_rows)
    tf = _title_fields(titles)
    note_texts = [strip_leading_marker(w.row_text(r)) for r in note_rows]
    units = _table_units(w, kinds, title_rows, header_rows, list(stacks.values()), titles, note_texts, data_rows, value_specs,
                         tf["title_en"] or tf["title_sq"])

    label_cols_final = [c.col for c in columns if c.kind in ("label", "code")]
    rows = _row_specs(w, data_rows, columns, label_cols_final, row_periods, section_rows)
    if orientation == "month_by_year" and composite_kind == "columns":
        for rs in rows:
            y = composite_years.get(rs.row)
            rs.period = parse_period(y) if y else None
    period_hint = _period_from_titles(titles) if orientation == "cross_section" else None
    if orientation == "month_by_year" and composite_kind == "rows":
        _attach_sub_periods(rows, composite_subs)

    periods = [c.period for c in value_specs if c.period] + [rs.period for rs in rows if rs.period]
    freq = infer_frequency([p for p in periods if not p.label.startswith("sub:")])
    if orientation == "month_by_year":
        freq = "Q" if any(v[0] == "Q" for v in composite_subs.values()) else "M"

    conf, why = _confidence(w, data_rows, value_specs, header_rows, orientation, period_cols, numeric_remaining)
    reasons.extend(why)
    if w.hidden_count:
        warnings.append(tn(w.hidden_count, "{n} hidden row or column was ignored.", "{n} hidden rows or columns were ignored."))
    if w.g.truncated:
        warnings.append(tr("The sheet was larger than the reader limits, so it was cut short."))
    if not header_rows:
        warnings.append(tr("No header row was found, so the columns have no labels."))
    if annotation_rows:
        reasons.append(tn(len(annotation_rows), "{n} row of column numbers or formulas was skipped.",
                          "{n} rows of column numbers or formulas were skipped."))

    header_is_dim = _header_names_categories(core_specs) if orientation in ("periods_in_rows", "cross_section") else True

    return TableSpec(
        sheet=w.g.name, orientation=orientation, title_rows=title_rows, header_rows=header_rows, data_rows=data_rows,
        note_rows=note_rows, annotation_rows=annotation_rows, section_rows=sorted(set(section_rows)), columns=columns,
        rows=rows, titles=titles, title_sq=tf["title_sq"], title_en=tf["title_en"], measure_sq=tf["measure_sq"],
        measure_en=tf["measure_en"], notes=[t for t in note_texts if t], units=units, period_hint=period_hint,
        header_is_dimension=header_is_dim, freq=freq, confidence=conf, warnings=warnings, reasons=reasons,
        label_header=[c.name for c in columns if c.kind == "label"], origin=w.g.origin,
        header_constants=header_constants, header_level_names=level_names, scope=scope, header_pair=bool(band or tail),
    )


def _mark_ragged_measures(value_specs: list[ColumnSpec]) -> None:
    """A column with a shorter header than its siblings (one cell merged down the header rows) stands for another measure:
    next to "Women by number of children: 0, 1, 2 ..." it is "Total number of children"."""
    depth = max((len(c.path_en or c.path_sq) for c in value_specs), default=0)
    ragged = [c for c in value_specs if 0 < len(c.path_en or c.path_sq) < depth]
    if depth >= 2 and ragged and len(ragged) <= len(value_specs) / 3:
        for c in ragged:
            c.measure = " – ".join(c.path_en or c.path_sq)


def _drop_constant_levels(core_specs: list[ColumnSpec]) -> tuple[list[str], list[str]]:
    """Header levels identical for every value column (a group title over all the years) carry no information and are
    taken out of the column paths. Returns the removed texts and, for each level that stays, the banner that names it."""
    if len(core_specs) < 2:
        return [], []
    depth = max(len(c.path_en) for c in core_specs)
    drop: set[int] = set()
    constants: list[str] = []
    for j in range(depth):
        vals = {(c.path_en[j] if j < len(c.path_en) else None) for c in core_specs}
        if len(vals) == 1 and None not in vals:
            drop.add(j)
            constants.append(next(iter(vals)))
    if not drop:
        return [], []
    first = core_specs[0].path_en
    # a banner over a level names it: "Sex" above Total / Male / Female; "Prefecture" above the county names
    level_names = [next((first[k] for k in sorted(drop, reverse=True) if k < j), "") for j in range(depth) if j not in drop]
    for c in core_specs:
        c.path_en = [t for j, t in enumerate(c.path_en) if j not in drop]
        c.path_sq = [t for j, t in enumerate(c.path_sq) if j not in drop]
        c.name = " | ".join(c.path_en or c.path_sq)
    return constants, level_names


def _demote_repeated_periods(value_specs: list[ColumnSpec], warnings: list[str]) -> None:
    """A repeated period (e.g. a "2025/2024" change column) is derived from the others: it stays as an attribute."""
    seen: set[tuple] = set()
    for c in value_specs:
        key = (tuple(c.path_sq), tuple(c.path_en), c.period.label)
        if key in seen:
            c.kind = "attr"
            warnings.append(tr("Column {name} repeats the period {period}, so it was kept as an attribute.", name=c.name or c.col,
                               period=c.period.label))
        seen.add(key)


def _titles_and_scope(w: _Work, title_rows: list[int]) -> tuple[list[str], list[str]]:
    titles = [t for t in (strip_leading_marker(w.row_text(r)) for r in title_rows) if t]
    titles = [sentence_case(_TABLE_PREFIX_RE.sub("", t) or t) for t in titles]  # drop "Tab.7", tame ALL CAPS
    scope = [s for s in (_scope_line(t) for t in titles[1:]) if s]
    if scope:  # "Qarku Berat | Prefecture Berat" scopes the table; it is not a title or a measure
        titles = [t for i, t in enumerate(titles) if i == 0 or _scope_line(t) is None]
    return titles, scope


def _table_units(w: _Work, kinds: list[str], title_rows: list[int], header_rows: list[int], stacks: list[list[str]],
                 titles: list[str], note_texts: list[str], data_rows: list[int], value_specs: list[ColumnSpec],
                 title: str) -> UnitInfo:
    """Unit, scale and base period from the lines near the header, the headers, the titles and the notes."""
    units = UnitInfo()
    if header_rows:
        for r in reversed([r for r in title_rows if kinds[r] == "T" and r >= header_rows[0] - 3]):
            units.merge(parse_units(w.row_text(r)))
    units.merge(parse_units(*[" ".join(s) for s in stacks[:40]]))
    units.merge(parse_units(*titles))
    units.merge(parse_units(*note_texts))
    if w.g.pct_cells and units.unit is None:
        hits = sum(1 for r in data_rows for c in value_specs if (r, c.col) in w.g.pct_cells)
        if hits >= 0.5 * len(data_rows) * len(value_specs):
            units.unit = "%"
    subject = subject_unit(title)
    if subject and units.unit in (None, "count", "years", "persons"):
        units.unit, units.unit_weak = subject, False  # what the title says is being counted
    return units


def _header_names_categories(core_specs: list[ColumnSpec]) -> bool:
    """Header text names categories (sex, age bands, regions ...) rather than measures when any level looks like that."""
    paths = [c.path_en or c.path_sq for c in core_specs]
    for j in range(max((len(p) for p in paths), default=0)):
        level = [p[j] for p in paths if len(p) > j]
        tag, _share = glossary.dominant_tag(level)
        parts = [v for v in level if not glossary.is_generic_total(v)]
        small_ints = len(parts) >= 3 and all(re.fullmatch(r"\d{1,3}", v) for v in parts)  # single ages, class numbers
        # a "Total" next to other columns means the others are its categories (Total | Male | Female)
        has_total = len(parts) < len(level) and len(set(parts)) >= 2
        if tag in DIM_TAGS or glossary.looks_like_age_band(level) or small_ints or has_total:
            return True
    return False


def _attach_sub_periods(rows: list[RowSpec], subs: dict[int, tuple[str, int]]) -> None:
    """Month/quarter markers for tidy(): stored on the row as a placeholder period ``sub:M3``."""
    from datetime import date

    for rs in rows:
        s = subs.get(rs.row)
        if s:
            rs.period = Period(f"sub:{s[0]}{s[1]}", s[0], date(2000, 1, 1), date(2000, 1, 1))


def _confidence(w: _Work, data_rows: list[int], value_specs: list[ColumnSpec], header_rows: list[int],
                orientation: str, period_cols: list[int], numeric_remaining: list[int]) -> tuple[float, list[str]]:
    conf, why = 1.0, []
    if not header_rows:
        conf *= 0.6
        why.append(tr("No header row was found."))
    cells = bad = 0
    for r in data_rows:
        for c in value_specs:
            v = w.raw[r][c.col]
            if v is None:
                continue
            cells += 1
            bad += not looks_numeric(v)
    if cells and bad / cells > 0.02:
        conf *= max(0.4, 1 - bad / cells)
        why.append(tr("{bad} of {cells} value cells were not numbers.", bad=num(bad), cells=num(cells)))
    if orientation == "periods_in_columns":
        stray = [c for c in numeric_remaining if c not in period_cols]
        if stray:
            conf *= 0.92
            why.append(tn(len(stray), "{n} numeric column without a period in its header was kept as an attribute.",
                          "{n} numeric columns without a period in their headers were kept as attributes."))
    if orientation == "cross_section":
        conf *= 0.85
        why.append(tr("No time axis was found, so the table was read as a snapshot of categories."))
    if len(data_rows) < 2:
        conf *= 0.6
        why.append(tr("There are fewer than two data rows."))
    return round(conf, 3), why
