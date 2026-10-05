"""Turns the chart suggestions of the analysis into SVG charts (used by the report and by the Insights tab of the app)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..analysis.engine import Analysis, category_matrix, snapshot_by_dim
from ..analysis.fmt import human_period
from ..excel.tidy import TidyTable
from ..i18n import tr
from ..semantics.glossary import display
from ..semantics.interpret import DatasetProfile
from ..semantics.units import unit_text
from . import charts as C


@dataclass
class RenderedChart:
    kind: str
    title: str
    caption: str
    svg: str


def series_frame(table: TidyTable, analysis: Analysis, series_ids: list[int]) -> pd.DataFrame:
    """The observations of the chosen series, with a display ``label`` and the unit of each."""
    df = table.df
    sel = df[df["series_id"].isin(series_ids) & (df["period"] != "")].copy()
    sel["label"] = sel["series_id"].map(analysis.labels)
    sel["unit_code"] = sel["measure"].map({m.name: m.unit_code for m in analysis.profile.measures})
    sel["unit_label"] = sel["measure"].map({m.name: m.unit for m in analysis.profile.measures})
    return sel


def line_svg(table: TidyTable, analysis: Analysis, series_ids: list[int], title: str = "") -> str:
    """Lines on one axis; series with different units are stacked as small panels instead."""
    frame = series_frame(table, analysis, series_ids)
    groups = []
    for unit_code, g in frame.groupby("unit_code", sort=False):
        label = unit_text(g["unit_label"].iloc[0] or unit_code) or tr("value")
        names = ", ".join(dict.fromkeys(g["measure"].map(lambda m: m[:40])))
        groups.append((f"{names} ({label})" if g["measure"].nunique() == 1 else label, unit_code or "", g))
    colors = C.ColorMap(list(dict.fromkeys(frame["label"])))
    if len(groups) == 1:
        _t, unit_code, g = groups[0]
        return C.line_chart(g, unit_code=unit_code, unit_label=unit_text(g["unit_label"].iloc[0] or ""), colors=colors, title=title)
    return C.small_multiples(groups[:4], colors=colors, title=title)


def render_charts(table: TidyTable, profile: DatasetProfile, analysis: Analysis, *, limit: int = 6) -> list[RenderedChart]:
    with table.wording():
        return _render_charts(table, profile, analysis, limit)


def _render_charts(table: TidyTable, profile: DatasetProfile, analysis: Analysis, limit: int) -> list[RenderedChart]:
    out: list[RenderedChart] = []
    df = table.df
    unit_code = profile.measures[0].unit_code if profile.measures else ""
    unit_label = unit_text(profile.measures[0].unit) if profile.measures else ""
    for spec in analysis.charts:
        try:
            chart = _render(spec, table, profile, analysis, df, unit_code, unit_label)
        except Exception as exc:  # one broken chart must not hide the others
            analysis.warnings.append(tr("The chart '{title}' could not be drawn ({error}).", title=spec.title,
                                        error=f"{type(exc).__name__}: {exc}"))
            chart = None
        if chart:
            out.append(chart)
    contrib = analysis.extras.get("cpi_contributions")
    if contrib is not None and len(contrib):
        title = tr("What each group added to annual inflation (percentage points, approximate)")
        caption = tr("Weighted change of each main group over the twelve months to {period}. Bars to the right pushed inflation up.",
                     period=human_period(profile.last_period))
        out.append(RenderedChart("contributions", title, caption, C.signed_bars(contrib, unit_label=tr("percentage points"), title=title)))
    gap = analysis.extras.get("pay_gap")
    if gap is not None and len(gap):
        title = tr("Gender pay gap by category (% below men's pay)")
        out.append(RenderedChart("gap", title, tr("Positive values mean women earn less than men."),
                                 C.signed_bars(gap, unit_label=tr("% of men's pay"), title=title)))
    return out[:limit]


def _render(spec, table, profile, analysis, df, unit_code, unit_label) -> RenderedChart | None:
    if spec.kind == "lines" and spec.series_ids:
        frequency = tr(profile.freq_name)
        caption = (tr("Values over time ({frequency}). Dotted lines are provisional figures.", frequency=frequency)
                   if profile.provisional_periods else tr("Values over time ({frequency}).", frequency=frequency))
        return RenderedChart("lines", spec.title, caption, line_svg(table, analysis, spec.series_ids, spec.title))
    if spec.kind == "seasonal":
        g = df[(df["series_id"] == spec.series_ids[0]) & (df["period"] != "")]
        return RenderedChart("seasonal", spec.title, tr("Each line is one year. The latest year is highlighted."),
                             C.seasonal_chart(g, freq=profile.freq or "M", unit_code=unit_code, unit_label=unit_label, title=spec.title))
    if spec.kind == "bars":
        snap, period = snapshot_by_dim(df, profile, spec.params["dim"])
        if len(snap.dropna()) < 2:
            return None
        snap = snap.rename(index=lambda name: display(str(name)))
        return RenderedChart("bars", spec.title, tr("Values for {period}, with every other breakdown set to its total.", period=human_period(period)),
                             C.bars_latest(snap, unit_code=unit_code, unit_label=unit_label, title=spec.title))
    if spec.kind == "heatmap":
        m = category_matrix(df, profile, spec.params["dim"])
        if m.shape[0] < 3 or m.shape[1] < 3:
            return None
        m = m.rename(index=lambda name: display(str(name)))
        signed = bool(profile.measures and profile.measures[0].kind == "growth") or bool((m.min().min() < 0) and (m.max().max() > 0))
        caption = tr("Blue is above zero, red is below zero.") if signed else tr("A darker colour means a larger value.")
        return RenderedChart("heatmap", spec.title, caption, C.heatmap(m, signed=signed, unit_code=unit_code, title=spec.title))
    if spec.kind == "pyramid":
        return _pyramid(table, profile, unit_label)
    return None


def _pyramid(table, profile, unit_label) -> RenderedChart | None:
    from ..analysis.recipes import _hold_others

    age, sex = profile.dim("age_group"), profile.dim("sex")
    df = table.df
    male = next((v for v in df[sex.name].unique() if v in ("Males", "Male", "Men")), None)
    female = next((v for v in df[sex.name].unique() if v in ("Females", "Female", "Women")), None)
    if not male or not female or not profile.last_period:
        return None
    sel = _hold_others(df[df["period"] == profile.last_period], profile, {age.name, sex.name})
    sel = sel[~sel[age.name].isin(age.total_values)]
    if sel.empty:
        return None
    sel = sel.assign(**{age.name: sel[age.name].map(lambda a: display(str(a)))})
    return RenderedChart("pyramid", tr("Population pyramid"), tr("Men and women by age group, {period}.", period=human_period(profile.last_period)),
                         C.pyramid(sel, age_col=age.name, sex_col=sex.name, male=male, female=female, unit_label=unit_label))
