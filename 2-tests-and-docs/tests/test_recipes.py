"""The extra findings for the statistics people ask about most (inflation, GDP, trade, population, youth unemployment, pay gap).

Every expected number here is worked out from the demo builders' own ``truth`` (the figures written into the workbook), never taken from
the program's output. A recipe is run on a processed demo table, often after one figure was changed, so the effect of that change is known."""

from __future__ import annotations

import dataclasses
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from instatkit import demo, i18n
from instatkit.analysis import recipes
from instatkit.analysis.facts import Fact
from instatkit.analysis.recipes import (
    _age_bounds,
    _find_measure,
    _hold_others,
    _holds,
    _moved,
    _one_measure,
    _prior,
    _val,
    age_structure,
    apply_recipes,
    cpi_contributions,
    gdp_identities,
    gender_pay_gap,
    trade_balance,
    youth_unemployment,
)
from instatkit.semantics.interpret import DimInfo, MeasureInfo

from .conftest import process_workbook_bytes


def processed(data: bytes, index: int = 0):
    with i18n.using("en"):
        pf = process_workbook_bytes(data)
    assert pf.ok, pf.errors
    t = pf.tables[index]
    return t.table, t.profile


def run(recipe, table, profile, facts=None):
    """The recipe on its own, with a bare analysis that only records what the recipe adds."""
    analysis = SimpleNamespace(extras={}, checks=[], warnings=[])
    facts = [] if facts is None else facts
    with i18n.using("en"):
        recipe(table, profile, analysis, facts)
    return analysis, facts


def edited(table, change):
    """The table with ``change(df)`` applied to a copy of its data (``change`` edits it in place or returns a new frame)."""
    df = table.df.copy()
    result = change(df)
    return dataclasses.replace(table, df=df if result is None else result)


def checks_by_key(analysis):
    return {c.key: c for c in analysis.checks}


# --- the small functions ---
def test_val_picks_the_first_known_figure_of_a_period_for_the_given_labels():
    df = pd.DataFrame({"period": ["2024", "2024", "2024", "2025"], "sex": ["M", "F", "F", "M"], "value": [1.0, np.nan, 3.0, 4.0]})
    assert _val(df, "2024", sex="M") == 1.0
    assert _val(df, "2024", sex="F") == 3.0                           # the blank is skipped, not returned
    assert _val(df, "2025") == 4.0 and _val(df, "2026") is None and _val(df, "2025", sex="F") is None


@pytest.mark.parametrize("period, n, expected", [
    ("2025-12", 12, "2024-12"), ("2025-03", 12, "2024-03"), ("2025-Q1", 4, "2024-Q1"), ("2025-Q1", 1, "2024-Q4"), ("2025", 1, "2024"), ("2025-01", 1, "2024-12"),
    ("not a period", 12, None), ("", 12, None),
])
def test_the_period_n_steps_back(period, n, expected):
    assert _prior(period, n) == expected


def test_a_measure_is_found_by_any_of_the_words_in_its_name_case_insensitively():
    df = pd.DataFrame({"measure": ["Output", "Gross Value Added", "GDP at market prices"]})
    assert _find_measure(df, "output") == "Output"
    assert _find_measure(df, "net taxes", "value added") == "Gross Value Added"
    assert _find_measure(df, "gdp at market", "gross domestic product", "gdp") == "GDP at market prices"
    assert _find_measure(df, "wages") is None
    assert _find_measure(df) is None


def test_the_sentence_for_a_check_that_holds_or_fails():
    nothing = pd.Series(dtype=float)
    assert _holds(nothing, 12) == "It holds in all 12 periods."
    assert _holds(nothing, 12, 0.001) == "It holds in all 12 periods (largest gap 0.100%)."
    assert _holds(pd.Series([0.1, 0.2]), 12) == "It fails in 2 of 12 periods."
    assert _holds(pd.Series([0.1, 0.2]), 12, 0.5) == "It fails in 2 of 12 periods."            # the worst gap is only quoted when nothing failed


def test_a_change_is_worded_as_rose_or_fell_with_its_size_without_a_sign():
    assert _moved(5.14) == "rose 5.1%" and _moved(-2.34) == "fell 2.3%" and _moved(0.0) == "rose 0.0%" and _moved(-0.04) == "fell 0.0%"


@pytest.mark.parametrize("label, bounds", [
    ("0-4", (0, 4)), ("15 - 64", (15, 64)), ("15–64", (15, 64)), ("15-64 years", (15, 64)), ("5-9 year", (5, 9)),
    ("85+", (85, None)), ("65 +", (65, None)), ("65 years and over", (65, None)), ("65 year and more", (65, None)), ("90 and over", (90, None)),
    ("under 15", (0, 14)), ("Below 5 years", (0, 4)), ("up to 29", (0, 28)), ("UNDER 1", (0, 0)),
    ("40", (40, 40)), ("25 years", (25, 25)), ("  7  ", (7, 7)),
    ("", None), ("total", None), ("1000", None), ("15-", None), ("-64", None), ("old", None), ("0-4-5", None),
])
def test_the_ages_an_age_group_label_stands_for(label, bounds):
    assert _age_bounds(label) == bounds


def dims_for_holding():
    return [DimInfo("a", "x", "A", 3, ["Total"]), DimInfo("b", "y", "B", 3, [], alias_of="a"), DimInfo("c", "z", "C", 3, ["Total"])]


def test_the_dimensions_not_asked_for_are_held_at_their_total():
    df = pd.DataFrame({"a": ["Total", "a1", "Total", "a1"], "b": ["B", "b1", "B", "b1"], "c": ["Total", "Total", "c1", "c1"], "v": [1, 2, 3, 4]})
    profile = SimpleNamespace(dims=dims_for_holding())
    held = _hold_others(df, profile, {"b"})                              # b is a copy of a: neither is held; c is held at Total
    assert held["v"].tolist() == [1, 2]
    assert _hold_others(df, profile, {"a"})["v"].tolist() == [1, 2]      # asking for a is the same as asking for its copy b
    assert _hold_others(df, profile, {"a", "c"})["v"].tolist() == [1, 2, 3, 4]
    assert _hold_others(df, profile, {"c"})["v"].tolist() == [1, 3]      # a is held at Total, and b (a copy of a, not asked for) at its only common value


def test_a_dimension_with_no_named_total_is_held_at_its_blank_or_commonest_value():
    profile = SimpleNamespace(dims=[DimInfo("d", "x", "D", 3), DimInfo("e", "y", "E", 2)])
    blank = pd.DataFrame({"d": ["x", "x", "y", ""], "e": ["k", "k", "k", "k"], "v": [1, 2, 3, 4]})
    assert _hold_others(blank, profile, {"e"})["v"].tolist() == [4]                      # the blank row is the total although x is more common
    commonest = pd.DataFrame({"d": ["x", "x", "y"], "e": ["k", "k", "k"], "v": [1, 2, 3]})
    assert _hold_others(commonest, profile, {"e"})["v"].tolist() == [1, 2]
    named = SimpleNamespace(dims=[DimInfo("d", "x", "D", 3, ["All"])])
    both = pd.DataFrame({"d": ["x", "x", "All", ""], "v": [1, 2, 3, 4]})
    assert _hold_others(both, named, set())["v"].tolist() == [3]                         # a named total wins over the blank


def test_an_empty_table_stays_empty_and_is_not_an_error():
    profile = SimpleNamespace(dims=[DimInfo("d", "x", "D", 3, ["All"]), DimInfo("e", "y", "E", 3, ["All"])])
    df = pd.DataFrame({"d": ["x", "y"], "e": ["p", "q"], "v": [1, 2]})
    assert _hold_others(df.iloc[0:0], profile, set()).empty
    assert _hold_others(df, profile, set())["v"].tolist() == [1]                         # no total in d: its first commonest value; the same in e


def test_only_one_measure_is_used_when_there_are_several():
    measures = [SimpleNamespace(name="B"), SimpleNamespace(name="A")]
    profile = SimpleNamespace(measures=measures)
    df = pd.DataFrame({"measure": ["A", "B", "A", "B"], "v": [1, 2, 3, 4]})
    assert _one_measure(df, profile)["v"].tolist() == [2, 4]                            # the first measure of the profile, not of the data
    assert _one_measure(df[df["measure"] == "A"], profile).equals(df[df["measure"] == "A"])
    assert _one_measure(df.drop(columns="measure"), profile).equals(df.drop(columns="measure"))
    other = pd.DataFrame({"measure": ["X", "Y"], "v": [1, 2]})
    assert _one_measure(other, profile).equals(other)                                   # none of them is known to the profile: leave it as it is


def test_a_recipe_that_fails_is_reported_and_the_others_still_run(monkeypatch):
    def broken_recipe(table, profile, analysis, facts):
        raise ValueError("nope")

    def working_recipe(table, profile, analysis, facts):
        facts.append("done")

    monkeypatch.setattr(recipes, "RECIPES", [broken_recipe, working_recipe])
    analysis, facts = SimpleNamespace(warnings=[]), []
    with i18n.using("en"):
        apply_recipes(None, None, analysis, facts)
    assert facts == ["done"]
    assert analysis.warnings == ["The broken recipe analysis was skipped (ValueError: nope)."]


def test_every_recipe_of_the_program_is_listed():
    assert [r.__name__ for r in recipes.RECIPES] == ["cpi_contributions", "gdp_identities", "trade_balance", "age_structure",
                                                     "youth_unemployment", "gender_pay_gap"]


# --- inflation: what each group contributed ---
@pytest.fixture(scope="module")
def cpi_case():
    data, truth = demo.make_cpi_consistent(48, (2022, 1))
    table, profile = processed(data)
    return table, profile, truth


def expected_cpi(truth, scale=1.0, last=47):
    prior = last - 12
    base = truth["total"][prior]
    contrib = {code: truth["weights"][code] * scale / 100 * (vals[last] - vals[prior]) / base * 100 for code, vals in truth["groups"].items()}
    return contrib, (truth["total"][last] / base - 1) * 100


def by_code(table, series):
    names = table.df.drop_duplicates("code").set_index("code")["product"]
    return {code: series[names[code]] for code in names.index if code in names and names[code] in series.index and code != "000000"}


def test_contribution_is_weight_times_index_change_over_total_a_year_before(cpi_case):
    table, profile, truth = cpi_case
    analysis, facts = run(cpi_contributions, table, profile)
    contrib, headline = expected_cpi(truth)
    got = analysis.extras["cpi_contributions"]
    assert list(got.values) == sorted(got.values, reverse=True)                              # the biggest first
    for code, value in by_code(table, got).items():
        assert value == pytest.approx(contrib[code]), code
    assert len(got) == 6 and analysis.extras["cpi_headline_yoy"] == pytest.approx(headline)
    [fact] = facts
    assert (fact.kind, fact.section, fact.subject, fact.importance, fact.period) == ("contribution", "composition", "Consumer prices", 0.88, "2025-12")
    assert fact.data["headline"] == pytest.approx(headline) and fact.data["sum"] == pytest.approx(sum(contrib.values()))
    assert fact.data["contributions"] == pytest.approx(got.to_dict())
    assert f"Annual inflation in December 2025 was {headline:.1f}%." in fact.text
    assert "Together the 6 main groups account for " in fact.text
    assert all(name in fact.text for name in ("Food", "Housing")) and fact.text.index("Food") < fact.text.index("Housing")


def test_the_contributions_add_up_to_inflation_and_that_is_reported_as_a_passed_check(cpi_case):
    table, profile, truth = cpi_case
    analysis, _ = run(cpi_contributions, table, profile)
    contrib, headline = expected_cpi(truth)
    assert sum(contrib.values()) == pytest.approx(headline)                                    # the demo is built so
    [check] = analysis.checks
    assert (check.key, check.status, check.name) == ("contributions add up to headline inflation", "pass", "Contributions add up to headline inflation")
    assert check.detail == f"The weighted contributions add up to {headline:.2f} pp, against {headline:.2f}% for the total index."


@pytest.mark.parametrize("factor, scale", [(10, 0.1), (1000, 0.001), (0.01, 100.0)])
def test_weights_that_do_not_add_up_to_a_hundred_are_scaled_so_that_they_do(cpi_case, factor, scale):
    table, profile, truth = cpi_case
    scaled = edited(table, lambda df: df.__setitem__("attr_weights", df["attr_weights"] * factor))
    analysis, facts = run(cpi_contributions, scaled, profile)
    contrib, headline = expected_cpi(truth)                                                    # the weights were 100 in all: only their proportions count
    for code, value in by_code(table, analysis.extras["cpi_contributions"]).items():
        assert value == pytest.approx(contrib[code]), code
    assert analysis.checks[0].status == "pass" and len(facts) == 1


@pytest.mark.parametrize("factor", [0.99, 1.0, 1.005, 1.01])
def test_weights_adding_up_to_between_99_and_101_are_taken_as_they_are(cpi_case, factor):
    table, profile, truth = cpi_case
    nearly = edited(table, lambda df: df.__setitem__("attr_weights", df["attr_weights"] * factor))
    analysis, _ = run(cpi_contributions, nearly, profile)
    contrib, _headline = expected_cpi(truth, scale=factor)
    for code, value in by_code(table, analysis.extras["cpi_contributions"]).items():
        assert value == pytest.approx(contrib[code]), code


@pytest.mark.parametrize("factor", [0.98, 1.02])
def test_weights_just_outside_that_range_are_scaled(cpi_case, factor):
    table, profile, truth = cpi_case
    off = edited(table, lambda df: df.__setitem__("attr_weights", df["attr_weights"] * factor))
    analysis, _ = run(cpi_contributions, off, profile)
    contrib, _headline = expected_cpi(truth)
    for code, value in by_code(table, analysis.extras["cpi_contributions"]).items():
        assert value == pytest.approx(contrib[code]), code


def _group_name(table, code):
    return table.df.loc[table.df["code"] == code, "product"].iloc[0]


def test_a_group_without_a_figure_in_either_period_is_left_out(cpi_case):
    table, profile, truth = cpi_case
    name = _group_name(table, "07.")
    for period in ("2025-12", "2024-12"):
        broken = edited(table, lambda df, p=period: df.__setitem__("value", df["value"].where(~((df["product"] == name) & (df["period"] == p)))))
        analysis, facts = run(cpi_contributions, broken, profile)
        got = analysis.extras["cpi_contributions"]
        assert len(got) == 5 and name not in got.index
        contrib, _headline = expected_cpi(truth, scale=100 / (100 - truth["weights"]["07."]))        # the other five weights are scaled up to a hundred
        for code, value in by_code(table, got).items():
            assert value == pytest.approx(contrib[code]), code
        assert "Together the 5 main groups" in facts[0].text


def test_a_group_without_a_weight_is_left_out(cpi_case):
    table, profile, _truth = cpi_case
    name = _group_name(table, "03.")
    unweighted = edited(table, lambda df: df.__setitem__("attr_weights", df["attr_weights"].where(df["product"] != name)))
    analysis, _ = run(cpi_contributions, unweighted, profile)
    assert len(analysis.extras["cpi_contributions"]) == 5 and name not in analysis.extras["cpi_contributions"].index


def test_fewer_than_three_groups_are_not_enough(cpi_case):
    table, profile, _truth = cpi_case
    keep = {"Total", _group_name(table, "01."), _group_name(table, "07.")}
    two = edited(table, lambda df: df[df["product"].isin(keep)])
    analysis, facts = run(cpi_contributions, two, profile)
    assert facts == [] and analysis.checks == [] and analysis.extras == {}
    three = {*keep, _group_name(table, "03.")}
    enough = edited(table, lambda df: df[df["product"].isin(three)])
    assert len(run(cpi_contributions, enough, profile)[1]) == 1


def test_a_gap_of_up_to_a_third_of_a_point_is_a_pass_and_more_is_only_information(cpi_case):
    table, profile, truth = cpi_case
    name = _group_name(table, "01.")
    weight, base = truth["weights"]["01."], truth["total"][35]
    for gap, status in ((0.2, "pass"), (0.29, "pass"), (0.31, "info"), (0.8, "info")):
        delta = gap * base / weight                                                      # this much more index in one group moves the sum by `gap` points
        moved = edited(table, lambda df, d=delta: df.__setitem__(
            "value", df["value"].where(~((df["product"] == name) & (df["period"] == "2025-12")), df["value"] + d)))
        [check] = run(cpi_contributions, moved, profile)[0].checks
        assert check.status == status, (gap, check.detail)
        assert ("A small difference is normal" in check.detail) == (status == "info")
        assert "add up to" in check.detail and "against" in check.detail


@pytest.mark.parametrize("change", [
    lambda p: dataclasses.replace(p, topics=["wages"]),
    lambda p: dataclasses.replace(p, code_system="NACE"),
    lambda p: dataclasses.replace(p, code_system=None),
    lambda p: dataclasses.replace(p, measures=[dataclasses.replace(p.measures[0], kind="level")]),
    lambda p: dataclasses.replace(p, measures=[]),
    lambda p: dataclasses.replace(p, last_period=None),
    lambda p: dataclasses.replace(p, last_period="2022-06"),                   # no figures a year before
    lambda p: dataclasses.replace(p, freq=None),
    lambda p: dataclasses.replace(p, freq="D"),                                # a frequency without a yearly lag
    lambda p: dataclasses.replace(p, dims=[]),                                 # no product dimension
])
def test_a_table_that_is_not_a_consumer_price_index_by_group_gets_no_contributions(cpi_case, change):
    table, profile, _truth = cpi_case
    analysis, facts = run(cpi_contributions, table, change(profile))
    assert facts == [] and analysis.checks == [] and analysis.extras == {}


def test_without_weights_or_levels_or_a_total_there_is_nothing_to_say(cpi_case):
    table, profile, _truth = cpi_case
    for broken in (table.df.drop(columns="attr_weights"), table.df.assign(level=np.nan), table.df.drop(columns="level"),
                   table.df[table.df["product"] != "Total"]):
        analysis, facts = run(cpi_contributions, dataclasses.replace(table, df=broken), profile)
        assert facts == [] and analysis.checks == []
    flat = edited(table, lambda df: df.__setitem__("value", df["value"].where(df["product"] != "Total")))
    assert run(cpi_contributions, flat, profile)[1] == []                      # no total index, so no base for the contributions


def test_only_the_top_level_groups_are_counted(cpi_case):
    table, profile, truth = cpi_case
    deeper = table.df.copy()
    child = deeper[deeper["code"] == "01."].copy()
    child["level"] = deeper["level"].max() + 1
    child["product"] = "A sub-group"
    child["value"] = child["value"] * 2
    analysis, _ = run(cpi_contributions, dataclasses.replace(table, df=pd.concat([deeper, child], ignore_index=True)), profile)
    assert "A sub-group" not in analysis.extras["cpi_contributions"].index and len(analysis.extras["cpi_contributions"]) == 6


# --- national accounts: the identities and the share of taxes ---
@pytest.fixture(scope="module")
def gdp_case():
    data, truth = demo.make_gdp_workbook()
    table, profile = processed(data)
    return table, profile, truth["gdp"]


def shifted(measure, period, amount):
    """An edit that adds ``amount`` to one figure of the long table."""
    return lambda df: df.__setitem__("value", df["value"].where(~((df["measure"] == measure) & (df["period"] == period)), df["value"] + amount))


def blanked(measure, period=None):
    def edit(df):
        mask = df["measure"] == measure
        if period is not None:
            mask &= df["period"] == period
        df["value"] = df["value"].where(~mask)
    return edit


OUTPUT_KEY = "output minus intermediate consumption equals gross value added"
TAX_KEY = "gross value added plus net taxes equals GDP"


def test_the_identities_of_the_accounts_hold_in_the_demo_and_the_share_of_taxes_is_reported(gdp_case):
    table, profile, gdp = gdp_case
    analysis, facts = run(gdp_identities, table, profile)
    checks = checks_by_key(analysis)
    assert list(checks) == [OUTPUT_KEY, TAX_KEY]
    first, second = checks[OUTPUT_KEY], checks[TAX_KEY]
    assert (first.status, first.name, first.examples) == ("pass", "Output minus intermediate consumption equals gross value added", [])
    assert first.detail == "It holds in all 5 periods (largest gap 0.000%)."
    assert (second.status, second.name, second.detail) == ("pass", "Gross value added plus net taxes on products equals GDP", "It holds in all 5 periods.")
    [fact] = facts
    share = gdp["2025"]["tax"] / gdp["2025"]["gdp"] * 100
    assert (fact.kind, fact.section, fact.subject, fact.importance, fact.period) == ("share", "composition", "GDP", 0.6, "2025")
    assert fact.text == f"In 2025, net taxes on products were {share:.1f}% of GDP at market prices. The rest is gross value added."
    assert fact.data == {"share": pytest.approx(share), "period": "2025"}


@pytest.mark.parametrize("fraction, status", [(0.004, "pass"), (0.0049, "pass"), (0.0051, "fail"), (0.006, "fail"), (-0.006, "fail")])
def test_output_minus_intermediate_consumption_may_differ_from_value_added_by_half_a_percent(gdp_case, fraction, status):
    table, profile, gdp = gdp_case
    off = edited(table, shifted("Output", "2023", fraction * gdp["2023"]["gva"]))
    [check] = [c for c in run(gdp_identities, off, profile)[0].checks if c.key == OUTPUT_KEY]
    assert check.status == status
    if status == "pass":
        assert check.detail == f"It holds in all 5 periods (largest gap {abs(fraction) * 100:.3f}%)."
    else:
        assert check.detail == "It fails in 1 of 5 periods." and check.examples == ["2023"]


@pytest.mark.parametrize("fraction, status", [(0.004, "pass"), (0.0049, "pass"), (0.0051, "fail"), (-0.006, "fail")])
def test_value_added_plus_net_taxes_may_differ_from_gdp_by_half_a_percent(gdp_case, fraction, status):
    table, profile, gdp = gdp_case
    off = edited(table, shifted("Net taxes on products", "2022", fraction * gdp["2022"]["gdp"]))
    [check] = [c for c in run(gdp_identities, off, profile)[0].checks if c.key == TAX_KEY]
    assert check.status == status
    assert check.detail == ("It holds in all 5 periods." if status == "pass" else "It fails in 1 of 5 periods.")


def test_at_most_three_failing_periods_are_named_in_the_order_of_the_calendar(gdp_case):
    table, profile, gdp = gdp_case

    def all_years_off(df):
        for year, row in gdp.items():
            shifted("Output", year, 0.02 * row["gva"])(df)

    [check] = [c for c in run(gdp_identities, edited(table, all_years_off), profile)[0].checks if c.key == OUTPUT_KEY]
    assert check.status == "fail" and check.detail == "It fails in 5 of 5 periods." and check.examples == ["2021", "2022", "2023"]


def test_a_year_with_a_missing_figure_is_not_counted_as_passing(gdp_case):
    table, profile, _gdp = gdp_case
    analysis, facts = run(gdp_identities, edited(table, blanked("Output", "2022")), profile)
    checks = checks_by_key(analysis)
    assert checks[OUTPUT_KEY].detail == "It holds in all 4 periods (largest gap 0.000%)." and checks[TAX_KEY].detail == "It holds in all 5 periods."
    analysis, _ = run(gdp_identities, edited(table, blanked("Output")), profile)
    assert list(checks_by_key(analysis)) == [TAX_KEY]                         # nothing can be tested for the first identity: no check at all


def test_the_share_of_taxes_is_given_for_the_latest_year_in_which_both_figures_are_known(gdp_case):
    table, profile, gdp = gdp_case
    for hide in ("GDP at market prices", "Net taxes on products"):
        analysis, [fact] = run(gdp_identities, edited(table, blanked(hide, "2025")), profile)
        assert fact.period == "2024" and fact.data["share"] == pytest.approx(gdp["2024"]["tax"] / gdp["2024"]["gdp"] * 100)
        assert checks_by_key(analysis)[TAX_KEY].detail == "It holds in all 4 periods."
    _, [fact] = run(gdp_identities, edited(table, lambda df: df.__setitem__("value", df["value"].where(~((df["measure"] == "GDP at market prices")
                                                                                                          & (df["period"] == "2025")), 0.0))), profile)
    assert fact.period == "2024"                                              # a GDP of zero cannot be a denominator


def test_without_the_figures_the_identities_need_nothing_is_said(gdp_case):
    table, profile, _gdp = gdp_case
    for gone in ("Output", "Intermediate Consumption", "Gross Value Added"):
        analysis, facts = run(gdp_identities, edited(table, lambda df, g=gone: df[df["measure"] != g]), profile)
        assert analysis.checks == [] and facts == [], gone
    analysis, facts = run(gdp_identities, edited(table, lambda df: df[df["measure"] != "Net taxes on products"]), profile)
    assert list(checks_by_key(analysis)) == [OUTPUT_KEY] and facts == []
    analysis, facts = run(gdp_identities, edited(table, lambda df: df[df["measure"] != "GDP at market prices"]), profile)
    assert list(checks_by_key(analysis)) == [OUTPUT_KEY] and facts == []
    analysis, facts = run(gdp_identities, table, dataclasses.replace(profile, topics=["prices"]))
    assert analysis.checks == [] and facts == []


def test_a_value_added_measure_named_gdp_skips_the_second_identity(gdp_case):
    table, profile, _gdp = gdp_case
    same = edited(table, lambda df: df[df["measure"] != "GDP at market prices"].assign(measure=lambda d: d["measure"].replace({"Gross Value Added": "GDP value added"})))
    analysis, facts = run(gdp_identities, same, profile)
    assert list(checks_by_key(analysis)) == [OUTPUT_KEY] and facts == []


def test_gdp_found_under_another_name_is_still_gdp(gdp_case):
    table, profile, gdp = gdp_case
    renamed = edited(table, lambda df: df.__setitem__("measure", df["measure"].replace({"GDP at market prices": "Gross domestic product"})))
    _, [fact] = run(gdp_identities, renamed, profile)
    assert fact.data["share"] == pytest.approx(gdp["2025"]["tax"] / gdp["2025"]["gdp"] * 100)
    value_added_only = edited(table, lambda df: df.__setitem__("measure", df["measure"].replace({"GDP at market prices": "Gross value added"})))
    analysis, facts = run(gdp_identities, value_added_only, profile)
    assert facts == []                                                        # a "GDP" that is the value added itself is no GDP to compare with


# --- foreign trade ---
def trade_case(n=36, start=(2021, 12)):
    data, truth = demo.make_trade_monthly(n, start)
    table, profile = processed(data)
    return table, profile, truth


@pytest.fixture(scope="module")
def trade36():
    return trade_case()


def month_label(period):
    year, month = period.split("-")
    return f"{['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'][int(month) - 1]} {year}"


def set_measure(measure, values):
    """An edit that replaces a whole row of the long table (one figure per period)."""
    def edit(df):
        for period, value in values.items():
            df.loc[(df["measure"] == measure) & (df["period"] == period), "value"] = value
    return edit


BALANCE_KEY = "trade balance equals exports minus imports"
COVERAGE_KEY = "coverage ratio equals exports divided by imports"


def test_the_latest_month_is_described_with_the_gap_and_the_cover(trade36):
    table, profile, truth = trade36
    analysis, facts = run(trade_balance, table, profile)
    e, i, last = truth["exports"][-1], truth["imports"][-1], truth["periods"][-1]
    headline = facts[0]
    assert (headline.kind, headline.section, headline.subject, headline.importance, headline.period) == ("trade", "headline", "Foreign trade", 0.9, last)
    assert headline.data == {"exports": pytest.approx(e), "imports": pytest.approx(i), "period": last}
    assert headline.text == (f"In {month_label(last)} exports were ALL {e:.2f} billion and imports ALL {i:.2f} billion, a trade deficit of "
                             f"ALL {i - e:.2f} billion. Exports covered {e / i * 100:.0f}% of imports.")


def test_the_year_to_date_is_compared_with_the_year_before(trade36):
    table, profile, truth = trade36
    _, facts = run(trade_balance, table, profile)
    e, i = truth["exports"], truth["imports"]
    ge, gi = (sum(e[-12:]) / sum(e[-24:-12]) - 1) * 100, (sum(i[-12:]) / sum(i[-24:-12]) - 1) * 100
    change = facts[1]
    assert (change.kind, change.section, change.subject, change.importance, change.period) == ("trade", "change", "Foreign trade", 0.8, truth["periods"][-1])
    assert change.data == {"exports_growth": pytest.approx(ge), "imports_growth": pytest.approx(gi)}
    word = lambda x: f"{'rose' if x >= 0 else 'fell'} {abs(x):.1f}%"           # noqa: E731
    assert change.text == (f"In the twelve months to {month_label(truth['periods'][-1])}, exports {word(ge)} and imports {word(gi)}, "
                           "compared with the twelve months before.")
    assert len(facts) == 2


def test_the_comparison_needs_two_full_years(monkeypatch):
    for n, expected in ((23, 1), (24, 2), (25, 2)):
        table, profile, _truth = trade_case(n, (2021, 1))
        assert len(run(trade_balance, table, profile)[1]) == expected, n


def test_the_comparison_is_for_monthly_tables_only(trade36):
    table, profile, _truth = trade36
    assert len(run(trade_balance, table, dataclasses.replace(profile, freq="Q"))[1]) == 1


def test_no_comparison_when_the_year_before_is_zero_or_any_figure_in_the_two_years_is_missing(trade36):
    table, profile, truth = trade36
    periods = truth["periods"]
    zero = edited(table, set_measure("Exports", dict.fromkeys(periods[-24:-12], 0.0)))
    assert len(run(trade_balance, zero, profile)[1]) == 1
    zero_imports = edited(table, set_measure("Imports", dict.fromkeys(periods[-24:-12], 0.0)))
    assert len(run(trade_balance, zero_imports, profile)[1]) == 1
    for position in (-24, -13, -12, -2):
        for measure in ("Exports", "Imports"):
            gap = edited(table, set_measure(measure, {periods[position]: np.nan}))
            assert len(run(trade_balance, gap, profile)[1]) == 1, (measure, position)
    one_zero = edited(table, set_measure("Exports", {periods[-20]: 0.0}))
    assert len(run(trade_balance, one_zero, profile)[1]) == 2                    # one month of nothing does not make the base nothing


def test_a_surplus_is_called_a_surplus(trade36):
    table, profile, truth = trade36
    last, i = truth["periods"][-1], truth["imports"][-1]
    surplus = edited(table, set_measure("Exports", {last: i + 10.37}))
    [headline, *_] = run(trade_balance, surplus, profile)[1]
    assert "a trade surplus of ALL 10.37 billion" in headline.text and "trade deficit" not in headline.text
    assert f"Exports covered {(i + 10.37) / i * 100:.0f}% of imports." in headline.text
    even = edited(table, set_measure("Exports", {last: i}))
    assert "a trade surplus of " in run(trade_balance, even, profile)[1][0].text and "deficit" not in run(trade_balance, even, profile)[1][0].text


def test_the_latest_month_with_both_flows_known_and_a_real_import_figure_is_described(trade36):
    table, profile, truth = trade36
    before = truth["periods"][-2]
    for edit in (set_measure("Imports", {truth["periods"][-1]: np.nan}), set_measure("Exports", {truth["periods"][-1]: np.nan}),
                 set_measure("Imports", {truth["periods"][-1]: 0.0})):
        head = run(trade_balance, edited(table, edit), profile)[1][0]
        assert head.period == before and head.data["exports"] == pytest.approx(truth["exports"][-2])
        assert head.text.startswith(f"In {month_label(before)} exports were ")
    nothing = edited(table, lambda df: df.__setitem__("value", np.nan))
    assert run(trade_balance, nothing, profile)[1] == []


def test_balance_tolerance_is_half_a_percent_of_the_median_import(trade36):
    table, profile, truth = trade36
    tolerance = 0.005 * float(np.median(truth["imports"]))
    period = truth["periods"][10]
    balance = dict(zip(truth["periods"], [a - b for a, b in zip(truth["exports"], truth["imports"])]))
    for factor, status in ((0.9, "pass"), (-0.9, "pass"), (1.1, "fail"), (-1.1, "fail")):
        off = edited(table, set_measure("Trade balance", {period: balance[period] + factor * tolerance}))
        check = checks_by_key(run(trade_balance, off, profile)[0])[BALANCE_KEY]
        assert check.status == status and check.name == "Trade balance equals exports minus imports", factor
        assert check.detail == ("It holds in all 36 periods." if status == "pass" else "It fails in 1 of 36 periods.")


def test_with_no_imports_to_measure_against_the_tolerance_is_a_millionth(trade36):
    table, profile, truth = trade36
    periods = truth["periods"]
    def no_imports(df):
        set_measure("Imports", dict.fromkeys(periods, 0.0))(df)
        set_measure("Trade balance", dict(zip(periods, truth["exports"])))(df)

    nothing_imported = edited(table, no_imports)
    assert checks_by_key(run(trade_balance, nothing_imported, profile)[0])[BALANCE_KEY].status == "pass"
    for amount, status in ((5e-7, "pass"), (2e-6, "fail")):
        off = edited(nothing_imported, set_measure("Trade balance", {periods[3]: truth["exports"][3] + amount}))
        assert checks_by_key(run(trade_balance, off, profile)[0])[BALANCE_KEY].status == status, amount


def test_the_coverage_ratio_may_differ_by_half_a_point(trade36):
    table, profile, truth = trade36
    period = truth["periods"][7]
    ratio = 100 * truth["exports"][7] / truth["imports"][7]
    for amount, status in ((0.45, "pass"), (-0.45, "pass"), (0.55, "warn"), (-0.55, "warn")):
        off = edited(table, set_measure("Coverage ratio (%)", {period: ratio + amount}))
        check = checks_by_key(run(trade_balance, off, profile)[0])[COVERAGE_KEY]
        assert check.status == status and check.name == "Coverage ratio equals exports divided by imports", amount
        assert check.detail == ("It holds in all 36 periods." if status == "pass" else "It differs by more than 0.5 pp in 1 periods.")


def test_months_without_imports_cannot_be_tested_for_coverage(trade36):
    table, profile, truth = trade36
    zero = edited(table, set_measure("Imports", {truth["periods"][4]: 0.0}))
    check = checks_by_key(run(trade_balance, zero, profile)[0])[COVERAGE_KEY]
    assert check.status == "pass" and check.detail == "It holds in all 35 periods."


def test_the_balance_and_coverage_rows_are_optional_and_found_under_other_names(trade36):
    table, profile, _truth = trade36
    bare = edited(table, lambda df: df[df["measure"].isin(["Exports", "Imports"])])
    analysis, facts = run(trade_balance, bare, profile)
    assert analysis.checks == [] and len(facts) == 2
    deficit = edited(table, lambda df: df.__setitem__("measure", df["measure"].replace({"Trade balance": "Trade deficit"})))
    assert BALANCE_KEY in checks_by_key(run(trade_balance, deficit, profile)[0])
    only_balance = edited(table, lambda df: df[df["measure"] != "Coverage ratio (%)"])
    assert list(checks_by_key(run(trade_balance, only_balance, profile)[0])) == [BALANCE_KEY]
    only_cover = edited(table, lambda df: df[df["measure"] != "Trade balance"])
    assert list(checks_by_key(run(trade_balance, only_cover, profile)[0])) == [COVERAGE_KEY]


def test_without_both_flows_there_is_nothing_to_say(trade36):
    table, profile, _truth = trade36
    for gone in ("Exports", "Imports"):
        analysis, facts = run(trade_balance, edited(table, lambda df, g=gone: df[df["measure"] != g]), profile)
        assert analysis.checks == [] and facts == [], gone
    renamed = edited(table, lambda df: df.__setitem__("measure", df["measure"].replace({"Exports": "Goods sold", "Imports": "Goods bought"})))
    assert run(trade_balance, renamed, profile) == (SimpleNamespace(extras={}, checks=[], warnings=[]), [])
    analysis, facts = run(trade_balance, table, dataclasses.replace(profile, topics=["prices"]))
    assert analysis.checks == [] and facts == []


def test_the_flows_may_also_be_the_values_of_a_category_column(trade36):
    table, profile, truth = trade36

    def as_category(df):
        out = df.rename(columns={"measure": "flow"})
        out["measure"] = "Foreign trade"
        return out

    moved = edited(table, as_category)
    flow = DimInfo("flow", "flow", "Flow", 4, [])
    other = dataclasses.replace(profile, dims=[flow], measures=[MeasureInfo("Foreign trade", "billion ALL", "level", True, unit_code="ALL")])
    analysis, facts = run(trade_balance, moved, other)
    assert set(checks_by_key(analysis)) == {BALANCE_KEY, COVERAGE_KEY} and all(c.status == "pass" for c in analysis.checks)
    assert facts[0].data["exports"] == pytest.approx(truth["exports"][-1]) and facts[0].period == truth["periods"][-1]
    neither = dataclasses.replace(other, dims=[])
    assert run(trade_balance, moved, neither)[1] == []


# --- population: the age structure ---
@pytest.fixture(scope="module")
def population_case():
    data, truth = demo.make_population()
    table, profile = processed(data)
    return table, profile, truth


def age_shares(truth, year):
    young = work = old = 0
    for age in demo.AGE_GROUPS:
        total = truth["rows"][(year, age)][2]
        low = int(age.split("-")[0].rstrip("+"))
        high = None if age.endswith("+") else int(age.split("-")[1])
        if high is not None and high <= 14:
            young += total
        elif low >= 15 and high is not None and high <= 64:
            work += total
        elif low >= 65:
            old += total
    everyone = young + work + old
    return {"young": young / everyone * 100, "work": work / everyone * 100, "old": old / everyone * 100, "old_dep": old / work * 100,
            "young_dep": young / work * 100, "aging": old / young * 100, "total": float(everyone)}


def set_ages(year, ages, value):
    def edit(df):
        df.loc[(df["period"] == year) & df["age_group"].isin(ages), "value"] = value
    return edit


YOUNG, WORKING, OLD = ["0-4", "5-9", "10-14"], [f"{a}-{a + 4}" for a in range(15, 65, 5)], [f"{a}-{a + 4}" for a in range(65, 85, 5)] + ["85+"]


def test_age_shares_and_dependency_ratios_follow_from_the_stated_totals(population_case):
    table, profile, truth = population_case
    analysis, facts = run(age_structure, table, profile)
    last = age_shares(truth, 2026)
    got = analysis.extras["age_structure"]
    assert got == {key: pytest.approx(value) for key, value in last.items()}
    [composition, change] = facts
    assert (composition.kind, composition.section, composition.subject, composition.importance, composition.period) == (
        "age_structure", "composition", "Population", 0.9, "2026")
    assert composition.data == got
    assert composition.text == (f"In 2026, {last['young']:.0f}% of the population is under 15, {last['work']:.0f}% is of working age (15 to 64) and "
                                f"{last['old']:.0f}% is 65 or older. For every 100 people of working age there are {last['old_dep']:.0f} aged 65 and over, "
                                f"and for every 100 children there are {last['aging']:.0f} older people.")
    first = age_shares(truth, 2024)
    d_old, d_young = last["old"] - first["old"], last["young"] - first["young"]
    assert (change.kind, change.section, change.subject, change.importance, change.period) == ("age_structure", "change", "Population", 0.78, "2026")
    assert change.data == {"first": {k: pytest.approx(v) for k, v in first.items()}, "last": {k: pytest.approx(v) for k, v in last.items()}}
    words = lambda d: "risen" if d > 0 else "fallen"                                    # noqa: E731
    assert change.text == (f"Since 2024, the share aged 65 and over has {words(d_old)} by {abs(d_old):.1f} pp, and the share under 15 has "
                           f"{words(d_young)} by {abs(d_young):.1f} pp.")


def test_a_share_that_grew_is_said_to_have_risen_and_one_that_fell_to_have_fallen(population_case):
    table, profile, truth = population_case
    older = edited(table, set_ages("2026", OLD, 10 ** 6))                                  # far more old people than in 2024
    change = run(age_structure, older, profile)[1][1]
    assert "share aged 65 and over has risen by" in change.text and "share under 15 has fallen by" in change.text
    younger = edited(table, set_ages("2026", YOUNG, 10 ** 6))
    change = run(age_structure, younger, profile)[1][1]
    assert "share aged 65 and over has fallen by" in change.text and "share under 15 has risen by" in change.text


def test_one_year_gives_the_structure_but_no_change():
    data, truth = demo.make_population(years=(2026,))
    table, profile = processed(data)
    [fact] = run(age_structure, table, profile)[1]
    assert fact.section == "composition" and fact.data == {k: pytest.approx(v) for k, v in age_shares(truth, 2026).items()}


def test_no_change_is_reported_when_the_first_year_cannot_be_read(population_case):
    table, profile, _truth = population_case
    other_labels = edited(table, lambda df: df.__setitem__("age_group", df["age_group"].where(~((df["period"] == "2024") & (df["age_group"] == "0-4")), "all kids")))
    facts = run(age_structure, other_labels, profile)[1]
    assert [f.section for f in facts] == ["composition"]
    gap = edited(table, set_ages("2024", ["30-34"], np.nan))
    assert [f.section for f in run(age_structure, gap, profile)[1]] == ["composition"]


def test_no_age_structure_when_a_group_is_not_an_age_or_has_no_figure(population_case):
    table, profile, _truth = population_case
    bad_label = edited(table, lambda df: df.__setitem__("age_group", df["age_group"].where(~((df["period"] == "2026") & (df["age_group"] == "0-4")), "unknown")))
    missing = edited(table, set_ages("2026", ["30-34"], np.nan))
    for broken in (bad_label, missing):
        analysis, facts = run(age_structure, broken, profile)
        assert facts == [] and analysis.extras == {}


def test_at_least_six_age_groups_are_needed(population_case):
    table, profile, _truth = population_case
    few = edited(table, lambda df: df[df["age_group"].isin(["0-4", "5-9", "10-14", "15-19", "65-69", "Total"])])
    assert run(age_structure, few, profile)[1] == []                                   # five groups and the total
    six = edited(table, lambda df: df[df["age_group"].isin(["0-4", "5-9", "10-14", "15-19", "65-69", "70-74", "Total"])])
    assert len(run(age_structure, six, profile)[1]) == 2


def test_nothing_is_said_when_there_is_nobody_of_working_age_or_nobody_at_all(population_case):
    table, profile, truth = population_case
    no_workers = edited(table, set_ages("2026", WORKING, 0))
    analysis, facts = run(age_structure, no_workers, profile)
    assert facts == [] and analysis.extras == {}
    rest = sum(truth["rows"][(2026, age)][2] for age in demo.AGE_GROUPS if age not in YOUNG)
    cancelled = edited(table, lambda df: (set_ages("2026", ["0-4"], -float(rest))(df), set_ages("2026", ["5-9", "10-14"], 0.0)(df))[0])
    assert run(age_structure, cancelled, profile)[1] == []                             # the three groups add up to zero: no shares can be given
    negative = edited(table, set_ages("2026", YOUNG + WORKING + OLD, -1.0))
    assert run(age_structure, negative, profile)[1] == []


def test_without_children_the_ageing_index_is_not_available(population_case):
    table, profile, _truth = population_case
    analysis, facts = run(age_structure, edited(table, set_ages("2026", YOUNG, 0)), profile)
    assert math.isnan(analysis.extras["age_structure"]["aging"]) and analysis.extras["age_structure"]["young"] == 0
    assert facts[0].text.endswith("and for every 100 children there are n/a older people.")


def test_the_same_age_group_written_twice_is_counted_once_per_row_and_added(population_case):
    table, profile, truth = population_case
    twice = edited(table, lambda df: pd.concat([df, df[(df["age_group"] == "85+") & (df["period"] == "2026")]], ignore_index=True))
    got = run(age_structure, twice, profile)[0].extras["age_structure"]
    assert got["total"] == pytest.approx(age_shares(truth, 2026)["total"] + truth["rows"][(2026, "85+")][2])


def test_only_the_first_measure_of_a_table_with_several_is_used(population_case):
    table, profile, truth = population_case
    second = table.df.copy()
    second["measure"] = "Another count"
    second["value"] = second["value"] * 3
    both = dataclasses.replace(table, df=pd.concat([table.df, second], ignore_index=True))
    got = run(age_structure, both, profile)[0].extras["age_structure"]
    assert got["total"] == pytest.approx(age_shares(truth, 2026)["total"])


def test_other_tables_get_no_age_structure(population_case):
    table, profile, _truth = population_case
    for changed in (dataclasses.replace(profile, topics=["labour"]), dataclasses.replace(profile, dims=[d for d in profile.dims if d.role != "age_group"]),
                    dataclasses.replace(profile, last_period=None)):
        analysis, facts = run(age_structure, table, changed)
        assert facts == [] and analysis.extras == {}
    assert run(age_structure, dataclasses.replace(table, df=table.df.iloc[0:0]), profile)[1] == []


# --- unemployment: young people against everybody ---
@pytest.fixture(scope="module")
def lfs_case():
    data, truth = demo.make_lfs_quarterly(20, (2021, 1))
    table, profile = processed(data)
    return table, profile, truth["rows"]


def test_the_rate_for_ages_15_to_29_is_compared_with_the_rate_for_everybody_over_15(lfs_case):
    table, profile, rows = lfs_case
    youth, base = rows[("15-29 vjeç", "Total")][-1], rows[("15 vjeç e lart", "Total")][-1]
    [fact] = run(youth_unemployment, table, profile)[1]
    assert (fact.kind, fact.section, fact.subject, fact.importance, fact.period) == ("youth", "comparison", "Unemployment rate", 0.82, "2025-Q4")
    assert fact.data == {"youth": pytest.approx(youth), "base": pytest.approx(base)}
    assert fact.text == f"In Q4 2025 the rate for ages 15 to 29 ({youth:.1f}%) is {youth / base:.1f} times the rate for ages 15 and over ({base:.1f}%)."


def test_the_first_of_the_two_possible_comparison_groups_in_the_table_is_used(lfs_case):
    table, profile, rows = lfs_case
    order = {"15-64 years": 0, "15-29 years": 1, "15 years and over": 2, "30-64 years": 3}
    reordered = edited(table, lambda df: df.sort_values("age_group", key=lambda col: col.map(order), kind="stable").reset_index(drop=True))
    [fact] = run(youth_unemployment, reordered, profile)[1]
    assert fact.data["base"] == pytest.approx(rows[("15-64 vjeç", "Total")][-1]) and "ages 15-64 (" in fact.text
    only_working_ages = edited(table, lambda df: df[df["age_group"] != "15 years and over"])
    [fact] = run(youth_unemployment, only_working_ages, profile)[1]
    assert fact.data["base"] == pytest.approx(rows[("15-64 vjeç", "Total")][-1])


def lfs_edit(age, value, period="2025-Q4"):
    def edit(df):
        df.loc[(df["age_group"] == age) & (df["period"] == period), "value"] = value
    return edit


def test_no_comparison_without_two_usable_rates_and_a_positive_base(lfs_case):
    table, profile, _rows = lfs_case
    for broken in (edited(table, lfs_edit("15-29 years", np.nan)), edited(table, lfs_edit("15 years and over", np.nan)),
                   edited(table, lfs_edit("15 years and over", 0.0)), edited(table, lfs_edit("15 years and over", -1.0)),
                   edited(table, lambda df: df[df["age_group"] != "15-29 years"]),
                   edited(table, lambda df: df[~df["age_group"].isin(["15 years and over", "15-64 years"])])):
        assert run(youth_unemployment, broken, profile)[1] == []
    assert len(run(youth_unemployment, edited(table, lfs_edit("15 years and over", 0.01)), profile)[1]) == 1
    older_gap = edited(table, lfs_edit("15 years and over", np.nan, "2025-Q3"))
    assert len(run(youth_unemployment, older_gap, profile)[1]) == 1                    # only the latest period matters


def test_only_unemployment_rates_in_percent_by_age_are_compared(lfs_case):
    table, profile, _rows = lfs_case
    for changed in (dataclasses.replace(profile, unit="persons"), dataclasses.replace(profile, topics=["population"]),
                    dataclasses.replace(profile, last_period=None), dataclasses.replace(profile, dims=[d for d in profile.dims if d.role != "age_group"])):
        assert run(youth_unemployment, table, changed)[1] == []


# --- wages: the gender pay gap ---
@pytest.fixture(scope="module")
def wages_case():
    table, profile = processed(demo.make_cross_section()[0])
    return table, profile


PAY = {"Agriculture": (54000, 48500), "Industry": (68000, 57000), "Trade": (64200, 58800), "Transport": (72000, 66000), "Education": (76000, 80500)}


def pay_gaps(pay):
    return {name: (m - f) / m * 100 for name, (m, f) in pay.items() if m > 0}


def pay(activity, sex, value):
    def edit(df):
        df.loc[(df["activity"] == activity) & (df["sex"] == sex), "value"] = value
    return edit


def median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def test_the_pay_gap_is_the_difference_between_men_and_women_as_a_share_of_the_pay_of_men(wages_case):
    table, profile = wages_case
    others = [Fact("latest", "headline", "x", "kept"), Fact("gap", "comparison", "y", "the general comparison of women and men")]
    analysis, facts = run(gender_pay_gap, table, profile, others)
    gaps = pay_gaps(PAY)
    assert [f.text for f in facts][0] == "kept" and len(facts) == 2                      # the general comparison was replaced
    fact = facts[-1]
    assert (fact.kind, fact.section, fact.subject, fact.importance, fact.period) == ("pay_gap", "headline", "Gender pay gap", 0.92, "2023")
    assert fact.data == {"median_gap": pytest.approx(median(gaps.values())), "worse": 4, "n": 5, "widest": "Industry"}
    assert fact.text == (f"In 2023 women earn less than men in 4 of 5 categories by economic activity. The median gender pay gap is "
                         f"{median(gaps.values()):.1f}%, widest in Industry ({gaps['Industry']:.1f}%). "
                         f"In Education women earn {abs(gaps['Education']):.1f}% more than men.")
    series = analysis.extras["pay_gap"]
    assert dict(series) == pytest.approx(gaps) and list(series.values) == sorted(series.values, reverse=True)


def test_a_category_where_women_earn_slightly_less_still_counts_as_one_where_they_earn_less(wages_case):
    table, profile = wages_case
    tiny = edited(table, pay("Transport", "Females", 72000 * 0.995))                     # a gap of half a percent
    assert run(gender_pay_gap, tiny, profile)[1][-1].data["worse"] == 4
    equal = edited(table, pay("Transport", "Females", 72000))
    fact = run(gender_pay_gap, equal, profile)[1][-1]
    assert fact.data["worse"] == 3 and "Transport" not in fact.text                      # equal pay is neither less nor more


def test_the_sentence_about_women_earning_more_is_left_out_when_they_nowhere_do(wages_case):
    table, profile = wages_case
    fact = run(gender_pay_gap, edited(table, pay("Education", "Females", 70000)), profile)[1][-1]
    assert "more than men" not in fact.text and fact.data["worse"] == 5
    nobody_ahead = run(gender_pay_gap, edited(table, pay("Education", "Females", 76000)), profile)[1][-1]
    assert "more than men" not in nobody_ahead.text and nobody_ahead.data["worse"] == 4          # equal pay is not an advantage
    two_more = edited(table, pay("Trade", "Females", 70000))
    fact = run(gender_pay_gap, two_more, profile)[1][-1]
    trade_gap = (64200 - 70000) / 64200 * 100
    assert fact.data["worse"] == 3 and f"In Trade women earn {abs(trade_gap):.1f}% more than men." in fact.text   # only the biggest advantage is named
    assert "In Education" not in fact.text


def test_three_categories_with_both_figures_are_enough_and_two_are_not(wages_case):
    table, profile = wages_case
    three = edited(table, lambda df: df[df["activity"].isin(["Agriculture", "Industry", "Trade", "Construction"])])
    fact = run(gender_pay_gap, three, profile)[1][-1]
    assert fact.data["n"] == 3 and fact.data["worse"] == 3                               # Construction has no figure for women
    two = edited(table, lambda df: df[df["activity"].isin(["Agriculture", "Industry", "Construction"])])
    assert run(gender_pay_gap, two, profile)[1] == []


def test_a_category_in_which_men_are_paid_nothing_has_no_gap(wages_case):
    table, profile = wages_case
    fact = run(gender_pay_gap, edited(table, pay("Agriculture", "Males", 0)), profile)[1][-1]
    assert fact.data["n"] == 4 and fact.data["widest"] == "Industry"


def test_a_dimension_that_only_holds_codes_is_not_a_category(wages_case):
    table, profile = wages_case
    codes = DimInfo("activity_code", "activity_code", "Code", 6, [])
    with_codes = edited(table, lambda df: df.__setitem__("activity_code", "x"))
    fact = run(gender_pay_gap, with_codes, dataclasses.replace(profile, dims=[codes, *profile.dims]))[1][-1]
    assert fact.data["n"] == 5 and fact.data["widest"] == "Industry"
    other_code = DimInfo("sector", "code", "Code", 6, [])
    fact = run(gender_pay_gap, edited(table, lambda df: df.__setitem__("sector", "x")), dataclasses.replace(profile, dims=[other_code, *profile.dims]))[1][-1]
    assert fact.data["n"] == 5


def test_with_no_category_the_single_gap_is_described_as_below_or_above(wages_case):
    table, profile = wages_case
    only_sex = dataclasses.replace(profile, dims=[d for d in profile.dims if d.role == "sex"])
    for activity, below in (("Industry", True), ("Education", False)):
        single = edited(table, lambda df, a=activity: df[df["activity"] == a])
        gap = pay_gaps(PAY)[activity]
        analysis, [fact] = run(gender_pay_gap, single, only_sex)
        assert fact.data == {"gap_pct": pytest.approx(gap)} and fact.importance == 0.92 and fact.period == "2023"
        sign = "+" if gap > 0 else "−"
        assert fact.text == (f"In 2023 women's average pay is {abs(gap):.1f}% {'below' if below else 'above'} men's (gender pay gap: {sign}{abs(gap):.1f}%).")
        assert analysis.extras == {}
    replaced = [Fact("gap", "comparison", "y", "general")]
    run(gender_pay_gap, edited(table, lambda df: df[df["activity"] == "Industry"]), only_sex, replaced)
    assert [f.kind for f in replaced] == ["pay_gap"]


def test_without_a_category_the_gap_needs_one_figure_per_sex_and_positive_pay_for_men(wages_case):
    table, profile = wages_case
    only_sex = dataclasses.replace(profile, dims=[d for d in profile.dims if d.role == "sex"])
    assert run(gender_pay_gap, table, only_sex)[1] == []                                    # five figures for each sex
    for activity, edit in (("Construction", None), ("Industry", pay("Industry", "Males", 0)), ("Industry", pay("Industry", "Females", np.nan))):
        one = edited(table, lambda df, a=activity: df[df["activity"] == a])
        if edit:
            one = edited(one, edit)
        assert run(gender_pay_gap, one, only_sex)[1] == [], (activity, edit)


def test_a_table_without_a_female_or_male_column_or_that_is_not_about_wages_gets_no_pay_gap(wages_case):
    table, profile = wages_case
    for broken in (edited(table, lambda df: df.__setitem__("sex", df["sex"].replace({"Females": "Others"}))),
                   edited(table, lambda df: df.__setitem__("sex", df["sex"].replace({"Males": "Others"}))),
                   edited(table, lambda df: df[df["sex"] != "Females"]),
                   edited(table, lambda df: df.__setitem__("value", df["value"].where(df["sex"] != "Females")))):
        assert run(gender_pay_gap, broken, profile)[1] == []
    for changed in (dataclasses.replace(profile, topics=["prices"]), dataclasses.replace(profile, unit="%"),
                    dataclasses.replace(profile, unit="share of pay, %"), dataclasses.replace(profile, last_period=None),
                    dataclasses.replace(profile, dims=[d for d in profile.dims if d.role != "sex"])):
        assert run(gender_pay_gap, table, changed)[1] == []
    in_all = dataclasses.replace(profile, unit="ALL million")
    assert len(run(gender_pay_gap, table, in_all)[1]) == 1


def test_the_other_names_for_women_and_men_are_understood(wages_case):
    table, profile = wages_case
    for female, male in (("Female", "Male"), ("Women", "Men")):
        renamed = edited(table, lambda df, f=female, m=male: df.__setitem__("sex", df["sex"].replace({"Females": f, "Males": m})))
        assert run(gender_pay_gap, renamed, profile)[1][-1].data["n"] == 5


def test_the_pay_gap_is_worded_in_albanian_when_albanian_is_switched_on(wages_case):
    table, profile = wages_case
    analysis = SimpleNamespace(extras={}, checks=[], warnings=[])
    facts = []
    with i18n.using("sq"):
        gender_pay_gap(table, profile, analysis, facts)
    assert facts[-1].text.startswith("Në 2023") and "women earn" not in facts[-1].text
