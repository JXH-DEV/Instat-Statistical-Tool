"""The seasonal chart and the map of missing values: what is drawn, how many marks, what the tooltips say.

The other charts are exercised by every demo; these two are drawn only when the data call for them (a strong yearly pattern, missing
cells), so they get their own tables.
"""

from __future__ import annotations

import html
import json
import re

import pandas as pd
import pytest

from instatkit.export.xlsx_writer import Workbook as Writer
from instatkit.viz import charts as C
from instatkit.viz.build import render_charts
from instatkit.web import api

from .conftest import process_demo, process_workbook_bytes

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
SEASON = [10, 12, 20, 35, 60, 90, 100, 95, 55, 30, 15, 11]


def frame(values_by_year: dict[int, list[float | None]], freq: str) -> pd.DataFrame:
    step = 1 if freq == "M" else 3
    rows = []
    for year, values in values_by_year.items():
        for i, v in enumerate(values):
            rows.append({"period_start": pd.Timestamp(year, 1 + i * step, 1), "value": v})
    return pd.DataFrame(rows)


def count(svg: str, cls: str) -> int:
    return len(re.findall(rf'class="{re.escape(cls)}"', svg))


def aria(svg: str) -> str:
    return re.search(r'aria-label="([^"]*)"', svg).group(1)


def tips(svg: str) -> list:
    """The tooltip data the page script reads from the chart."""
    return json.loads(html.unescape(re.search(r"data-tips='([^']*)'", svg).group(1)))


# --- seasonal chart ---
def test_monthly_years_are_drawn_as_one_line_each_with_the_latest_year_marked():
    df = frame({2021: SEASON, 2022: [v + 5 for v in SEASON], 2023: [v + 10 for v in SEASON]}, "M")
    svg = C.seasonal_chart(df, freq="M", unit_code="ALL", unit_label="ALL million", title="Exports")
    assert aria(svg) == "Exports: 3 years"
    assert count(svg, "ln old") == 2  # the two earlier years
    assert svg.count('class="ln"') == 1 and count(svg, "pt") == 12  # the latest year: a line and twelve points
    assert [m for m in MONTHS if f">{m}<" in svg] == MONTHS
    assert "2023" in svg and "Earlier years" in svg and "ALL million" in svg


def test_every_month_has_a_tooltip_with_the_latest_year_first():
    df = frame({2021: SEASON, 2022: [v + 5 for v in SEASON], 2023: [v + 10 for v in SEASON]}, "M")
    data = tips(C.seasonal_chart(df, freq="M"))
    assert len(data) == 1 and len(data[0]) == 12
    june = data[0][5]
    assert june["h"] == "Jun"
    assert [r[1] for r in june["r"]] == ["2023", "2022", "2021"]  # latest year first
    assert [r[0] for r in june["r"]] == ["c1", "co", "co"]  # only the latest is highlighted
    assert june["r"][0][2] == "100" or june["r"][0][2].startswith("1")  # the value is the figure for that year and month


def test_quarterly_years_have_four_positions_named_after_quarters():
    df = frame({2021: [10, 20, 30, 15], 2022: [11, 21, 31, 16]}, "Q")
    svg = C.seasonal_chart(df, freq="Q")
    assert aria(svg) == "Seasonal pattern: 2 years"
    assert [q for q in ("Q1", "Q2", "Q3", "Q4") if f">{q}<" in svg] == ["Q1", "Q2", "Q3", "Q4"]
    assert ">Jan<" not in svg
    assert count(svg, "ln old") == 1 and count(svg, "hit") == 4


def test_a_single_year_has_the_singular_title_and_no_earlier_lines():
    svg = C.seasonal_chart(frame({2023: SEASON}, "M"), freq="M")
    assert aria(svg) == "Seasonal pattern: 1 year"
    assert count(svg, "ln old") == 0 and svg.count('class="ln"') == 1


def test_a_year_with_one_figure_is_a_point_not_a_line():
    df = frame({2022: SEASON, 2023: [50]}, "M")
    svg = C.seasonal_chart(df, freq="M")
    assert svg.count('class="ln"') == 0 and count(svg, "pt") == 1  # the latest year has a single point
    assert count(svg, "ln old") == 1


def test_an_earlier_year_with_one_figure_adds_no_line():
    df = frame({2022: [40], 2023: SEASON}, "M")
    svg = C.seasonal_chart(df, freq="M")
    assert count(svg, "ln old") == 0 and svg.count('class="ln"') == 1


def test_missing_months_leave_gaps_in_the_tooltips_and_no_points():
    values = list(SEASON)
    values[2] = None
    df = frame({2022: SEASON, 2023: values}, "M")
    svg = C.seasonal_chart(df, freq="M")
    assert count(svg, "pt") == 11
    data = tips(svg)
    march = data[0][2]
    assert [r[1] for r in march["r"]] == ["2022"]  # no 2023 row for the month without a figure


def test_no_figures_gives_the_empty_chart_instead_of_failing():
    df = frame({2023: [None] * 12}, "M")
    assert C.seasonal_chart(df, freq="M") == C._empty()
    assert C.seasonal_chart(pd.DataFrame({"period_start": pd.to_datetime([]), "value": []}), freq="M") == C._empty()


def test_the_tooltips_show_at_most_eight_years():
    df = frame({2010 + k: [v + k for v in SEASON] for k in range(12)}, "M")
    svg = C.seasonal_chart(df, freq="M")
    data = tips(svg)
    assert all(len(month["r"]) == 8 for month in data[0])
    assert data[0][0]["r"][0][1] == "2021" and data[0][0]["r"][-1][1] == "2014"
    assert aria(svg) == "Seasonal pattern: 12 years"


def test_the_albanian_chart_names_months_and_legend_in_albanian():
    from instatkit import i18n

    df = frame({2022: SEASON, 2023: SEASON}, "M")
    with i18n.using("sq"):
        svg = C.seasonal_chart(df, freq="M")
    assert "Vitet e mëparshme" in svg and "Earlier years" not in svg
    assert [h["h"] for h in tips(svg)[0]][:3] == ["jan", "shk", "mar"]  # Janar, Shkurt, Mars


# --- the whole way: a table with strong seasons gets the chart ---
def seasonal_workbook(years: int = 4, values: list[float] | None = None) -> bytes:
    """One row of monthly figures; by default the same yearly curve every year on a slowly rising level."""
    values = values or [SEASON[m] + 2 * k for k in range(years) for m in range(12)]
    wb = Writer()
    ws = wb.active
    ws["A1"], ws["A2"] = "Eksportet mujore", "Monthly exports (ALL million)"
    ws.cell(4, 1, "Treguesi / Indicator")
    ws.cell(5, 1, "Exports")
    for k in range(years):
        for m, name in enumerate(MONTHS):
            col = 2 + k * 12 + m
            ws.cell(4, col, f"{name} {2019 + k}")
            ws.cell(5, col, values[k * 12 + m])
    return wb.save()


def test_a_strongly_seasonal_monthly_table_gets_a_seasonal_chart():
    pf = process_workbook_bytes(seasonal_workbook())
    assert pf.ok, pf.errors
    pt = pf.tables[0]
    assert pt.profile.freq == "M" and pt.profile.n_periods == 48
    charts = {c.kind: c for c in render_charts(pt.table, pt.profile, pt.analysis)}
    assert {"lines", "seasonal"} <= set(charts)
    seasonal = charts["seasonal"]
    assert seasonal.title.startswith("Seasonal pattern") and "Exports" in seasonal.title
    assert aria(seasonal.svg) == f"{seasonal.title}: 4 years" or aria(seasonal.svg).endswith(": 4 years")
    assert count(seasonal.svg, "ln old") == 3


def test_a_table_without_seasons_gets_no_seasonal_chart():
    noise = [50 + (i * 37 + (i * i) % 11) % 9 for i in range(48)]  # no yearly rhythm: 37 and 11 share nothing with 12
    pf = process_workbook_bytes(seasonal_workbook(values=noise))
    pt = pf.tables[0]
    assert "seasonal" not in {c.kind for c in render_charts(pt.table, pt.profile, pt.analysis)}


def test_a_short_series_gets_no_seasonal_chart():
    pf = process_workbook_bytes(seasonal_workbook(years=1))
    pt = pf.tables[0]
    assert "seasonal" not in {c.kind for c in render_charts(pt.table, pt.profile, pt.analysis)}


# --- map of missing values ---
def test_only_the_missing_cells_are_drawn():
    missing = pd.DataFrame([[False, True, False, True], [False, False, False, False], [True, True, True, False]],
                           index=["a", "b", "c"], columns=["2020", "2021", "2022", "2023"])
    svg = C.missing_map(missing, ["Alpha", "Beta", "Gamma"], title="Gaps")
    assert count(svg, "cell m") == 5  # two in the first row, none in the second, three in the third
    assert aria(svg) == "Gaps: 3 series"
    assert all(label in svg for label in ("Alpha", "Beta", "Gamma"))


def test_each_missing_cell_says_which_series_and_period_it_is():
    missing = pd.DataFrame([[True, False]], index=["a"], columns=["2020", "2021"])
    svg = C.missing_map(missing, ["Alpha"])
    assert re.findall(r'data-t="([^"]*)"', svg) == ["Alpha · 2020\nmissing"] or re.findall(r'data-t="([^"]*)"', svg) == ["Alpha · 2020&#10;missing"]
    assert aria(svg) == "Missing values: 1 series"


def test_a_long_series_name_is_cut_in_the_map_but_not_in_the_tooltip():
    name = "Persons employed in the wholesale and retail trade; repair of vehicles"
    missing = pd.DataFrame([[True]], index=["a"], columns=["2020"])
    svg = C.missing_map(missing, [name])
    assert name not in re.sub(r'data-t="[^"]*"', "", svg)  # the printed label is shortened
    assert "…" in svg
    assert name in svg  # the tooltip keeps the whole name


def test_a_map_with_many_periods_labels_about_twelve_of_them():
    cols = [f"{y}-{m:02d}" for y in range(2010, 2024) for m in range(1, 13)]
    missing = pd.DataFrame([[i % 7 == 0 for i in range(len(cols))]], index=["a"], columns=cols)
    svg = C.missing_map(missing, ["Alpha"])
    labels = re.findall(r'<text[^>]*class="tm"[^>]*>', svg)
    assert 8 <= len(labels) <= 13


def test_an_all_present_map_still_draws_the_frame_without_marks():
    missing = pd.DataFrame([[False, False]], index=["a"], columns=["2020", "2021"])
    svg = C.missing_map(missing, ["Alpha"])
    assert count(svg, "cell m") == 0 and svg.startswith("<svg")


def test_the_quality_tab_draws_the_map_when_cells_are_missing():
    pt = process_demo("wages").tables[0]
    reply = api.quality(pt)
    missing_cells = int(pt.table.df["value"].isna().sum())
    assert missing_cells > 0
    assert reply["missing_svg"].startswith("<svg")
    assert 0 < count(reply["missing_svg"], "cell m") <= missing_cells


def test_the_quality_tab_has_no_map_when_nothing_is_missing():
    pt = process_demo("cpi").tables[0]
    assert not pt.table.df["value"].isna().any()
    assert api.quality(pt)["missing_svg"] == ""


def test_the_map_lists_only_series_with_gaps_and_marks_exactly_the_gaps():
    wb = Writer()
    ws = wb.active
    ws["A1"], ws["A2"] = "Popullsia", "Population (persons)"
    ws.cell(4, 1, "Kategoria / Category")
    for j, y in enumerate([2018, 2019, 2020, 2021]):
        ws.cell(4, 2 + j, y)
    rows = [("Complete", [1, 2, 3, 4]), ("Gappy", [5, "..", 7, ".."]), ("Also complete", [8, 9, 10, 11])]
    for i, (name, values) in enumerate(rows):
        ws.cell(5 + i, 1, name)
        for j, v in enumerate(values):
            ws.cell(5 + i, 2 + j, v)
    pt = process_workbook_bytes(wb.save()).tables[0]
    svg = api.quality(pt)["missing_svg"]
    assert count(svg, "cell m") == 2
    assert aria(svg) == "Missing values: 1 series"
    printed = re.sub(r'data-t="[^"]*"', "", svg)
    assert "Gappy" in printed and "Complete" not in printed
    assert re.findall(r'data-t="([^"]*)"', svg) == ["Population (persons) (Gappy) · 2019&#10;missing",
                                                     "Population (persons) (Gappy) · 2021&#10;missing"]


@pytest.mark.parametrize("lang,word", [("en", "missing"), ("sq", "mungon")])
def test_the_tooltip_of_a_missing_cell_is_in_the_language_of_the_page(lang, word):
    from instatkit import i18n

    missing = pd.DataFrame([[True]], index=["a"], columns=["2020"])
    with i18n.using(lang):
        svg = C.missing_map(missing, ["Alpha"])
    assert re.findall(r'data-t="([^"]*)"', svg) == [f"Alpha · 2020&#10;{word}"]
