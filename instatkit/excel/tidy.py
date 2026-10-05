"""Turn a detected :class:`~instatkit.excel.layout.TableSpec` into a tidy (long) DataFrame.

One row per observation: ``series_id``, dimension columns (``dim_1`` ...), ``measure``, ``period`` (+ start /
end / freq), ``value``, ``flag``, ``unit`` and ``src_ref`` (the original cell, e.g. ``D7``) so any number can be
traced back to the spreadsheet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from .. import config
from ..i18n import language, pick, tn, tr
from ..semantics import glossary
from ..semantics.numbers import parse_number
from ..semantics.periods import Period, combine_year_sub, sub_period
from ..semantics.textnorm import clean_text
from ..semantics.units import unit_text
from .grid import Grid, Workbook
from .layout import Overrides, RowSpec, TableSpec, analyze_grid

_CURRENCIES = frozenset({"ALL", "EUR", "USD"})


@dataclass
class TidyTable:
    table_id: str
    sheet: str
    spec: TableSpec
    df: pd.DataFrame
    dim_columns: list[str]
    dim_info: dict[str, dict] = field(default_factory=dict)  # dim -> {'source': row|column|section, 'header': str}
    title_en: str | None = None
    title_sq: str | None = None
    measure: str | None = None
    measure_names: dict[str, str] = field(default_factory=dict)  # a measure's English name -> the file's Albanian name
    label_words: dict[str, str] = field(default_factory=dict)  # a category's English name -> the file's Albanian name (set by interpret)
    warnings: list[str] = field(default_factory=list)
    parts: list[TidyTable] = field(default_factory=list)  # the repeated tables this one combines (see excel/stack.py)

    @property
    def title(self) -> str:
        """The title in the language that is switched on, when the file has one in that language."""
        return pick(self.title_en, self.title_sq, self.sheet)

    @property
    def reading_title(self) -> str:
        """The title the program reasons with. It does not depend on the language, so a table is read the same way in both."""
        return self.title_en or self.title_sq or self.sheet

    def measure_label(self, name: str) -> str:
        """A measure's name as it is shown: the file's own Albanian name, else the glossary's, else the name itself."""
        if language() != "sq":
            return name
        return self.measure_names.get(name) or glossary.display(name)

    @property
    def confidence(self) -> float:
        return self.spec.confidence

    def wording(self):
        """A context in which ``glossary.display`` knows the Albanian words this file uses for its own categories."""
        return glossary.file_words(self.label_words)

    def localized_df(self) -> pd.DataFrame:
        """The tidy frame with category and measure names in the language that is switched on (the original text stays in
        the ``_orig`` columns). In English it is the frame itself."""
        if language() != "sq":
            return self.df
        df = self.df.copy()
        with self.wording():
            for col in self.dim_columns:
                df[col] = df[col].map(lambda v: glossary.display(v) if isinstance(v, str) else v)
            df["measure"] = df["measure"].map(self.measure_label)
        return df

    def to_wide(self) -> pd.DataFrame:
        """Back to a human-friendly single-header layout: one row per series, one column per period."""
        df = self.localized_df()
        if df.empty:
            return pd.DataFrame()
        keys = ["measure"] + self.dim_columns + [c for c in ("code", "section") if c in df.columns]
        if df["period"].eq("").all():
            return df[keys + ["value", "flag"]].reset_index(drop=True)
        order = df.drop_duplicates("period").sort_values("period_start")["period"].tolist()
        wide = df.groupby(keys + ["period"], sort=False)["value"].first().unstack("period")
        wide = wide[[p for p in order if p in wide.columns]]
        wide.columns = [str(c) for c in wide.columns]
        return wide.reset_index()


@dataclass
class WorkbookResult:
    tables: list[TidyTable]
    skipped: list[tuple[str, str]]  # (sheet, reason)
    meta: dict
    warnings: list[str]
    workbook: Workbook


def _period_for(spec: TableSpec, rs: RowSpec, col) -> Period | None:
    o = spec.orientation
    if o == "periods_in_columns":
        return col.period
    if o == "periods_in_rows":
        return rs.period
    if o == "month_by_year":
        if rs.period is not None and rs.period.label.startswith("sub:"):  # month/quarter names down the rows
            kind, n = rs.period.label[4], int(rs.period.label[5:])
            return combine_year_sub(col.period.year, (kind, n)) if col.period else None
        sub = sub_period((col.path_en or col.path_sq or [""])[-1]) if (col.path_en or col.path_sq) else None
        if rs.period is not None and sub:  # years down the rows, months/quarters across
            return combine_year_sub(rs.period.year, sub)
        return None
    return col.period or spec.period_hint


def _pct_scale(grid: Grid, spec: TableSpec) -> float:
    """Values formatted as percentages but stored as fractions (0.123 shown as 12.3%) are scaled by 100."""
    if not grid.pct_cells or spec.units.unit not in (None, "%"):
        return 1.0
    vals, pct = [], 0
    for rs in spec.rows:
        for c in spec.value_cols:
            v = grid.cells[rs.row][c.col]
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                vals.append(abs(v))
                pct += (rs.row, c.col) in grid.pct_cells
    if vals and pct >= 0.8 * len(vals) and max(vals) <= 1.5:
        return 100.0
    return 1.0


def build_table(grid: Grid, spec: TableSpec, table_id: str | None = None) -> TidyTable:
    value_cols = spec.value_cols
    n_label = max((len(rs.labels) for rs in spec.rows), default=0)
    hdr_levels = max((len(c.path_en or c.path_sq) for c in value_cols if c.measure is None), default=0) if spec.header_is_dimension else 0
    if spec.orientation == "month_by_year":
        hdr_levels = 0  # header cells carry the period, not a category
    n_scope = len(spec.scope)
    dim_columns = [f"dim_{i + 1}" for i in range(n_label + hdr_levels + n_scope)]
    dim_info: dict[str, dict] = {}
    for i in range(n_label):
        dim_info[dim_columns[i]] = {"source": "row", "header": spec.label_header[i] if i < len(spec.label_header) else ""}
    for j in range(hdr_levels):
        names = spec.header_level_names
        dim_info[dim_columns[n_label + j]] = {"source": "column", "header": names[j] if j < len(names) else ""}
    scope_values = [value for _label, value in spec.scope]
    for k, (label, _value) in enumerate(spec.scope):  # constant dimensions named by a line under the title
        dim_info[dim_columns[n_label + hdr_levels + k]] = {"source": "scope", "header": label}
    has_code = any(rs.code for rs in spec.rows)
    has_level = has_code or any(rs.level is not None for rs in spec.rows)
    has_section = any(rs.section for rs in spec.rows)
    # keep the label exactly as written in the file whenever translation changed it (traceability)
    orig_cols = {i: f"{dim_columns[i]}_orig" for i in range(n_label)
                 if any(i < len(rs.labels) and i < len(rs.labels_orig) and rs.labels_orig[i] != rs.labels[i] for rs in spec.rows)}
    default_measure = spec.measure_en or spec.measure_sq or spec.title_en or spec.title_sq or spec.sheet
    default_measure_sq = spec.measure_sq or spec.measure_en or spec.title_sq or spec.title_en or spec.sheet
    measure_names: dict[str, str] = {}
    scale = _pct_scale(grid, spec)
    unit_label = spec.units.label or ""
    attr_cols = {}
    for c in spec.columns:
        if c.kind in ("attr", "attr_text"):
            name = "attr_" + (re.sub(r"\W+", "_", (c.name or f"col{c.col}").lower()).strip("_") or f"col{c.col}")
            while name in attr_cols.values():
                name += "_"
            attr_cols[c.col] = name

    label_words: dict[str, str] = {}  # the Albanian half of header labels written in both languages
    if spec.header_is_dimension:
        for col in value_cols:
            if col.measure is None:
                label_words.update({clean_text(en): sq for en, sq in zip(col.path_en, col.path_sq, strict=False) if en and len(sq) > 2 and sq != en})

    warnings: list[str] = list(spec.warnings)
    records: list[dict] = []
    text_cells = 0
    rows_to_read = spec.rows
    if len(spec.rows) * max(1, len(value_cols)) > config.MAX_OBSERVATIONS:
        keep = max(1, config.MAX_OBSERVATIONS // max(1, len(value_cols)))
        rows_to_read = spec.rows[:keep]
        warnings.append(tr("This table is very large: only the first {kept} of {total} rows were processed.", kept=f"{keep:,}",
                           total=f"{len(spec.rows):,}"))
    for rs in rows_to_read:
        row_dims = list(rs.labels) + [""] * (n_label - len(rs.labels))
        row_attrs = {}
        for col_idx, name in attr_cols.items():
            v = grid.cells[rs.row][col_idx]
            if v is not None:
                n = parse_number(v)
                row_attrs[name] = n.value if n.value is not None else clean_text(v)
        for col in value_cols:
            raw = grid.cells[rs.row][col.col]
            if raw is None:
                continue
            num = parse_number(raw)
            period = _period_for(spec, rs, col)
            if spec.orientation == "month_by_year" and period is None:
                continue
            flag = num.flag or ""
            if period is not None and period.provisional and flag in ("", "note"):
                flag = "p"
            if num.value is None and not num.is_marker:
                text_cells += 1
                flag = "text"
            path = (col.path_en or col.path_sq)
            path_sq = col.path_sq or col.path_en
            if spec.header_is_dimension and col.measure is not None:
                hdr = [""] * hdr_levels  # a measure of its own: no category along the header
                measure = measure_sq = col.measure
            elif spec.header_is_dimension:
                hdr = list(path) + [""] * (hdr_levels - len(path))
                measure, measure_sq = default_measure, default_measure_sq
            else:
                hdr = []
                measure = " – ".join(path) if path else default_measure
                measure_sq = " – ".join(path_sq) if path_sq else default_measure_sq
            if measure_sq != measure:
                measure_names.setdefault(measure, measure_sq)
            value = None if num.value is None else num.value * scale
            rec = {
                "measure": measure,
                "period": period.label if period else "",
                "period_start": period.start if period else pd.NaT,
                "period_end": period.end if period else pd.NaT,
                "freq": period.freq if period else "",
                "value": value,
                "flag": flag,
                "unit": unit_label,
                "src_ref": grid.a1(rs.row, col.col),
                "_dims": tuple(row_dims + hdr[:hdr_levels] + scope_values),
                "code": rs.code or "",
                "level": rs.level,
                "parent_code": rs.parent_code or "",
                "is_total": rs.is_total,
                "section": rs.section or "",
                "base_period": period.base.label if (period and period.base) else "",
                "_attrs": row_attrs,
                "_orig": tuple(rs.labels_orig[i] if i < len(rs.labels_orig) else "" for i in range(n_label)),
            }
            records.append(rec)
    if text_cells:
        warnings.append(tn(text_cells, "{n} value cell contained text instead of a number and was set to missing.",
                           "{n} value cells contained text instead of a number and were set to missing."))

    df = _frame(records, dim_columns, has_code, has_section, list(attr_cols.values()), orig_cols, has_level)
    if has_section:
        dim_info["section"] = {"source": "section", "header": "Section"}
    dup = int(df.duplicated(["series_id", "period"]).sum()) if len(df) else 0
    if dup and (df["period"] != "").any():
        warnings.append(tn(dup, "{n} duplicate observation (same series and period) was found; check the header and the labels.",
                           "{n} duplicate observations (same series and period) were found; check the header and the labels."))
    tid = table_id or re.sub(r"\W+", "_", spec.sheet).strip("_") or "table"
    return TidyTable(table_id=tid, sheet=spec.sheet, spec=spec, df=df, dim_columns=dim_columns, dim_info=dim_info,
                     title_en=spec.title_en, title_sq=spec.title_sq, measure=default_measure, measure_names=measure_names,
                     label_words=label_words, warnings=warnings)


def _frame(records: list[dict], dim_columns: list[str], has_code: bool, has_section: bool,
           attr_names: list[str], orig_cols: dict[int, str] | None = None, has_level: bool = False) -> pd.DataFrame:
    orig_cols = orig_cols or {}
    hier = (["code"] if has_code else []) + (["level", "parent_code"] if (has_code or has_level) else [])
    cols = ["series_id"] + dim_columns + list(orig_cols.values()) + hier + \
        ["is_total"] + (["section"] if has_section else []) + \
        ["measure", "period", "period_start", "period_end", "freq", "value", "flag", "unit"]
    if any(r["base_period"] for r in records):
        cols.append("base_period")
    cols += attr_names + ["src_ref"]
    if not records:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in cols})
    keys: dict[tuple, int] = {}
    rows = []
    for r in records:
        key = (r["measure"], r["_dims"], r["code"], r["section"])
        sid = keys.setdefault(key, len(keys))
        row = {"series_id": sid, **{d: (r["_dims"][i] if i < len(r["_dims"]) else "") for i, d in enumerate(dim_columns)}}
        row.update({k: r[k] for k in ("code", "level", "parent_code", "is_total", "section", "measure", "period",
                                        "period_start", "period_end", "freq", "value", "flag", "unit", "base_period", "src_ref")})
        for name in attr_names:
            row[name] = r["_attrs"].get(name)
        for i, name in orig_cols.items():
            row[name] = r["_orig"][i]
        rows.append(row)
    df = pd.DataFrame(rows)
    df = df[[c for c in cols if c in df.columns]]
    df["period_start"] = pd.to_datetime(df["period_start"])
    df["period_end"] = pd.to_datetime(df["period_end"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    if "level" in df.columns:
        df["level"] = pd.to_numeric(df["level"], errors="coerce").astype("Int64")
    return df.reset_index(drop=True)


_PUBLISHED_RE = re.compile(r"(?i)(?:publikuar|published|publication date)\s*[:\-]?\s*(\d{1,2}[./]\d{1,2}[./]\d{4})")
_UPDATED_RE = re.compile(r"(?i)(?:p[eë]rdit[eë]simi i fundit|last update[d]?|updated)\s*[:\-]?\s*(.+)")
_TAB_RE = re.compile(r"(?i)^tab(?:ela|le|\.)?[\s_.\-]*(\d+)$")


def _harvest_meta(wb: Workbook, text_sheets: list[Grid]) -> dict:
    meta: dict = {"contents": {}}
    for g in text_sheets:
        for row in g.cells:
            cells = [clean_text(v) for v in row if v is not None]
            for t in cells:
                m = _PUBLISHED_RE.search(t)
                if m:
                    meta.setdefault("published", m.group(1))
                m = _UPDATED_RE.search(t)
                if m:
                    meta.setdefault("updated", m.group(1).strip())
                if t.startswith("©"):
                    meta.setdefault("copyright", t)
                if re.match(r"(?i)^(riprodhimi|reproduction|the reproduction|reuse)", t):
                    meta.setdefault("reuse", t)
            if len(cells) >= 2:
                m = _TAB_RE.match(cells[0])
                if m:
                    meta["contents"][int(m.group(1))] = cells[1]
    if wb.properties:
        meta["properties"] = dict(wb.properties)
    return meta


def _inherit_units(specs: list[TableSpec]) -> None:
    """INSTAT's national-accounts workbooks say "in million ALL" on most sheets and leave it out on others. A sheet that
    prices its figures ("at current prices") but never names the unit takes the one its sister sheets agree on."""
    stated = {(s.units.unit, s.units.scale, s.units.scale_label) for s in specs if s.units.unit in _CURRENCIES and not s.units.unit_weak}
    if len(stated) != 1:
        return
    unit, scale, scale_label = next(iter(stated))
    for s in specs:
        u = s.units
        if u.unit is None and u.price_basis:
            u.unit, u.unit_weak, u.scale, u.scale_label = unit, True, scale, scale_label
            s.reasons.append(tr("The unit is not stated on this sheet; {unit} is taken from the other sheets of the workbook.", unit=unit_text(u.label)))


def extract_tables(wb: Workbook, *, include_hidden: bool = False, overrides: dict[str, Overrides] | None = None,
                   stack: bool = True) -> WorkbookResult:
    """Detect and tidy every table in a workbook. Text-only sheets (cover, contents) feed the metadata.

    ``overrides`` maps a sheet name to the user's manual corrections for that sheet. With ``stack`` the same table
    repeated per prefecture, per sheet or per block is combined into one (see :mod:`instatkit.excel.stack`)."""
    tables: list[TidyTable] = []
    skipped: list[tuple[str, str]] = []
    text_sheets: list[Grid] = []
    seen_ids: dict[str, int] = {}
    analysed: list[tuple[Grid, list[TableSpec]]] = []
    for g in wb.sheets:
        if not g.visible and not include_hidden:
            skipped.append((g.name, tr("hidden sheet")))
            continue
        specs = analyze_grid(g, (overrides or {}).get(g.name))
        if not specs:
            text_sheets.append(g)
            skipped.append((g.name, tr("no data table (cover page, contents or notes)")))
            continue
        analysed.append((g, specs))
    _inherit_units([spec for _g, specs in analysed for spec in specs])
    for g, specs in analysed:
        for k, spec in enumerate(specs):
            base = re.sub(r"\W+", "_", g.name).strip("_") or "sheet"
            tid = base if len(specs) == 1 else f"{base}_{k + 1}"
            n = seen_ids.get(tid, 0)
            seen_ids[tid] = n + 1
            tid = tid if n == 0 else f"{tid}_{n + 1}"
            tables.append(build_table(g, spec, tid))
    meta = _harvest_meta(wb, text_sheets)
    # contents sheet: "tab 1" -> title, matched to sheets named like _tab_1 / Tab1 / Tabela 1
    for t in tables:
        if not (t.title_en or t.title_sq):
            m = re.search(r"(\d+)\s*$", t.sheet)
            if m and int(m.group(1)) in meta["contents"]:
                t.title_sq = meta["contents"][int(m.group(1))]
    if stack and len(tables) > 1:
        from .stack import stack_tables  # local import: stack builds on TidyTable

        tables = stack_tables(tables, {g.name: g for g in wb.sheets})
    warnings = list(wb.warnings)
    for t in tables:
        if t.confidence < 0.6:
            warnings.append(tr("Sheet '{sheet}': the layout was hard to recognise ({confidence} confidence). Check \"How it was read\".",
                               sheet=t.sheet, confidence=f"{t.confidence:.0%}"))
    return WorkbookResult(tables=tables, skipped=skipped, meta=meta, warnings=warnings, workbook=wb)
