"""End to end: the demo builders write a workbook *and* return the numbers they wrote, so the reader's output can be
checked against the truth cell by cell. These are the guard rails for any change to the layout detector."""

from __future__ import annotations

import pytest

from instatkit import demo
from instatkit.pipeline import SourceInfo, process_bytes

from .conftest import process_demo


def _process(data: bytes, name: str = "t.xlsx"):
    return process_bytes(data, name, source=SourceInfo(name, "", len(data), "demo"))


def test_cpi_values_codes_and_cells():
    data, truth = demo.make_cpi_consistent(30, (2023, 1))
    pf = _process(data)
    assert pf.ok, pf.errors
    t = pf.tables[0]
    df = t.table.df
    assert t.profile.freq == "M" and t.profile.n_periods == 30 and t.profile.n_series == 7
    assert sorted(df["period"].unique()) == truth["periods"]
    by_code = {c: g.set_index("period")["value"] for c, g in df.groupby("code")}
    for k, period in enumerate(truth["periods"]):
        assert by_code["000000"][period] == pytest.approx(truth["total"][k])
        for code, vals in truth["groups"].items():
            assert by_code[code][period] == pytest.approx(vals[k]), (code, period)
    assert df.loc[df["code"] == "000000", "is_total"].all()
    first = df[(df["code"] == "000000") & (df["period"] == "2023-01")].iloc[0]
    assert first["src_ref"] == "D6"                      # every number points back to its cell in the INSTAT file
    assert "2020-12" in t.profile.unit and "100" in t.profile.unit
    assert t.profile.missing_periods == []


def test_cpi_contributions_add_up_to_headline_inflation():
    pf = process_demo("cpi")
    checks = {c.key: c for c in pf.tables[0].analysis.checks}
    check = checks["contributions add up to headline inflation"]      # the demo is built so that they do, exactly
    assert check.status == "pass", check.detail
    assert any("contribut" in f.text.lower() for f in pf.tables[0].analysis.facts), "the findings should say which groups drove inflation"


def test_lfs_quarterly_rates():
    data, truth = demo.make_lfs_quarterly(14, (2023, 1))
    pf = _process(data)
    assert pf.ok, pf.errors
    t = pf.tables[0]
    df = t.table.df
    assert t.profile.freq == "Q" and sorted(df["period"].unique()) == truth["periods"]
    assert t.profile.unit == "%" or "%" in t.profile.unit
    for (age, sex), vals in truth["rows"].items():
        g = df[(df["age_group_orig"] == age) & (df["sex_orig"] == sex)].sort_values("period_start")
        assert len(g) == 14, (age, sex)
        assert g["value"].tolist() == pytest.approx(vals)
    assert {"age_group", "sex"} <= {d.role for d in t.profile.dims}


def test_gdp_workbook_skips_cover_and_contents():
    data, truth = demo.make_gdp_workbook()
    pf = _process(data)
    assert pf.ok, pf.errors
    assert len(pf.tables) == 2
    skipped = {name for name, _why in pf.result.skipped}
    assert {"Kapaku-Cover", "Permbajtja-Content"} <= skipped
    first = pf.tables[0].table.df
    assert pf.tables[0].profile.freq == "A"
    gdp = first[first["measure"].str.contains("Output")].set_index("period")["value"]
    for year, row in truth["gdp"].items():
        assert gdp[year] == pytest.approx(row["output"])
    assert pf.meta.get("published")                       # the cover sheet's "Publikuar: 29.06.2026" is picked up
    growth = pf.tables[1].table.df
    for code, vals in truth["growth"].items():
        got = growth[growth["code"] == code].sort_values("period_start")["value"].tolist()
        assert got == pytest.approx(vals), code
    assert "%" in pf.tables[1].profile.unit


def test_trade_is_transposed_and_has_unpadded_months():
    data, truth = demo.make_trade_monthly(14, (2021, 12))
    pf = _process(data)
    assert pf.ok, pf.errors
    df = pf.tables[0].table.df
    assert sorted(df["period"].unique()) == truth["periods"]        # '2 - 22' and '02 - 22' are the same month
    exp = df[df["measure"] == "Exports"].sort_values("period_start")["value"].tolist()
    imp = df[df["measure"] == "Imports"].sort_values("period_start")["value"].tolist()
    assert exp == pytest.approx(truth["exports"]) and imp == pytest.approx(truth["imports"])
    assert "Coverage ratio (%)" in set(df["measure"])
    assert df[df["measure"] == "Coverage ratio (%)"]["unit"].iloc[0] == "%"


def test_population_two_level_header():
    data, truth = demo.make_population()
    pf = _process(data)
    assert pf.ok, pf.errors
    t = pf.tables[0]
    df = t.table.df
    assert t.profile.freq == "A" and sorted(df["period"].unique()) == [str(y) for y in truth["years"]]
    sexes = {"Male", "Female", "Total"}
    assert sexes <= set(df["sex"])
    for (year, age), (m, f, tot) in list(truth["rows"].items())[:12]:
        g = df[(df["age_group_orig"] == age) & (df["period"] == str(year))].set_index("sex")["value"]
        assert (g["Male"], g["Female"], g["Total"]) == (m, f, tot)
    for year, (m, _f, tot) in truth["totals"].items():
        g = df[(df["is_total"]) & (df["period"] == str(year))].set_index("sex")["value"]
        assert g["Total"] == tot and g["Male"] == m


def test_population_parts_add_up_to_the_stated_total():
    pf = process_demo("population")
    checks = {c.key: c for c in pf.tables[0].analysis.checks}
    sums = [c for k, c in checks.items() if k.startswith("parts add up")]
    assert sums and all(c.status in ("pass", "info") for c in sums), [(c.key, c.status, c.detail) for c in sums]


def test_tourism_months_down_the_rows():
    data, truth = demo.make_month_by_year()
    pf = _process(data)
    assert pf.ok, pf.errors
    t = pf.tables[0]
    assert t.table.spec.orientation == "month_by_year" and t.profile.freq == "M"
    got = {(int(p[:4]), int(p[5:7])): v for p, v in zip(t.table.df["period"], t.table.df["value"])}
    assert got == {k: float(v) for k, v in truth["rows"].items()}


def test_wages_markers_become_missing_values_with_a_reason():
    data, truth = demo.make_cross_section()
    pf = _process(data)
    assert pf.ok, pf.errors
    df = pf.tables[0].table.df
    assert pf.tables[0].table.spec.orientation == "cross_section"
    assert len(df) == 18
    missing = df[df["value"].isna()]
    assert sorted(missing["flag"]) == ["na", "nil"]                 # '..' = not available, '-' = nothing to report
    tirana = df[df["activity_orig"] == "Tregtia"].set_index("sex")["value"]
    assert tirana["Total"] == 61500 and tirana["Males"] == 64200    # numbers stored as text with a space


@pytest.mark.parametrize("name", list(demo.DEMOS))
def test_every_demo_reads_cleanly_in_both_languages(name):
    en, sq = process_demo(name, "en"), process_demo(name, "sq")
    for pf in (en, sq):
        assert pf.ok and not pf.errors, (name, pf.errors)
        for pt in pf.tables:
            assert pt.profile.confidence >= 0.8, (name, pt.table.sheet, pt.profile.confidence)
            assert pt.briefing.what_is_this and pt.analysis.tiles is not None
    assert [len(t.table.df) for t in en.tables] == [len(t.table.df) for t in sq.tables]
    assert en.tables[0].briefing.what_is_this != sq.tables[0].briefing.what_is_this
