"""Everything for one file in a single ZIP: report, workbook, SQLite, tidy/wide CSVs and plain-text briefings."""

from __future__ import annotations

import io
import zipfile

from ..pipeline import ProcessedFile
from .excel_export import excel_bytes
from .html_report import build_report
from .tables import sqlite_bytes, tidy_csv, wide_csv


def bundle_bytes(pf: ProcessedFile) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("report.html", build_report(pf))
        z.writestr("workbook.xlsx", excel_bytes(pf))
        z.writestr("data.sqlite", sqlite_bytes(pf))
        for i, pt in enumerate(pf.tables, 1):
            z.writestr(f"table{i}-tidy.csv", tidy_csv(pt))
            z.writestr(f"table{i}-wide.csv", wide_csv(pt))
            z.writestr(f"table{i}-briefing.md", pt.briefing.markdown())
    return buf.getvalue()
