"""A report in one HTML file: the findings, the charts, the checks and how the file was read.

It is self-contained: the charts are inline SVG, the stylesheet and the hover script are embedded and nothing is loaded from
the internet, so the file opens anywhere and prints cleanly. Every piece of text from the data is escaped.
"""

from __future__ import annotations

from datetime import datetime, UTC
from functools import cache
from html import escape
from importlib.resources import files

from .. import __version__
from ..analysis.facts import status_text
from ..analysis.fmt import fmt_number
from ..i18n import language, num, tn, tr
from ..pipeline import ProcessedFile, ProcessedTable
from ..semantics.labels import role_name
from ..viz.build import render_charts
from ..viz.theme import chart_css
from .reading import reading_summary

_ICONS = {"pass": "✔", "warn": "⚠", "fail": "✖", "info": "ℹ"}
PREVIEW_ROWS = 25


@cache
def _assets() -> tuple[str, str]:
    """(stylesheet, hover script) embedded in every report."""
    css = chart_css() + files("instatkit.export").joinpath("report.css").read_text(encoding="utf-8")
    return css, files("instatkit.viz").joinpath("chart.js").read_text(encoding="utf-8")


def _preview(pt: ProcessedTable) -> tuple[str, int]:
    wide = pt.table.to_wide()
    if "measure" in wide.columns and wide["measure"].nunique() == 1:
        wide = wide.drop(columns=["measure"])
    headings = {d.name: role_name(d.role).capitalize() for d in pt.profile.dims if not d.alias_of}
    if len(set(headings.values())) == len(headings):  # two columns of the same kind keep their own names
        wide = wide.rename(columns={"measure": tr("Measure"), "code": role_name("code").capitalize(), **headings})
    wide = wide.loc[:, ~wide.columns.duplicated()]
    html = wide.head(PREVIEW_ROWS).to_html(index=False, escape=True, border=0, classes="data", na_rep="",
                                          float_format=fmt_number, max_cols=40)
    return html, len(wide)


def _chips(pf: ProcessedFile) -> str:
    s, meta = pf.source, pf.meta
    chips = [f"<strong>{escape(tr('Demo data: the numbers are invented and are not INSTAT figures'))}</strong>" if s.kind == "demo"
             else escape(tr("Source: Institute of Statistics of Albania (INSTAT)"))]
    chips.append(f'<a href="{escape(s.url, quote=True)}">{escape(s.filename)}</a>' if s.url and s.url.startswith("http")
                 else escape(tr("File: {name}", name=s.filename)))
    chips.append(escape(tr("Retrieved {date}", date=s.retrieved_at[:10])))
    if s.last_modified:
        chips.append(escape(tr("Last modified on the server: {date}", date=s.last_modified)))
    if meta.get("published"):
        chips.append(escape(tr("Published {date}", date=meta["published"])))
    return '<div class="chips">' + "".join(f'<span class="chip">{c}</span>' for c in chips) + "</div>"


def _table_html(pt: ProcessedTable, idx: int, multi: bool) -> str:
    charts = render_charts(pt.table, pt.profile, pt.analysis)
    preview, n_series = _preview(pt)
    head = f'<h2 style="margin-top:28px">{escape(pt.table.title)}</h2><p class="sub">{escape(pt.briefing.subtitle)}</p>' if multi else ""
    tiles = "".join(
        f'<div class="tile"><div class="label">{escape(t.label)}</div><div class="value">{escape(t.value)}</div>'
        f'<div class="delta">{escape(t.delta)}</div></div>' for t in pt.analysis.tiles)
    sections = "".join(
        f'<div class="card"><h2>{escape(name)}</h2><ul class="findings">{"".join(f"<li>{escape(b)}</li>" for b in bullets)}</ul></div>'
        for name, bullets in pt.briefing.sections)
    chart_html = "".join(
        f'<div class="chart-box"><h3>{escape(c.title)}</h3><div class="cap">{escape(c.caption)}</div>{c.svg}</div>' for c in charts)
    checks = "".join(
        f'<li><span class="badge {c.status}"><span class="ic">{_ICONS[c.status]}</span>{escape(status_text(c.status))}</span>'
        f'<span><span class="name">{escape(c.name)}</span><br><span class="detail">{escape(c.detail)}</span></span></li>'
        for c in pt.analysis.checks)
    reading = "".join(f"<tr><th>{escape(str(k))}</th><td>{escape(str(v))}</td></tr>" for k, v in reading_summary(pt))
    notes = (f'<h3>{escape(tr("Footnotes in the file"))}</h3><ul class="findings">'
             + "".join(f"<li>{escape(n)}</li>" for n in pt.table.spec.notes) + "</ul>") if pt.table.spec.notes else ""
    tiles_html = f'<div class="tiles">{tiles}</div>' if tiles else ""
    charts_card = f'<div class="card"><h2>{escape(tr("Charts"))}</h2>{chart_html}</div>' if chart_html else ""
    preview_note = tr("The first {shown} of {total} series, one column per period. The full table is in the CSV, Excel and SQLite exports.",
                      shown=num(min(PREVIEW_ROWS, n_series)), total=num(n_series))
    return (
        f'<section id="t{idx}">{head}'
        f'<div class="card"><h2>{escape(tr("What this is"))}</h2><p class="lead">{escape(pt.briefing.what_is_this)}</p>'
        f'{tiles_html}</div>{sections}{charts_card}'
        f'<div class="card"><h2>{escape(tr("Checks"))}</h2><ul class="checks">{checks}</ul></div>'
        f'<div class="card"><h2>{escape(tr("How it was read"))}</h2><table class="kv">{reading}</table>{notes}</div>'
        f'<div class="card"><h2>{escape(tr("The cleaned data (preview)"))}</h2><p class="sub">{escape(preview_note)}</p>'
        f'<div class="scroll">{preview}</div></div></section>')


def build_report(pf: ProcessedFile) -> str:
    """The whole report as one HTML document."""
    css, js = _assets()
    first = pf.tables[0]
    multi = len(pf.tables) > 1
    title = pf.source.label or pf.source.filename if multi else first.table.title
    subtitle = (tn(len(pf.tables), "{n} table from {file}", "{n} tables from {file}", file=pf.source.filename) if multi
                else first.briefing.subtitle)
    toc = (f'<nav class="toc card"><strong>{escape(tr("Tables in this file:"))}</strong> ' + "".join(
        f'<a href="#t{i}">{escape(t.table.title)}</a>' for i, t in enumerate(pf.tables, 1)) + "</nav>") if multi else ""
    s = pf.source
    if s.kind == "demo":
        provenance = tr("Demo data made by INSTAT Explorer. The numbers are invented and only imitate the layout of INSTAT tables.")
    else:
        where = s.url if s.url else tr("file “{name}”", name=s.filename)
        provenance = tr("Source: Institute of Statistics of Albania (INSTAT), {where}, retrieved {date}.", where=where, date=s.retrieved_at[:10])
        if pf.meta.get("reuse"):
            provenance += " " + tr("Reuse notice in the file: “{notice}”", notice=pf.meta["reuse"])
    body = "".join(_table_html(pt, i, multi) for i, pt in enumerate(pf.tables, 1))
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    closing = tr("Made on {date} by INSTAT Explorer {version}, an independent tool with no connection to INSTAT. The findings are written "
                 "automatically by fixed rules from the table above, so check important figures against INSTAT's own publication "
                 "before you quote them.", date=generated, version=__version__)
    return (
        f'<!doctype html><html lang="{language()}"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title><style>{css}</style></head><body><main><header><h1>{escape(title)}</h1>"
        f'<p class="sub">{escape(subtitle)}</p>{_chips(pf)}{toc}</header>{body}'
        f"<footer><p>{escape(provenance)}</p><p>{escape(closing)}</p></footer></main><script>{js}</script></body></html>")
