"""Tidy CSV, wide CSV and a portable SQLite file for the processed tables."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace

import pandas as pd

from .. import store
from ..pipeline import ProcessedFile, ProcessedTable


def _public_columns(df: pd.DataFrame) -> pd.DataFrame:
    """The tidy frame as users should see it: dates as ISO strings, no empty helper columns."""
    out = df.copy()
    for col in ("period_start", "period_end"):
        if col in out.columns:
            out[col] = out[col].dt.strftime("%Y-%m-%d")
    drop = [c for c in ("is_total",) if c in out.columns and not out[c].any()]
    return out.drop(columns=drop)


def tidy_csv(pt: ProcessedTable) -> bytes:
    """UTF-8 with a BOM so Excel on Windows shows ë and ç correctly."""
    return _public_columns(pt.table.localized_df()).to_csv(index=False).encode("utf-8-sig")


def wide_csv(pt: ProcessedTable) -> bytes:
    return pt.table.to_wide().to_csv(index=False).encode("utf-8-sig")


def sqlite_bytes(pf: ProcessedFile) -> bytes:
    """A self-contained SQLite database (datasets, series, observations, findings, checks) for these tables."""
    src = {"url": pf.source.url, "sha256": pf.source.sha256, "filename": pf.source.filename}
    with closing(sqlite3.connect(":memory:")) as conn:
        for pt in pf.tables:
            store.save_dataset(conn, pt.dataset_id, replace(pt.table, df=pt.table.localized_df()), pt.profile, pt.analysis, src)
        conn.commit()
        return bytes(conn.serialize())
