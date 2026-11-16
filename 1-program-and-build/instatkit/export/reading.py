"""A plain account of how a sheet was read (shown in the report and in the "How it was read" tab)."""

from __future__ import annotations

from ..analysis.fmt import fmt_pct, human_period
from ..excel.grid import col_letter
from ..i18n import N_, tn, tr
from ..pipeline import ProcessedTable
from ..semantics.labels import role_name
from ..semantics.units import unit_text

ORIENT_TEXT = {
    "periods_in_columns": N_("The periods run across the columns, and each row is a series."),
    "periods_in_rows": N_("The periods run down the rows, and each column is a measure."),
    "month_by_year": N_("A grid of months or quarters by year, turned into one time axis."),
    "cross_section": N_("No time axis: the categories are compared at one point in time."),
}
_PRICE_BASIS = {"current": N_("current prices"), "previous_year": N_("previous-year prices"), "constant": N_("constant prices")}


def _rows(rows: list[int], origin_row: int) -> str:
    if not rows:
        return tr("none found")
    a, b = min(rows) + origin_row + 1, max(rows) + origin_row + 1
    return tr("row {a}", a=a) if a == b else tr("rows {a} to {b}", a=a, b=b)


def _cols(cols: list[int], origin_col: int) -> str:
    if not cols:
        return tr("none")
    letters = [col_letter(c + origin_col) for c in cols]
    if len(letters) == 1:
        return letters[0]
    return f"{letters[0]}–{letters[-1]}" if cols == list(range(cols[0], cols[-1] + 1)) else ", ".join(letters)


def reading_summary(pt: ProcessedTable) -> list[tuple[str, str]]:
    spec, prof = pt.table.spec, pt.profile
    r0, c0 = spec.origin
    label_cols = [c.col for c in spec.columns if c.kind in ("label", "code")]
    value_cols = [c.col for c in spec.columns if c.kind == "value"]
    attr_cols = [c.col for c in spec.columns if c.kind in ("attr", "attr_text")]
    header_rows = _rows(spec.header_rows, r0)
    if spec.header_pair:
        header_rows += tr(" (a pair of rows, Albanian and English)")
    labels = _cols(label_cols, c0) + (f" ({', '.join(spec.label_header)})" if spec.label_header else "")
    out: list[tuple[str, str]] = [
        (tr("Sheet"), pt.table.sheet),
        (tr("Data block"), prof.source.get("cells", "")),
        (tr("Layout"), tr(ORIENT_TEXT[spec.orientation]) if spec.orientation in ORIENT_TEXT else spec.orientation),
        (tr("Title rows"), _rows(spec.title_rows, r0)),
        (tr("Header rows"), header_rows),
        (tr("Data rows"), tn(len(spec.data_rows), "{rows} ({n} row)", "{rows} ({n} rows)", rows=_rows(spec.data_rows, r0))),
        (tr("Label columns"), labels),
        (tr("Value columns"), tn(len(value_cols), "{cols} ({n} column)", "{cols} ({n} columns)", cols=_cols(value_cols, c0))),
    ]
    if attr_cols:
        out.append((tr("Attribute columns"), tr("{cols}: kept as attributes (for example weights), not as observations", cols=_cols(attr_cols, c0))))
    if spec.annotation_rows:
        out.append((tr("Skipped helper rows"), tr("{rows} (column numbers or formulas)", rows=_rows(spec.annotation_rows, r0))))
    if spec.note_rows:
        out.append((tr("Footnotes captured"), tn(len(spec.notes), "{n} line in {rows}", "{n} lines in {rows}", rows=_rows(spec.note_rows, r0))))
    if spec.header_constants:
        out.append((tr("Shared header text"), tr("{text}: applies to every value column", text="; ".join(spec.header_constants))))
    out.append((tr("Unit"), unit_text(prof.unit) or tr("not stated")))
    if prof.base_period:
        out.append((tr("Index base"), human_period(prof.base_period) if prof.base_period[:1].isdigit() else prof.base_period))
    if prof.price_basis:
        out.append((tr("Price basis"), tr(_PRICE_BASIS[prof.price_basis]) if prof.price_basis in _PRICE_BASIS else prof.price_basis))
    out.append((tr("Frequency"), tn(prof.n_periods, "{frequency} ({n} period)", "{frequency} ({n} periods)", frequency=tr(prof.freq_name))
                if prof.n_periods else tr("no periods")))
    roles = {d.name: role_name(d.role) for d in prof.dims}
    for d in prof.dims:
        value = tn(d.n_values, "{n} value: {reason}", "{n} values: {reason}", reason=d.reason)
        same = tr("; the same as {name}", name=roles.get(d.alias_of, d.alias_of)) if d.alias_of else ""
        out.append((tr("Breakdown: {name}", name=roles[d.name]), value + same))
    confidence = fmt_pct(spec.confidence * 100, 0)
    out.append((tr("Confidence"), f"{confidence}. {' '.join(spec.reasons)}" if spec.reasons else confidence))
    for w in pt.table.warnings:
        out.append((tr("Warning"), w))
    return out
