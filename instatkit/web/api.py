"""What the app does behind the HTTP layer: a small in-memory workspace, and the JSON or bytes each endpoint returns.

Nothing here knows about HTTP, so every function can be called (and tested) directly. A function raises
:class:`ApiError` for anything the user should be told about, and the server turns that into a JSON error reply.
"""

from __future__ import annotations

import platform
import re
import sys
import threading
import time
from collections import OrderedDict

import numpy as np
import pandas as pd

from .. import __version__, config
from ..analysis.facts import kind_text, status_text
from ..analysis.fmt import human_period
from ..i18n import LANGUAGES, N_, catalog, language, tr
from ..excel.grid import col_letter
from ..excel.layout import Overrides
from ..export.bundle import bundle_bytes
from ..export.excel_export import excel_bytes
from ..export.html_report import build_report
from ..export.reading import reading_summary
from ..export.tables import sqlite_bytes, tidy_csv, wide_csv
from ..pipeline import ProcessedFile, ProcessedTable, SourceInfo, process_bytes, process_workbook, slug, source_from_download
from ..semantics.glossary import display
from ..semantics.labels import role_name
from ..semantics.units import unit_text
from ..sources.fetch import FetchError, Fetcher, host_of, is_instat_host
from ..sources.page_links import PageListing, parse_page
from ..sources.resolve import resolve
from ..viz import charts as C
from ..viz.build import render_charts
from .common import ApiError, dumps

MAX_FILES = 12  # open files kept in memory; the oldest is dropped first
PAGE_SIZE = 100
EXPLORE_ROWS = 1000
LISTING_TTL = 3600.0
LAYOUTS = {"auto": N_("Find it automatically"), "periods_in_columns": N_("The periods run across the columns"),
           "periods_in_rows": N_("The periods run down the rows"), "month_by_year": N_("A grid of months or quarters by year"),
           "cross_section": N_("No time axis (categories only)")}
_ROLE_STYLE = ("title", "header", "skip", "note")
_MIME = {"report": "text/html; charset=utf-8", "tidy": "text/csv; charset=utf-8", "wide": "text/csv; charset=utf-8",
         "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "sqlite": "application/vnd.sqlite3",
         "zip": "application/zip", "diagnostic": "application/json; charset=utf-8"}
_EXT = {"report": "-report.html", "tidy": "-tidy.csv", "wide": "-wide.csv", "xlsx": ".xlsx", "sqlite": ".sqlite",
        "zip": "-bundle.zip", "diagnostic": "-diagnostic.json"}


def _cell(v: object) -> object:
    """A DataFrame cell as JSON: NaN/NaT/NA -> null, timestamps as ISO dates, numpy scalars as Python ones."""
    if v is None or v is pd.NA or v is pd.NaT or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    return v.item() if isinstance(v, np.generic) else v


class Workspace:
    """Everything the open browser tab can see: the processed files, cached page listings and built exports."""

    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self.files: OrderedDict[str, ProcessedFile] = OrderedDict()
        self._fetcher = fetcher
        self._listings: dict[str, tuple[float, PageListing]] = {}
        self._wide: dict[tuple[str, int], pd.DataFrame] = {}
        self._lock = threading.RLock()  # state
        self.work = threading.Lock()  # one heavy job (read, analyse, export) at a time: kind to small computers

    @property
    def fetcher(self) -> Fetcher:
        if self._fetcher is None:
            self._fetcher = Fetcher()
        return self._fetcher

    # files
    def add(self, pf: ProcessedFile) -> str:
        key = (pf.source.sha256 or slug(pf.source.filename))[:10]
        with self._lock:
            self.files.pop(key, None)
            self.files[key] = pf
            while len(self.files) > MAX_FILES:
                self.files.popitem(last=False)
            self._wide = {k: v for k, v in self._wide.items() if k[0] in self.files}
        return key

    def localised(self, key: str) -> ProcessedFile | None:
        """The open file ``key`` with its texts in the language that is switched on. A file made in the other language is
        read again from the workbook it kept (a moment's work), so every sentence comes out in one language."""
        with self._lock:
            pf = self.files.get(key)
        if pf is None or pf.lang == language() or pf.workbook is None:
            return pf
        with self.work:
            new = process_workbook(pf.workbook, pf.source, label=pf.source.label, overrides=pf.overrides)
        with self._lock:
            if key in self.files:
                self.files[key] = new
            self._wide = {k: v for k, v in self._wide.items() if k[0] != key}
        return new

    def get(self, key: str, i: int = 0) -> tuple[ProcessedFile, ProcessedTable]:
        pf = self.localised(key)
        if pf is None:
            raise ApiError(tr("That file is no longer open. Load it again."), 404)
        if not pf.ok or not 0 <= i < len(pf.tables):
            raise ApiError(tr("That table does not exist."), 404)
        return pf, pf.tables[i]

    def wide(self, key: str, i: int, pt: ProcessedTable) -> pd.DataFrame:
        with self._lock:
            if (key, i) not in self._wide:
                self._wide[(key, i)] = pt.table.to_wide()
            return self._wide[(key, i)]


def _shown_label(pf: ProcessedFile) -> str:
    """What the file list calls a file: a demo's name is translated, the label from an INSTAT page is shown as it is."""
    label = pf.source.label or pf.source.filename
    return tr(label) if pf.source.kind == "demo" else label


def state(ws: Workspace) -> dict:
    from ..demo import DEMOS

    with ws._lock:
        keys = list(ws.files)
    files = [(k, pf) for k in keys if (pf := ws.localised(k)) is not None]
    return {"version": __version__, "language": language(), "demos": [[k, tr(v[0])] for k, v in DEMOS.items()], "files": [{
        "key": k, "label": _shown_label(pf), "filename": pf.source.filename, "kind": pf.source.kind,
        "ok": pf.ok, "errors": pf.errors,
        "tables": [{"i": i, "title": t.table.title, "sheet": t.table.sheet, "confidence": t.profile.confidence} for i, t in enumerate(pf.tables)],
    } for k, pf in files]}


def about() -> dict:
    return {"version": __version__, "python": sys.version.split()[0], "platform": platform.platform(), "data_dir": str(config.DATA_DIR)}


def translations(code: str) -> dict:
    """The sentences of the app for ``code`` (English needs none), for the page to use."""
    return {"language": code if code in LANGUAGES else "en", "catalog": catalog(code)}


def resolve_query(q: str) -> dict:
    r = resolve(q)
    return {"kind": r.kind, "message": r.message, "url": r.url, "external": r.external,
            "hits": [{"url": h.topic.url, "name": h.topic.title, "theme": h.topic.theme_name} for h in r.hits],
            "topics": [{"url": t.url, "name": t.title} for t in r.topics],
            "topic": {"url": r.topic.url, "name": r.topic.title} if r.topic else None}


def listing(ws: Workspace, url: str) -> dict:
    now = time.monotonic()
    with ws._lock:
        hit = ws._listings.get(url)
    if hit and now - hit[0] < LISTING_TTL:
        page = hit[1]
    else:
        try:
            page = parse_page(ws.fetcher.get_html(url), url)
        except FetchError as exc:
            raise ApiError(tr("The page could not be opened: {error}", error=exc), 502) from exc
        with ws._lock:
            ws._listings[url] = (now, page)
    return {"title": page.title, "url": page.url, "pdfs": page.n_pdfs,
            "files": [{"url": f.url, "label": f.label, "ext": f.ext, "filename": f.filename, "section": f.section or tr("Other"),
                       "legacy": f.is_legacy_xls} for f in page.files]}


def _process(ws: Workspace, data: bytes, filename: str, source: SourceInfo, label: str | None = None) -> str:
    with ws.work:
        pf = process_bytes(data, filename, source=source, label=label)
    return ws.add(pf)


def load_url(ws: Workspace, url: str, label: str | None = None, allow_external: bool = False) -> dict:
    if not allow_external and not is_instat_host(host_of(url)):
        raise ApiError(tr("This file is not on instat.gov.al. Confirm that you trust the source before it is downloaded."), 400)
    try:
        d = ws.fetcher.download(url)
    except FetchError as exc:
        raise ApiError(str(exc), 502) from exc
    key = _process(ws, d.data, d.filename, source_from_download(d, label=label), label)
    return {"key": key}


def load_upload(ws: Workspace, data: bytes, filename: str) -> dict:
    name = re.sub(r"[^\w.\- ]+", "_", filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])[:120] or "upload.xlsx"
    return {"key": _process(ws, data, name, SourceInfo(name, "", len(data), "upload"))}


def load_demo(ws: Workspace, name: str) -> dict:
    from ..demo import DEMOS

    if name not in DEMOS:
        raise ApiError(tr("Unknown demo."), 404)
    label, fname, build = DEMOS[name]
    data = build()
    return {"key": _process(ws, data, fname, SourceInfo(fname, "", len(data), "demo"), label)}


def close_file(ws: Workspace, key: str | None) -> dict:
    with ws._lock:
        if key is None:
            ws.files.clear()
        else:
            ws.files.pop(key, None)
    return state(ws)


def summary(pf: ProcessedFile, pt: ProcessedTable) -> dict:
    s, a = pf.source, pt.analysis
    charts = render_charts(pt.table, pt.profile, a)
    return {
        "title": pt.table.title, "subtitle": pt.briefing.subtitle, "confidence": pt.profile.confidence,
        "source": {"filename": s.filename, "url": s.url if (s.url or "").startswith("http") else None, "retrieved": s.retrieved_at[:10],
                   "last_modified": s.last_modified, "published": pf.meta.get("published"), "demo": s.kind == "demo"},
        "what": pt.briefing.what_is_this,
        "tiles": [{"label": t.label, "value": t.value, "delta": t.delta} for t in a.tiles],
        "sections": [[name, bullets] for name, bullets in pt.briefing.sections],
        "evidence": [{"kind": kind_text(f.kind), "text": f.text, "data": f.data} for f in a.facts],
        "charts": [{"title": c.title, "caption": c.caption, "svg": c.svg} for c in charts],
        "warnings": a.warnings, "parts": [p.sheet for p in pt.table.parts],
    }


def _label_frame(pt: ProcessedTable, sub: pd.DataFrame, dims: list[str]) -> pd.DataFrame:
    """A display ``label`` per row: the chosen non-total category values, plus the measure when there are several."""
    totals = {d.name: set(d.total_values) | {""} for d in pt.profile.dims}
    multi = sub["measure"].nunique() > 1

    def lab(row) -> str:
        parts = [display(str(row[d])) for d in dims if row[d] not in totals.get(d, {""})]
        base = pt.table.measure_label(row["measure"]) if (multi or not parts) else ""
        return f"{base} ({', '.join(parts)})" if (parts and base) else (", ".join(parts) or base or tr("Total"))

    out = sub.copy()
    out["label"] = out.apply(lab, axis=1)
    return out


def explore(pt: ProcessedTable, q: dict) -> dict:
    with pt.table.wording():
        return _explore(pt, q)


def _explore(pt: ProcessedTable, q: dict) -> dict:
    df, prof = pt.table.df, pt.profile
    if df.empty:
        raise ApiError(tr("There is no data to explore."))
    measures = [m.name for m in prof.measures]
    measure = q.get("measure") if q.get("measure") in measures else measures[0]
    mi = prof.measure(measure)
    sub = df[df["measure"] == measure]
    chosen: dict[str, list[str]] = q.get("filters") or {}
    controls, names, compare_offered = [], [], False
    for d in (d for d in prof.dims if not d.alias_of):
        opts = [o for o in dict.fromkeys(sub[d.name]) if o != ""] or [""]
        totals = [o for o in opts if o in d.total_values]
        default = totals or opts[:4]
        if not mi.additive and not compare_offered and d.role != "sex" and len(opts) - len(totals) >= 3:
            default = totals + [o for o in opts if o not in totals][:3]  # a total plus a few categories to compare with
            compare_offered = True
        sel = [v for v in chosen.get(d.name, default) if v in opts]
        controls.append({"name": d.name, "label": role_name(d.role).capitalize(), "options": [[o, display(o)] for o in opts], "selected": sel})
        sub = sub[sub[d.name].isin(sel)]
        names.append(d.name)
    periods = [p for p in dict.fromkeys(sub.sort_values("period_start")["period"]) if p]
    lo, hi = (q.get("lo"), q.get("hi")) if q.get("lo") in periods and q.get("hi") in periods else (None, None)
    if len(periods) > 1:
        lo, hi = lo or periods[0], hi or periods[-1]
        if periods.index(lo) > periods.index(hi):
            lo, hi = hi, lo
        sub = sub[sub["period"].isin(periods[periods.index(lo): periods.index(hi) + 1])]
    out = {"measures": [[m, pt.table.measure_label(m)] for m in measures], "measure": measure, "dims": controls,
           "periods": [[p, human_period(p)] for p in periods], "lo": lo, "hi": hi}
    if sub.empty:
        return out | {"kinds": [], "kind": "table", "svg": "", "caption": tr("Nothing matches these filters."), "columns": [], "rows": [],
                      "total": 0}
    kinds = (["lines"] if sub["period"].nunique() > 1 else []) + ["bars", "table"]
    kind = q.get("kind") if q.get("kind") in kinds else kinds[0]
    frame = _label_frame(pt, sub, names)
    svg, caption = "", ""
    if kind == "lines":
        if frame["label"].nunique() > 24:
            caption = tr("There are too many series to draw clearly. Narrow the filters (the first 24 are shown).")
            frame = frame[frame["label"].isin(list(dict.fromkeys(frame["label"]))[:24])]
        svg = C.line_chart(frame, unit_code=mi.unit_code, unit_label=unit_text(mi.unit), title=mi.display)
    elif kind == "bars":
        last = frame.sort_values("period_start")["period"].iloc[-1]
        snap = frame[frame["period"] == last].groupby("label")["value"].first()
        caption = tr("Values for {period}", period=human_period(last)) if human_period(last) else tr("Values for this table")
        svg = C.bars_latest(snap, unit_code=mi.unit_code, unit_label=unit_text(mi.unit), title=mi.display)
    show = frame.drop(columns=["period_start", "period_end", "series_id"], errors="ignore")
    if language() == "sq":
        show = show.copy()
        for col in names:
            if col in show.columns:
                show[col] = show[col].map(display)
        if "measure" in show.columns:
            show["measure"] = show["measure"].map(pt.table.measure_label)
    if q.get("csv"):
        return {"csv": show.to_csv(index=False)}
    return out | {"kinds": kinds, "kind": kind, "svg": svg, "caption": caption, "columns": list(show.columns), "total": len(show),
                  "rows": [[_cell(v) for v in r] for r in show.head(EXPLORE_ROWS).itertuples(index=False, name=None)]}


def data_page(ws: Workspace, key: str, i: int, pt: ProcessedTable, q: dict) -> dict:
    df = pt.table.localized_df().drop(columns=["period_end"], errors="ignore") if q.get("layout") != "wide" else ws.wide(key, i, pt)
    text = (q.get("q") or "").strip()
    if text:
        mask = pd.Series(False, index=df.index)
        for c in df.select_dtypes(exclude="number").columns:
            mask |= df[c].astype(str).str.contains(text, case=False, regex=False, na=False)
        df = df[mask]
    sort = q.get("sort")
    if sort in df.columns:
        df = df.sort_values(sort, ascending=not q.get("desc"), kind="stable")
    page = max(0, int(q.get("page") or 0))
    part = df.iloc[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    return {"columns": [str(c) for c in df.columns], "total": len(df), "page": page, "size": PAGE_SIZE,
            "rows": [[_cell(v) for v in r] for r in part.itertuples(index=False, name=None)]}


def _grid_region(pf: ProcessedFile, tbl, max_rows: int = 45, max_cols: int = 18) -> dict | None:
    """The original sheet region with each cell tagged by the role the reader gave it."""
    spec = tbl.spec
    grid = next((g for g in (pf.workbook.sheets if pf.workbook else []) if g.name == tbl.sheet), None)
    if grid is None:
        return None
    row_role = dict.fromkeys(spec.title_rows, "title") | dict.fromkeys(spec.header_rows, "header") | \
               dict.fromkeys(spec.annotation_rows, "skip") | dict.fromkeys(spec.note_rows, "note")
    col_role = {c.col: ("label" if c.kind in ("label", "code", "period") else "attr" if c.kind in ("attr", "attr_text") else "value") for c in spec.columns}
    data = set(spec.data_rows)
    seen = spec.title_rows + spec.header_rows + spec.data_rows[:1]
    first = max(0, min(seen)) if seen else 0
    last, n_cols = min(grid.n_rows, first + max_rows), min(grid.n_cols, max_cols)
    rows = []
    for r in range(first, last):
        cells = []
        for c in range(n_cols):
            v = grid.cells[r][c]
            txt = "" if v is None else (f"{v:,.4g}" if isinstance(v, float) else str(v))
            cells.append([txt[:60], row_role.get(r) or (col_role.get(c, "") if r in data else "")])
        rows.append({"n": r + grid.origin[0] + 1, "cells": cells})
    return {"cols": [col_letter(c + grid.origin[1]) for c in range(n_cols)], "rows": rows}


def _piece(pt: ProcessedTable, part: int):
    """The sheet-level table behind ``pt``: itself, or one of the repeated tables a stacked table was built from."""
    return pt.table.parts[part] if pt.table.parts and 0 <= part < len(pt.table.parts) else pt.table


def read_info(pf: ProcessedFile, pt: ProcessedTable, part: int = 0) -> dict:
    tbl = _piece(pt, part)
    spec = tbl.spec
    r0, _c0 = spec.origin
    cur = pf.overrides.get(tbl.sheet)
    summary_rows = reading_summary(pt)
    return {"rows": summary_rows, "grid": _grid_region(pf, tbl), "notes": spec.notes, "sheet": tbl.sheet,
            "parts": [p.sheet for p in pt.table.parts], "part": part if pt.table.parts else None,
            "skipped": [[n, w] for n, w in (pf.result.skipped if pf.result else [])],
            "override": {"header_first": spec.header_rows[0] + r0 + 1 if spec.header_rows else 0,
                         "header_last": spec.header_rows[-1] + r0 + 1 if spec.header_rows else 0,
                         "data_first": spec.data_rows[0] + r0 + 1, "data_last": spec.data_rows[-1] + r0 + 1,
                         "n_labels": len(spec.label_cols), "layout": spec.orientation if spec.orientation in LAYOUTS else "auto",
                         "active": cur is not None, "layouts": {k: tr(v) for k, v in LAYOUTS.items()}}}


def reread(ws: Workspace, key: str, i: int, q: dict) -> dict:
    pf, pt = ws.get(key, i)
    tbl = _piece(pt, int(q.get("part") or 0))
    sheet, r0 = tbl.sheet, tbl.spec.origin[0]
    overrides = dict(pf.overrides)
    if q.get("reset"):
        overrides.pop(sheet, None)
    else:
        hf, hl = int(q.get("header_first") or 0), int(q.get("header_last") or 0)
        overrides[sheet] = Overrides(
            header_rows=list(range(hf - 1 - r0, hl - r0)) if hf and hl and hl >= hf else None,
            first_data_row=int(q["data_first"]) - 1 - r0, last_data_row=int(q["data_last"]) - 1 - r0,
            n_label_cols=int(q["n_labels"]), orientation=None if q.get("layout") in (None, "auto") else q["layout"])
    with ws.work:
        new = process_workbook(pf.workbook, pf.source, label=pf.source.label, overrides=overrides)
    ws.add(new)
    return state(ws)


def quality(pt: ProcessedTable) -> dict:
    checks = [{"status": c.status, "word": status_text(c.status), "name": c.name, "detail": c.detail,
               "examples": [str(e) for e in c.examples or []]} for c in pt.analysis.checks]
    df = pt.table.df
    svg = ""
    if df["value"].isna().any() and df["period"].ne("").any():
        m = df.assign(missing=df["value"].isna()).pivot_table(index="series_id", columns="period", values="missing", aggfunc="max")
        m = m.loc[m.any(axis=1)].head(60)
        if not m.empty:
            order = df.drop_duplicates("period").sort_values("period_start")["period"]
            m = m[[p for p in order if p in m.columns]]
            svg = C.missing_map(m.astype(bool), [pt.analysis.labels.get(i, str(i)) for i in m.index])
    return {"checks": checks, "missing_svg": svg}


def diagnostic(pf: ProcessedFile, pt: ProcessedTable) -> dict:
    """What a maintainer needs to reproduce a misreading: the sheet's first rows, the decisions made, the versions."""
    tbl = pt.table
    spec = tbl.spec
    grid = next((g for g in (pf.workbook.sheets if pf.workbook else []) if g.name == tbl.sheet), None)
    preview = [[("" if v is None else str(v)[:80]) for v in row[:30]] for row in (grid.cells[:80] if grid else [])]
    return {"app": __version__, "python": sys.version.split()[0], "platform": platform.platform(),
            "file": {"name": pf.source.filename, "sha256": pf.source.sha256, "format": pf.workbook.format if pf.workbook else None,
                     "url": pf.source.url},
            "sheet": tbl.sheet, "origin": spec.origin, "preview_note": "first 80 rows x 30 columns of the sheet, as read",
            "preview": preview,
            "spec": {"orientation": spec.orientation, "title_rows": spec.title_rows, "header_rows": spec.header_rows,
                     "data_rows": [spec.data_rows[0], spec.data_rows[-1]] if spec.data_rows else [], "confidence": spec.confidence,
                     "reasons": spec.reasons, "warnings": spec.warnings, "scope": spec.scope,
                     "columns": [[c.col, c.kind, c.name] for c in spec.columns]},
            "profile": {"dims": [[d.name, d.role, d.header, d.n_values] for d in pt.profile.dims], "unit": pt.profile.unit,
                        "freq": pt.profile.freq, "n_obs": pt.profile.n_obs},
            "checks": [[c.key, c.status] for c in pt.analysis.checks if c.status in ("warn", "fail")], "errors": pf.errors}


def export(ws: Workspace, key: str, i: int, kind: str) -> tuple[str, str, bytes]:
    """(filename, MIME type, bytes) for one export of a file or table."""
    if kind not in _MIME:
        raise ApiError(tr("Unknown export."), 404)
    pf, pt = ws.get(key, i)
    with ws.work:
        data = {"report": lambda: build_report(pf).encode("utf-8"), "tidy": lambda: tidy_csv(pt), "wide": lambda: wide_csv(pt),
                "xlsx": lambda: excel_bytes(pf), "sqlite": lambda: sqlite_bytes(pf), "zip": lambda: bundle_bytes(pf),
                "diagnostic": lambda: dumps(diagnostic(pf, pt))}[kind]()
    return slug(pf.source.label or pf.source.filename.rsplit(".", 1)[0]) + _EXT[kind], _MIME[kind], data
