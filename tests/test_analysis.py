"""Statistics and the sentences written from them: edge cases."""

from __future__ import annotations

import json
import math
import re

import numpy as np
import pytest

from instatkit import demo
from instatkit.analysis.fmt import fmt_number, fmt_pct, fmt_pp, fmt_value, human_period
from instatkit.analysis.insights import Ctx, series_facts
from instatkit.analysis.series import compute_series_stats, linear_trend, robust_outliers
from instatkit.export.xlsx_writer import Workbook as Writer
from instatkit.semantics.periods import from_label, make_month
from instatkit.semantics.units import UnitInfo
from instatkit.web.common import dumps

from .conftest import process_demo, process_workbook_bytes

JUNK = re.compile(r"\b(nan|inf|infinity|none)\b", re.I)


def months(n: int, start=(2020, 1)):
    y, m = start
    out = []
    for _ in range(n):
        out.append(make_month(y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


# --- statistics ---------------------------------------------------------------------------------------------------

def test_too_little_data_gives_no_statistics():
    assert compute_series_stats(months(1), np.array([1.0])) is None
    assert compute_series_stats(months(5), np.full(5, np.nan)) is None
    two = compute_series_stats(months(2), np.array([1.0, 2.0]))
    assert two is not None and two.change_abs == 1.0 and two.trend is None


def test_a_flat_series_has_no_record():
    """A constant series is not 'the highest of all N observations'."""
    st = compute_series_stats(months(24), np.full(24, 5.0))
    assert st.record is None and st.trend.direction == "flat"
    tie = np.r_[np.arange(10.0), 9.0]                                   # equals the old maximum: not a new record
    assert compute_series_stats(months(11), tie).record is None
    assert compute_series_stats(months(11), np.arange(11.0)).record == "high"
    assert compute_series_stats(months(11), -np.arange(11.0)).record == "low"


def test_trend_is_per_period_even_when_months_are_missing():
    """The slope used 0,1,2... for the observations, so a gap made the trend steeper than the data."""
    ps = [p for p in months(24) if not (4 <= p.start.month <= 9 and p.start.year == 2020)]     # six months missing
    ordinal = np.array([p.start.year * 12 + p.start.month for p in ps], dtype=float)
    values = 10 + 2.0 * (ordinal - ordinal[0])                         # exactly +2 a month
    st = compute_series_stats(ps, values, kind="rate")
    assert st.missing == 6
    assert st.trend.slope == pytest.approx(2.0)
    assert linear_trend(np.arange(5.0), log=False).slope == pytest.approx(1.0)
    assert linear_trend(np.arange(5.0), log=False, t=np.array([0, 2, 4, 6, 8.0])).slope == pytest.approx(0.5)


def test_outliers_need_spread():
    assert robust_outliers(np.full(20, 3.0)) == []
    x = np.r_[np.random.default_rng(1).normal(0, 1, 30), 40.0]
    assert [i for i, _z in robust_outliers(x)][0] == 30


def test_changes_are_percentages_only_for_positive_levels():
    positive = compute_series_stats(months(30), 100 + np.arange(30.0) + np.where(np.arange(30) == 20, 40, 0))
    assert positive.pct_changes
    crossing = compute_series_stats(months(30), np.sin(np.arange(30) / 3) * 20)
    assert not crossing.pct_changes


def _facts(values, kind="level", unit="ALL"):
    st = compute_series_stats(months(len(values)), np.asarray(values, dtype=float), kind=kind)
    ctx = Ctx(UnitInfo(unit=unit, scale=1e6 if unit == "ALL" else None), kind, "M")
    return st, {f.kind: f for f in series_facts("Trade balance", st, ctx, headline=True)}


def test_a_level_that_goes_negative_is_not_described_in_percent():
    """Outlier and level-shift sentences always used fmt_pct, although the changes were plain differences in ALL."""
    rng = np.random.default_rng(7)
    values = rng.normal(-40, 6, 48)
    values[30] = 120                                                    # a spike in a series that is mostly negative
    values[24:] += 60                                                   # and a lasting move
    st, facts = _facts(values)
    assert not st.pct_changes
    text = " ".join(f.text for f in facts.values())
    assert "anomaly" in facts and "%" not in facts["anomaly"].text, facts["anomaly"].text
    assert "ALL" in facts["anomaly"].text
    assert not JUNK.search(text), text
    if "shift" in facts:
        assert "%" not in facts["shift"].text


def test_a_positive_level_is_described_in_percent():
    rng = np.random.default_rng(3)
    values = 100 + np.cumsum(rng.normal(0.3, 0.4, 48))
    values[30] *= 1.5
    st, facts = _facts(values)
    assert st.pct_changes and "anomaly" in facts and "%" in facts["anomaly"].text


# --- number and period formatting ----------------------------------------------------------------------------------

@pytest.mark.parametrize("fn", [fmt_pct, fmt_pp])
def test_missing_numbers_are_never_written_as_nan(fn):
    for bad in (float("nan"), float("inf"), float("-inf"), None):
        assert fn(bad) == "n/a", (fn.__name__, bad)
    assert fmt_number(float("inf")) == "n/a" and fmt_value(float("nan"), "ALL") == "n/a"


def test_rounding_to_zero_has_no_sign():
    assert fmt_pct(-0.04) == "0.0%" and fmt_pp(-0.04) == "0.0 pp"
    assert fmt_pct(-0.04, signed=True) == "0.0%" and fmt_pct(0.04, signed=True) == "0.0%"
    assert fmt_pct(-1.25) == "−1.3%" or fmt_pct(-1.25) == "−1.2%"
    assert fmt_pct(1.25, signed=True).startswith("+") and fmt_pct(-3, signed=True).startswith("−")


def test_human_period():
    assert human_period("2017-01") == "January 2017" and human_period("2023-Q2") == "Q2 2023"
    assert human_period("2024-H2") == "H2 2024" and human_period("2019-2023") == "2019-2023"
    assert human_period("2024-03-31") == "31 March 2024"
    assert human_period("2020-2021-2022") == "2020-2021-2022"            # not an error
    assert human_period("") == "" and human_period("2020-13") == "2020-13"


def test_labels_in_the_facts_use_the_calendar_not_a_guess():
    """2005-06 in a canonical label is June 2005; reading it back as the years 2005-2006 hid real gaps."""
    assert from_label("2005-06").freq == "M"


# --- sentences from real tables -------------------------------------------------------------------------------------

def _trade_workbook(n=30, missing_last_import=False, zero_imports=False):
    wb = Writer()
    ws = wb.active
    ws["A1"], ws["A2"], ws["A4"] = "Qarkullimi i mallrave", "Flow of goods in foreign trade", "miliardë lekë/billion ALL"
    ms = months(n, (2021, 1))
    for j, p in enumerate(ms):
        ws.cell(5, 2 + j, f"{p.start.month:02d} - {p.start.year % 100:02d}")
    rng = np.random.default_rng(5)
    exp = 30 + rng.uniform(0, 10, n)
    imp = 80 + rng.uniform(0, 10, n)
    rows = [("Eksporte", exp), ("Importe", imp), ("Bilanci tregtar", exp - imp), ("Përqindja e mbulimit \nCoverage ratio (%)", 100 * exp / imp)]
    for i, (name, vals) in enumerate(rows):
        ws.cell(6 + i, 1, name)
        for j, v in enumerate(vals):
            if name == "Importe" and j == n - 1 and (missing_last_import or zero_imports):
                v = None if missing_last_import else 0.0
            ws.cell(6 + i, 2 + j, v)
    return wb.save()


@pytest.mark.parametrize("variant", [{}, {"missing_last_import": True}, {"zero_imports": True}])
def test_trade_findings_never_contain_nan_or_inf(variant):
    pf = process_workbook_bytes(_trade_workbook(**variant))
    assert pf.ok, pf.errors
    t = pf.tables[0]
    for f in t.analysis.facts:
        assert not JUNK.search(f.text), f.text
    for c in t.analysis.checks:
        assert not JUNK.search(c.detail), c.detail
    assert not JUNK.search(t.briefing.markdown())
    assert not t.analysis.warnings, t.analysis.warnings


def test_trade_summary_uses_the_last_complete_month():
    pf = process_workbook_bytes(_trade_workbook(missing_last_import=True))
    trade = [f for f in pf.tables[0].analysis.facts if f.kind == "trade" and f.data.get("period")]
    assert trade and trade[0].data["period"] == "2023-05", trade[0].data     # June 2023 has no imports yet


def test_missing_figures_are_not_counted_as_passing_an_identity():
    pf = process_workbook_bytes(_trade_workbook(missing_last_import=True))
    checks = {c.key: c for c in pf.tables[0].analysis.checks}
    balance = checks["trade balance equals exports minus imports"]
    assert balance.status == "pass" and "29 periods" in balance.detail       # 30 months, one of them untestable


@pytest.mark.parametrize("name", ["cpi", "lfs", "gdp", "trade", "population", "tourism", "wages"])
def test_no_demo_produces_junk_text_in_either_language(name):
    for lang in ("en", "sq"):
        pf = process_demo(name, lang)
        for pt in pf.tables:
            blob = " ".join([pt.briefing.markdown(), pt.briefing.what_is_this] + [f.text for f in pt.analysis.facts]
                            + [c.detail for c in pt.analysis.checks] + [t.value + t.delta for t in pt.analysis.tiles])
            assert not JUNK.search(blob), (name, lang, JUNK.search(blob).group(0))
            assert not re.search(r"\{\w+\}", blob), (name, lang, "an unfilled placeholder")
            assert pt.analysis.warnings == [], (name, lang, pt.analysis.warnings)


def test_chart_warnings_are_not_repeated_on_every_visit(monkeypatch):
    from instatkit.viz import build

    pt = process_demo("cpi").tables[0]
    monkeypatch.setattr(build, "_render", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    build.render_charts(pt.table, pt.profile, pt.analysis)
    first = list(pt.analysis.warnings)
    assert first
    build.render_charts(pt.table, pt.profile, pt.analysis)
    build.render_charts(pt.table, pt.profile, pt.analysis)
    assert pt.analysis.warnings == first


def test_charts_for_every_demo_render():
    from instatkit.viz.build import render_charts

    for name in ("cpi", "lfs", "gdp", "trade", "population", "tourism", "wages"):
        pt = process_demo(name).tables[0]
        charts = render_charts(pt.table, pt.profile, pt.analysis)
        assert charts, name
        for c in charts:
            assert c.svg.startswith("<svg") and c.svg.rstrip().endswith("</svg>")
            assert not JUNK.search(re.sub(r"<[^>]+>", " ", c.svg)), (name, c.title)


# --- JSON for the browser -------------------------------------------------------------------------------------------

def test_replies_are_always_valid_json():
    """``json.dumps`` writes NaN and Infinity, which JSON.parse in the browser rejects."""
    payload = {"a": float("nan"), "b": [float("inf"), 1.5, np.float64("nan")], "c": np.int64(3), "d": {"e": float("-inf")},
               "f": (1, 2), "g": "text"}

    def strict(token):
        raise AssertionError(f"not JSON: {token}")

    back = json.loads(dumps(payload), parse_constant=strict)
    assert back == {"a": None, "b": [None, 1.5, None], "c": 3, "d": {"e": None}, "f": [1, 2], "g": "text"}
    assert math.isclose(json.loads(dumps({"x": np.float64(2.5)}))["x"], 2.5)


def test_bar_and_heatmap_specs_name_the_measure_the_text_is_about():
    """The charts used the first measure of the table while the sentences next to them used the most telling one."""
    pt = process_demo("lfs").tables[0]
    specs = [c for c in pt.analysis.charts if c.kind in ("bars", "heatmap")]
    assert specs and all(c.params["measure"] == pt.profile.measures[0].name for c in specs)


def _prices_with_a_late_starter():
    wb = Writer()
    ws = wb.active
    ws["A1"], ws["A2"] = "Indeksi i çmimeve sipas grupit", "Price index by group"
    ms = months(30, (2021, 1))
    ws.cell(4, 1, "Grupi")
    for j, p in enumerate(ms):
        ws.cell(4, 2 + j, f" {p.start.month:02d}-{p.start.year % 100:02d}")
    rng = np.random.default_rng(2)
    for i, name in enumerate(["Gjithsej", "Ushqime", "Veshje", "Transport", "Banesa", "Shëndetësi"]):
        ws.cell(5 + i, 1, name)
        level = 100.0
        for j in range(len(ms)):
            level *= 1 + rng.uniform(0.0, 0.01)
            if name == "Transport" and j < 18:
                continue                                     # a series that only began a year and a half in: no value a year earlier
            ws.cell(5 + i, 2 + j, level)
    return wb.save()


def test_movers_are_compared_on_one_basis():
    """All movers are ranked on one basis: year-on-year only when every category has a value for the year before."""
    pf = process_workbook_bytes(_prices_with_a_late_starter())
    assert pf.ok, pf.errors
    movers = [f for f in pf.tables[0].analysis.facts if f.kind == "movers"]
    assert movers, "expected a ranking of categories"
    assert all(f.data["basis"] == "the previous period" for f in movers), [f.data["basis"] for f in movers]
    assert all("a year earlier" not in f.text for f in movers)


def test_colliding_values_mark_the_table_as_misread(monkeypatch):
    """Two values for one series and period lower the confidence and add a warning."""
    from instatkit.analysis import checks
    from instatkit.analysis.facts import Check
    from instatkit.export.html_report import build_report

    failing = Check("duplicate observations", "fail", "6 values share the same series and period. The headers or row labels may have been misread.",
                    name="Duplicates")
    monkeypatch.setattr(checks, "_duplicates", lambda df: failing)
    pf = process_demo("cpi")
    pt = pf.tables[0]
    assert pt.profile.confidence <= 0.5
    assert "probably read wrongly" in pt.analysis.warnings[0] and "6 values share" in pt.analysis.warnings[0]
    html = build_report(pf)
    assert 'class="warn"' in html and "probably read wrongly" in html
    sq = process_demo("cpi", "sq").tables[0]
    assert "lexuar gabim" in sq.analysis.warnings[0]


def test_clean_table_keeps_its_confidence():
    pt = process_demo("cpi").tables[0]
    assert pt.profile.confidence > 0.9 and pt.analysis.warnings == []


def test_a_population_pyramid_is_only_drawn_for_counts_of_people():
    """Unemployment rates by age group and sex got a 'population pyramid' as well."""
    kinds = lambda name: {c.kind for c in process_demo(name).tables[0].analysis.charts}  # noqa: E731
    assert "pyramid" in kinds("population")
    assert "pyramid" not in kinds("lfs") and "pyramid" not in kinds("wages")


@pytest.mark.parametrize("name", list(demo.DEMOS))
def test_a_check_does_not_say_its_examples_a_second_time(demo_file, name):
    """The Quality tab, the report and the workbook list a check's examples under its detail; the detail must not already contain them."""
    for pt in demo_file(name).tables:
        for check in pt.analysis.checks:
            for example in check.examples:
                assert example not in check.detail, (check.name, example)
