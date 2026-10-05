"""SQLite: the download manifest of the workspace, and the dataset tables of the SQLite export."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from . import config

DOWNLOADS = """
CREATE TABLE IF NOT EXISTS downloads(
  url TEXT PRIMARY KEY, sha256 TEXT, path TEXT, size INTEGER, etag TEXT, last_modified TEXT,
  content_type TEXT, fetched_at TEXT, status INTEGER, filename TEXT);
"""

DATASETS = """
CREATE TABLE IF NOT EXISTS datasets(
  dataset_id TEXT PRIMARY KEY, source_sha256 TEXT, source_url TEXT, filename TEXT, sheet TEXT, title TEXT,
  profile_json TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS series(
  dataset_id TEXT, series_id INTEGER, measure TEXT, dims_json TEXT, code TEXT, PRIMARY KEY(dataset_id, series_id));
CREATE TABLE IF NOT EXISTS observations(
  dataset_id TEXT, series_id INTEGER, period TEXT, period_start TEXT, period_end TEXT, freq TEXT, value REAL,
  flag TEXT, unit TEXT, src_ref TEXT);
CREATE INDEX IF NOT EXISTS obs_idx ON observations(dataset_id, series_id, period);
CREATE TABLE IF NOT EXISTS findings(
  dataset_id TEXT, section TEXT, kind TEXT, subject TEXT, text TEXT, importance REAL, data_json TEXT);
CREATE TABLE IF NOT EXISTS checks(dataset_id TEXT, name TEXT, status TEXT, detail TEXT);
"""


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@contextmanager
def connect(path: Path | str | None = None):
    path = Path(path or config.DB_PATH)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(DOWNLOADS)
        yield conn
        conn.commit()
    finally:
        conn.close()


def record_download(conn: sqlite3.Connection, **row) -> None:
    cols = ["url", "sha256", "path", "size", "etag", "last_modified", "content_type", "fetched_at", "status", "filename"]
    conn.execute(f"INSERT OR REPLACE INTO downloads({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                 [row.get(c) for c in cols])


def get_download(conn: sqlite3.Connection, url: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM downloads WHERE url=?", (url,)).fetchone()


def save_dataset(conn: sqlite3.Connection, dataset_id: str, table, profile, analysis, source: dict) -> None:
    """Replace everything stored for ``dataset_id`` with the current run."""
    conn.executescript(DATASETS)
    for t in ("datasets", "series", "observations", "findings", "checks"):
        conn.execute(f"DELETE FROM {t} WHERE dataset_id=?", (dataset_id,))
    conn.execute("INSERT INTO datasets VALUES(?,?,?,?,?,?,?,?)", (
        dataset_id, source.get("sha256"), source.get("url"), source.get("filename"), table.sheet, table.title,
        json.dumps(asdict(profile), default=str, ensure_ascii=False), now_iso()))
    df = table.df
    dims = table.dim_columns
    first = df.drop_duplicates("series_id")
    conn.executemany("INSERT INTO series VALUES(?,?,?,?,?)", [
        (dataset_id, int(r.series_id), r.measure, json.dumps({d: getattr(r, d) for d in dims}, ensure_ascii=False),
         getattr(r, "code", "") if "code" in df.columns else "") for r in first.itertuples()])
    obs = df[["series_id", "period", "period_start", "period_end", "freq", "value", "flag", "unit", "src_ref"]].copy()
    obs["period_start"] = obs["period_start"].dt.strftime("%Y-%m-%d").fillna("")
    obs["period_end"] = obs["period_end"].dt.strftime("%Y-%m-%d").fillna("")
    obs["value"] = obs["value"].where(obs["value"].notna(), None)
    conn.executemany("INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?)",
                     [(dataset_id, int(r[0]), *r[1:]) for r in obs.itertuples(index=False, name=None)])
    conn.executemany("INSERT INTO findings VALUES(?,?,?,?,?,?,?)", [
        (dataset_id, f.section, f.kind, f.subject, f.text, f.importance, json.dumps(f.data, default=str)) for f in analysis.facts])
    conn.executemany("INSERT INTO checks VALUES(?,?,?,?)", [(dataset_id, c.name, c.status, c.detail) for c in analysis.checks])


