"""A clean Excel workbook: one header row, real numbers and dates, and sheets with a README, the findings and the checks."""

from __future__ import annotations

import re
from collections.abc import Iterator

import pandas as pd

from .. import __version__
from ..analysis.facts import status_text
from ..analysis.narrate import SECTION_TITLES
from ..i18n import tr
from ..pipeline import ProcessedFile
from .tables import _public_columns
from .xlsx_writer import MAX_ROWS, Sheet, Style, Workbook

_HEAD = Style(bold=True, color="FFFFFF", fill="1C5CAB", wrap=True)
_CHUNK = 10_000


def attribution() -> str:
    return tr("Source: Institute of Statistics of Albania (INSTAT), www.instat.gov.al")


def _sheet_name(base: str, used: set[str]) -> str:
    name = re.sub(r"[\[\]*?/\\:]", " ", base).strip()[:31] or "Sheet"
    cand, n = name, 2
    while cand.lower() in used:
        suffix = f" {n}"
        cand = name[: 31 - len(suffix)] + suffix
        n += 1
    used.add(cand.lower())
    return cand


def _rows(df: pd.DataFrame) -> Iterator[list]:
    """The frame's rows with missing values as ``None``, converted a chunk at a time to keep memory flat."""
    for i in range(0, len(df), _CHUNK):
        part = df.iloc[i:i + _CHUNK]
        yield from (list(row) for row in part.astype(object).where(part.notna(), None).itertuples(index=False, name=None))


def _frame_sheet(wb: Workbook, title: str, df: pd.DataFrame, *, number_format: str = "#,##0.00") -> Sheet:
    ws = wb.create_sheet(title)
    cols = list(df.columns)
    ws.header_style, ws.freeze_header, ws.autofilter = _HEAD, True, bool(len(df))
    for j, col in enumerate(cols):
        sample = [len(str(col))] + [len(str(v)) for v in df[col].head(200).tolist()]
        ws.widths[j + 1] = min(48, max(9, max(sample) + 2))
        if pd.api.types.is_float_dtype(df[col]):
            ws.column_styles[j] = Style(fmt=number_format)
    ws.rows_from([str(c) for c in cols], _rows(df.iloc[: MAX_ROWS - 1]))
    return ws


def excel_bytes(pf: ProcessedFile) -> bytes:
    src = pf.source
    title = pf.tables[0].table.title if len(pf.tables) == 1 else (src.label or src.filename)
    wb = Workbook(title)
    readme = wb.active
    readme.title = tr("README")
    used: set[str] = {readme.title.lower()}
    lines: list[tuple[str, str]] = [
        (tr("Title"), title),
        (tr("Source file"), src.filename),
        (tr("Source URL"), src.url or tr("(uploaded file)")),
        (tr("Retrieved"), src.retrieved_at),
        (tr("Last modified (server)"), src.last_modified or ""),
        ("SHA-256", src.sha256),
        (tr("Published (file cover)"), pf.meta.get("published", "")),
        (tr("Reuse notice (file cover)"), pf.meta.get("reuse", "")),
        (tr("Attribution"), tr("Demo data made by INSTAT Explorer. The numbers are invented and are not INSTAT figures.")
         if src.kind == "demo" else attribution()),
        (tr("Made by"), tr("INSTAT Explorer {version} (automatic analysis by fixed rules; check the figures against the source before you "
                           "publish them)", version=__version__)),
        ("", ""),
        (tr("Sheets"), tr("Data: one row per observation, with the original cell in src_ref. Wide: one row per series and one column per "
                          "period. Findings and Checks are written automatically.")),
    ]
    for r, (k, v) in enumerate(lines, 1):
        readme.cell(r, 1, k).style = Style(bold=True)
        readme.cell(r, 2, v).style = Style(wrap=True)
    readme.widths = {1: 26, 2: 100}

    multi = len(pf.tables) > 1
    for i, pt in enumerate(pf.tables, 1):
        prefix = f"T{i} " if multi else ""
        _frame_sheet(wb, _sheet_name(prefix + tr("Data"), used), _public_columns(pt.table.localized_df()))
        _frame_sheet(wb, _sheet_name(prefix + tr("Wide"), used), pt.table.to_wide())
    findings = [(pt.table.title, tr(SECTION_TITLES.get(f.section, f.section)), f.text) for pt in pf.tables for f in pt.analysis.facts]
    if findings:
        columns = [tr("table"), tr("section"), tr("finding")]
        _frame_sheet(wb, _sheet_name(tr("Findings"), used), pd.DataFrame(findings, columns=columns))
    checks = [(pt.table.title, c.name, status_text(c.status), c.detail) for pt in pf.tables for c in pt.analysis.checks]
    if checks:
        columns = [tr("table"), tr("check"), tr("status"), tr("detail")]
        _frame_sheet(wb, _sheet_name(tr("Checks"), used), pd.DataFrame(checks, columns=columns))
    return wb.save()
