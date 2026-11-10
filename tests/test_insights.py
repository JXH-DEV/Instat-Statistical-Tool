"""The sentences of the findings, one scenario at a time. Each series is built so that every number in the sentence can be worked out by
hand (a line that rises by 2 a month, a rate that jumps from 5 to 9), and the expected wording is the complete sentence."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from instatkit.analysis import crosssection as cs
from instatkit.analysis.insights import (
    Ctx,
    _change_text,
    _delta_phrase,
    composition_fact,
    gap_fact,
    growth_fact,
    movers_fact,
    ranking_fact,
    series_facts,
    short_measure,
)
from instatkit.analysis.series import compute_series_stats
from instatkit.semantics.periods import make_month, make_quarter
from instatkit.semantics.units import UnitInfo

MILLION_ALL = Ctx(UnitInfo(unit="ALL", scale=1e6, scale_label="million"), "amount", "M")
RATE = Ctx(UnitInfo(unit="%"), "rate", "M")


def months(n, start=(2020, 1)):
    y, m = start
    out = []
    for _ in range(n):
        out.append(make_month(y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def facts_of(values, ctx=MILLION_ALL, *, periods=None, headline=True, kind="level"):
    values = np.asarray(values, dtype=float)
    st = compute_series_stats(periods or months(len(values)), values, kind=kind)
    out: dict[str, list] = {}
    for f in series_facts("Exports", st, ctx, headline=headline):
        out.setdefault(f.kind, []).append(f)
    return out


def sentence(facts, kind):
    return facts[kind][0].text


LINE = 100 + 2.0 * np.arange(24)                                  # 100, 102, ... 146: December 2021 is the last month


# --- the latest value and how it changed ---
def test_the_latest_value_names_its_unit_scale_and_period():
    f = facts_of(LINE)
    assert sentence(f, "latest") == "Exports: ALL 146 million in December 2021."
    assert f["latest"][0].data == {"value": 146.0, "period": "2021-12"}


def test_the_change_is_given_on_the_previous_period_and_on_a_year_earlier():
    assert sentence(facts_of(LINE), "change") == "Exports: up 1.4% on November 2021 and up 19.7% on December 2020."       # 146 / 144 and 146 / 122
    falling = facts_of(LINE[::-1])
    assert sentence(falling, "change") == "Exports: down 2.0% on November 2021 and down 19.4% on December 2020."          # 100 / 102 and 100 / 124


def test_a_rate_is_described_in_points_and_a_steady_rise_is_not_called_unusual():
    f = facts_of(8 + 0.1 * np.arange(24), RATE, kind="rate")
    assert sentence(f, "latest") == "Exports: 10.3% in December 2021."
    assert sentence(f, "change") == "Exports: up 0.1 pp on November 2021 and up 1.2 pp on December 2020."
    assert sentence(f, "trend") == "From January 2020 to December 2021 the series has risen by about 1.20 pp a year."
    assert "anomaly" not in f and "shift" not in f                                           # every month rises by the same 0.1: nothing stands out


def test_a_steady_rise_in_amounts_has_no_unusual_month_and_no_change_of_pattern():
    f = facts_of(LINE)
    assert sorted(f) == ["change", "extreme", "latest", "trend"]


def test_nothing_that_did_not_move_is_reported_as_movement():
    f = facts_of([100.0] * 24)
    assert sentence(f, "latest") == "Exports: ALL 100 million in December 2021."
    assert sentence(f, "change") == "Exports: unchanged on November 2021."
    assert sentence(f, "trend") == "There is no clear long-term trend between January 2020 and December 2021."
    assert sorted(f) == ["change", "latest", "trend"]                                         # a constant series is not "the highest" of anything


def test_up_on_one_period_and_unchanged_on_the_other_are_both_said():
    v = np.full(24, 100.0)
    v[11] = v[23] = 101.5
    assert sentence(facts_of(v), "change") == "Exports: up 1.5% on November 2021 and unchanged on December 2020."


def test_a_series_that_reaches_zero_is_described_in_its_own_unit_not_in_percent():
    values = [-6.0, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 6, 7]
    f = facts_of(values)
    assert sentence(f, "change") == "Exports: up ALL 1 million on December 2020 and up ALL 13 million on January 2020."
    slope = np.polyfit(np.arange(13), values, 1)[0]
    assert sentence(f, "trend") == f"From January 2020 to January 2021 the series has risen by about ALL {slope * 12:.2f} million a year."


def test_quarters_are_compared_with_the_quarter_before_and_the_same_quarter_a_year_earlier():
    quarters = [make_quarter(2020 + k // 4, k % 4 + 1) for k in range(8)]
    ctx = Ctx(UnitInfo(unit="persons"), "amount", "Q")
    f = facts_of([10, 11, 12, 13, 14, 15, 16, 18], ctx, periods=quarters)
    assert sentence(f, "latest") == "Exports: 18 people in Q4 2021."
    assert sentence(f, "change") == "Exports: up 12.5% on Q3 2021 and up 38.5% on Q4 2020."                              # 18 / 16 and 18 / 13


def test_an_index_names_its_base_and_shows_one_decimal():
    index = lambda base, value: Ctx(UnitInfo(unit="index", base_period=base, base_value=value), "index", "M")        # noqa: E731
    assert sentence(facts_of(LINE, index("2015", 100.0)), "latest") == "Exports: 146.0 in December 2021 (base 2015 = 100)."
    assert sentence(facts_of(LINE, index("2015", 99.5)), "latest") == "Exports: 146.0 in December 2021 (base 2015 = 99.5)."
    assert sentence(facts_of(LINE, index("2020-12", 100.0)), "latest") == "Exports: 146.0 in December 2021 (base December 2020 = 100)."
    assert sentence(facts_of(LINE, Ctx(UnitInfo(unit="index"), "index", "M")), "latest") == "Exports: 146.0 in December 2021."


def test_a_change_smaller_than_the_rounding_is_unchanged():
    pp, pct = Ctx(UnitInfo(unit="%"), "rate", "M"), MILLION_ALL
    assert _delta_phrase(pp, 0.0499, None) == ("unchanged", True)
    assert _delta_phrase(pp, 0.05, None) == ("up 0.1 pp", False)
    assert _delta_phrase(pp, -0.05, None) == ("down 0.1 pp", False)
    assert _delta_phrase(pct, 1.0, 0.0499) == ("unchanged", True)
    assert _delta_phrase(pct, 1.0, 0.05)[1] is False and _delta_phrase(pct, 1.0, 0.05)[0].startswith("up")
    assert _delta_phrase(pct, 1.0, -12.5) == ("down 12.5%", False)
    assert _delta_phrase(pct, 1.0, None) is None and _delta_phrase(pct, None, 1.0) is None
    assert _delta_phrase(pct, 0.0, None, allow_pct=False) == ("unchanged", True)
    assert _delta_phrase(pct, 2.0, None, allow_pct=False) == ("up ALL 2 million", False)
    assert _delta_phrase(pct, -2.0, None, allow_pct=False) == ("down ALL 2 million", False)


def test_a_change_is_written_in_points_percent_or_the_unit_of_the_series():
    levels = compute_series_stats(months(10), np.arange(1.0, 11))
    zero = compute_series_stats(months(10), np.arange(-4.0, 6))
    assert _change_text(RATE, levels, 1.3) == "+1.3 pp"
    assert _change_text(RATE, levels, -1.5) == "−1.5 pp" and _change_text(RATE, levels, -1.5, signed=False) == "−1.5 pp"
    assert _change_text(MILLION_ALL, levels, 12.5) == "+12.5%" and _change_text(MILLION_ALL, levels, -12.5) == "−12.5%"
    assert _change_text(MILLION_ALL, zero, 2.0) == "+ALL 2 million" and _change_text(MILLION_ALL, zero, -2.0) == "−ALL 2 million"
    assert _change_text(MILLION_ALL, zero, 2.0, signed=False) == "ALL 2 million" and _change_text(MILLION_ALL, zero, 0) == "ALL 0"


# --- where the latest value stands in the history ---
def test_a_record_is_said_with_the_number_of_observations_and_where_they_begin():
    assert sentence(facts_of(LINE), "extreme") == "The latest value is the highest of all 24 observations, going back to January 2020."
    assert sentence(facts_of(20.0 - np.arange(10)), "extreme") == "The latest value is the lowest of all 10 observations, going back to January 2020."


def test_a_value_that_is_not_a_record_is_the_highest_or_lowest_since_a_period():
    assert sentence(facts_of([5.0, 4, 1, 6, 6, 5, 5, 4, 4, 3, 2]), "extreme") == "The latest value is the lowest since March 2020."
    assert sentence(facts_of([1.0, 2, 9, 3, 3, 4, 4, 5, 5, 6, 7]), "extreme") == "The latest value is the highest since March 2020."


def test_nothing_is_said_about_the_history_of_a_short_series():
    assert "extreme" not in facts_of([1.0, 2, 3, 4, 5, 6, 7])


# --- the trend ---
def test_a_rising_level_is_given_as_a_percentage_a_year_from_a_log_linear_fit():
    slope = np.polyfit(np.arange(24), np.log(LINE), 1)[0]
    expected = (math.exp(slope * 12) - 1) * 100
    assert sentence(facts_of(LINE), "trend") == f"From January 2020 to December 2021 the series has risen by about {expected:.1f}% a year."
    slope = np.polyfit(np.arange(14), np.log(20.0 - np.arange(14)), 1)[0]
    assert sentence(facts_of(20.0 - np.arange(14)), "trend") == (
        f"From January 2020 to February 2021 the series has fallen by about {abs((math.exp(slope * 12) - 1) * 100):.1f}% a year.")


def test_a_rate_per_year_needs_a_year_of_observations():
    """Ten months stretched to twelve would say "risen by about 22 % a year" of a change that was seen for less than a year."""
    ten = facts_of(100 + 2.0 * np.arange(10))
    assert sentence(ten, "trend") == "Over the whole series the trend is rising."
    assert "a year" in sentence(facts_of(100 + 2.0 * np.arange(13)), "trend")                       # 12 intervals: a full year
    assert sentence(facts_of(100 + 2.0 * np.arange(12)), "trend") == "Over the whole series the trend is rising."     # 11 intervals


def test_a_long_rise_adds_the_compound_rate_and_a_recent_fall_is_mentioned():
    v = np.r_[100 + np.arange(30.0), 129 - np.arange(1, 11) * 1.5]
    text = sentence(facts_of(v), "trend")
    assert text.startswith("From January 2020 to April 2023 the series has risen by about ")
    years = (make_month(2023, 4).start - make_month(2020, 1).start).days / 365.25
    assert f"The compound annual rate is {((v[-1] / v[0]) ** (1 / years) - 1) * 100:.1f}%." in text
    assert text.endswith("Over the last 12 observations, though, it has fallen.")


def test_no_trend_is_claimed_for_a_series_that_wobbles_around_a_level():
    v = 100 + np.array([0.0, 1, -1, 0.5] * 6)
    assert sentence(facts_of(v), "trend") == "There is no clear long-term trend between January 2020 and December 2021."
    assert "trend" not in facts_of(v[:11])                                                    # too short to say so
    assert "trend" not in facts_of(v, headline=False)                                         # and only the main series says it


# --- seasons ---
SEASON = np.array([100.0, 90, 80, 70, 60, 50, 60, 70, 80, 90, 100, 110])


def test_a_seasonal_pattern_names_the_highest_and_lowest_month_and_the_gap():
    f = facts_of(np.tile(SEASON, 3))
    assert sentence(f, "seasonality") == ("The numbers follow a seasonal pattern: December is usually the highest and June the lowest, "
                                          "a gap of about 75% of the usual level.")           # (110 - 50) / 80, where 80 is the average month
    assert "shift" not in f and "anomaly" not in f                                            # the swings of the seasons are not a change of pattern


def test_the_peak_of_the_season_is_named_in_quarters_and_half_years():
    quarters = [make_quarter(2020 + k // 4, k % 4 + 1) for k in range(12)]
    f = facts_of(np.tile([10.0, 20, 40, 30], 3), Ctx(UnitInfo(unit="persons"), "amount", "Q"), periods=quarters)
    assert "Q3 is usually the highest and Q1 the lowest" in sentence(f, "seasonality")


def test_an_unusual_month_in_a_seasonal_series_is_compared_with_the_same_month_a_year_earlier():
    v = np.tile(SEASON, 3)
    v[30] *= 1.5                                                                              # July 2022: 105 instead of 70
    f = facts_of(v)
    assert sentence(f, "anomaly") == ("July 2022 stands out: the change on a year earlier was +50.0%, unusually large for this series "
                                      "(possible context: the 2022-23 energy and food price shock).")


# --- unusual months and lasting changes ---
def spike(index, start=(2020, 1)):
    v = 100 + ((np.arange(24) % 3) - 1) * 1.0
    v[index] = 140.0
    return facts_of(v, periods=months(24, start))


def test_an_unusual_month_says_when_by_how_much_and_what_it_may_be_connected_with():
    f = spike(3)                                                                              # April 2020: from 100 to 140 is +40 %, and 99 to 140 is +41.4 %
    assert [a.text for a in f["anomaly"]] == [
        "April 2020 stands out: the change on the previous period was +38.6%, unusually large for this series (possible context: COVID-19 restrictions).",
        "May 2020 stands out: the change on the previous period was −28.6%, unusually large for this series (possible context: COVID-19 restrictions).",
    ]
    assert f["anomaly"][0].period == "2020-04" and f["anomaly"][0].data["change"] == pytest.approx(140 / 101 * 100 - 100)


def test_a_month_with_no_known_event_has_no_context():
    f = spike(6, start=(2024, 1))
    assert [a.text for a in f["anomaly"]][0] == "July 2024 stands out: the change on the previous period was +38.6%, unusually large for this series."


def test_the_main_series_gets_two_unusual_months_and_the_others_one():
    v = np.full(24, 100.0)
    v[5], v[15] = 130.0, 70.0
    assert len(facts_of(v)["anomaly"]) == 2
    assert len(facts_of(v, headline=False)["anomaly"]) == 1


def test_a_jump_in_a_rate_is_a_change_of_pattern_at_its_first_period():
    noise = np.array([0.0, 0.2, -0.2] * 4)
    f = facts_of(np.r_[5 + noise, 9 + noise], RATE, kind="rate")
    assert sentence(f, "shift") == ("Around January 2021 the pattern changed: the average level went from 5.0% to 9.0% "
                                    "(possible context: COVID-19 restrictions).")


def test_a_change_in_the_speed_of_growth_is_a_change_of_pattern_in_the_typical_change():
    noise = np.array([0.0, 0.2, -0.2] * 4)
    monthly = np.r_[0.2 + 0.05 * noise[:11], 5 + 0.05 * noise]
    f = facts_of(100 * np.r_[1.0, np.cumprod(1 + monthly / 100)])
    assert sentence(f, "shift") == ("Around January 2021 the pattern changed: the typical change from one period to the next went from 0.2% to 5.0% "
                                    "(possible context: COVID-19 restrictions).")


def test_only_the_main_series_reports_a_change_of_pattern_and_the_importance_follows_the_rank():
    noise = np.array([0.0, 0.2, -0.2] * 4)
    v = np.r_[5 + noise, 9 + noise]
    assert "shift" in facts_of(v, RATE, kind="rate") and "shift" not in facts_of(v, RATE, kind="rate", headline=False)
    st = compute_series_stats(months(24), LINE)
    main = {f.kind: f.importance for f in series_facts("Exports", st, MILLION_ALL, headline=True)}
    other = {f.kind: f.importance for f in series_facts("Exports", st, MILLION_ALL, headline=False)}
    assert main["latest"] == pytest.approx(0.95) and other["latest"] == pytest.approx(0.95 * 0.45)
    assert main["change"] == pytest.approx(0.9) and other["change"] == pytest.approx(0.9 * 0.45)
    assert main["trend"] == pytest.approx(0.7) and other["trend"] == pytest.approx(0.7 * 0.45)
    assert main["extreme"] == pytest.approx(0.85) and other["extreme"] == pytest.approx(0.85 * 0.45)


def test_with_several_series_every_sentence_that_needs_it_starts_with_the_subject():
    st = compute_series_stats(months(24), LINE)
    plain = [f.text for f in series_facts("Exports", st, MILLION_ALL, headline=True)]
    named = [f.text for f in series_facts("Exports", st, MILLION_ALL, headline=True, prefix=True)]
    assert plain[2] == "The latest value is the highest of all 24 observations, going back to January 2020."
    assert named[2] == "Exports: " + plain[2] and named[3] == "Exports: " + plain[3]


# --- comparing categories ---
PEOPLE = Ctx(UnitInfo(unit="persons"), "amount", "A")


def test_a_ranking_names_the_two_highest_and_the_two_lowest_and_how_far_apart_they_are():
    values = pd.Series({"Tirana": 900.0, "Durres": 400.0, "Vlore": 300.0, "Shkoder": 200.0, "Kukes": 100.0})
    assert ranking_fact("Population", values, PEOPLE, "2023", "region").text == (
        "Population by region, 2023: highest in Tirana (900 people) and Durres (400 people), lowest in Kukes (100 people) and Shkoder (200 people). "
        "The highest is 9.0 times the lowest.")
    close = pd.Series({"A": 100.0, "B": 120.0, "C": 140.0})
    assert "times" not in ranking_fact("Population", close, PEOPLE, "2023", "region").text                 # 1.4 times is not worth saying


def test_with_three_categories_no_category_is_both_the_highest_and_the_lowest():
    text = ranking_fact("Rate", pd.Series({"A": 9.0, "B": 7.0, "C": 3.0}), RATE, "2023", "region").text
    assert text == "Rate by region, 2023: highest in A (9.0%), lowest in C (3.0%)."
    assert ranking_fact("Rate", pd.Series({"A": 9.0, "B": 7.0}), RATE, "2023", "region") is None             # two are too few to rank


def test_a_ranking_of_rates_does_not_give_a_ratio_and_a_ratio_needs_a_factor_of_one_and_a_half():
    values = pd.Series({"A": 90.0, "B": 60.0, "C": 30.0, "D": 20.0})
    assert "times" not in ranking_fact("Rate", values, RATE, "2023", "region").text
    assert "1.5 times the lowest" in ranking_fact("Population", pd.Series({"A": 150.0, "B": 120.0, "C": 100.0}), PEOPLE, "2023", "region").text
    assert "times" not in ranking_fact("Population", pd.Series({"A": 149.0, "B": 120.0, "C": 100.0}), PEOPLE, "2023", "region").text


def test_the_biggest_shares_and_how_concentrated_they_are():
    values = pd.Series({"Tirana": 900.0, "Durres": 400.0, "Vlore": 300.0, "Shkoder": 200.0, "Kukes": 100.0})
    assert composition_fact("Population", values, "2023", "region").text == (
        "Population by region, 2023: the biggest shares are Tirana (47%), Durres (21%) and Vlore (16%). "
        "The top three add up to 84% of the total, so it is moderately concentrated.")
    assert composition_fact("Population", pd.Series({"A": 1.0, "B": 2.0}), "2023", "region") is None


def test_women_against_men_in_amounts_and_in_rates():
    women, men = pd.Series({"Agri": 80.0, "Ind": 90.0, "Svc": 110.0}), pd.Series({"Agri": 100.0, "Ind": 100.0, "Svc": 100.0})
    assert gap_fact("Wage", cs.gaps(women, men), Ctx(UnitInfo(unit="ALL"), "amount", "A"), "2023", "activity").text == (
        "Wage, 2023: across 3 categories by economic activity, the value for women is 7% below the value for men on average, and higher in 1 "
        "of them. The widest gap is in Agri (women ALL 80.0, men ALL 100.0).")                   # the ratios 0.8, 0.9 and 1.1 average 0.933
    assert gap_fact("Rate", cs.gaps(women / 10, men / 10), RATE, "2023", "activity").text == (
        "Rate, 2023: across 3 categories by economic activity, the value for women is 0.7 pp below the value for men on average, and higher in 1 "
        "of them. The widest gap is in Agri (women 8.0%, men 10.0%).")
    assert gap_fact("Wage", cs.gaps(women, men)[:1], PEOPLE, "2023", "activity") is None                    # one category is not "across categories"


def test_women_above_men_and_no_difference():
    men = pd.Series({"A": 100.0, "B": 100.0})
    above = gap_fact("Wage", cs.gaps(pd.Series({"A": 120.0, "B": 110.0}), men), PEOPLE, "", "activity").text
    assert above.startswith("Wage: across 2 categories by economic activity, the value for women is 15% above the value for men on average, "
                            "and higher in 2 of them.")
    same = gap_fact("Wage", cs.gaps(men.copy(), men), PEOPLE, "", "activity").text
    assert "about the same as the value for men" in same and "higher in 0 of them" in same
    close = gap_fact("Wage", cs.gaps(pd.Series({"A": 100.4, "B": 100.4}), men), PEOPLE, "", "activity").text
    assert "about the same as the value for men" in close                                      # 0.4 % is inside the rounding


def test_the_biggest_risers_and_fallers_among_the_groups():
    groups = pd.Series({"Food": 5.0, "Housing": 2.0, "Transport": -1.5, "Health": 0.02, "Other": 0.0})
    fact = movers_fact("Inflation by group", groups, Ctx(UnitInfo(unit="%"), "growth", "M"), "2024-05", "a year earlier")
    assert fact.text == ("Inflation by group, May 2024 compared with a year earlier. Biggest increases: Food (+5.0 pp) and Housing (+2.0 pp). "
                         "Biggest decreases: Transport (−1.5 pp).")
    assert fact.data["up"] == {"Food": 5.0, "Housing": 2.0} and fact.data["down"] == {"Transport": -1.5}
    assert movers_fact("x", groups.iloc[:3], Ctx(UnitInfo(unit="%"), "growth", "M"), "2024-05", "a year earlier") is None           # fewer than four
    flat = pd.Series({"A": 0.0, "B": 0.01, "C": -0.01, "D": 0.04})
    assert movers_fact("x", flat, Ctx(UnitInfo(unit="%"), "growth", "M"), "2024-05", "a year earlier") is None                      # nothing moved


def test_movers_in_amounts_are_percentages_and_at_most_three_of_each_are_named():
    groups = pd.Series({"A": 50.0, "B": 40.0, "C": 30.0, "D": 20.0, "E": -10.0, "F": -20.0, "G": -30.0, "H": -40.0})
    text = movers_fact("Wages", groups, MILLION_ALL, "2024-05", "the previous month", "2023-05").text
    assert text == ("Wages, May 2024 compared with May 2023. Biggest increases: A (+50.0%), B (+40.0%) and C (+30.0%). "
                    "Biggest decreases: H (−40.0%), G (−30.0%) and F (−20.0%).")


def test_growth_between_two_periods_names_the_fastest_and_slowest():
    growth = pd.Series({"A": 10.0, "B": 5.0, "C": -2.0, "D": 20.0})
    assert growth_fact("Population", growth, "2015", "2023", "region").text == (
        "Population by region, 2015 to 2023: grew fastest in D (+20.0%) and A (+10.0%) and slowest in C (−2.0%) and B (+5.0%).")
    assert growth_fact("Population", growth.iloc[:3], "2015", "2023", "region") is None


@pytest.mark.parametrize("title, short", [
    ("Gross average monthly wage by economic activity and sex, 2023", "Gross average monthly wage"),
    ("Popullsia sipas gjinisë", "Popullsia"), ("Wage, 2020-2023", "Wage"), ("Consumer price index (2015 = 100)", "Consumer price index"),
    ("Population", "Population"), ("A" * 80, "A" * 69 + "…"),
])
def test_a_long_title_becomes_a_short_subject(title, short):
    assert short_measure(title) == short


def test_a_value_of_zero_is_written_as_zero():
    assert sentence(facts_of([5.0, 4, 3, 5, 6, 2, 4, 5, 4, 3, 2, 0]), "latest") == "Exports: ALL 0 in December 2020."
    assert Ctx(UnitInfo(unit="tonnes"), "amount", "M").val(0.0) == "0 tonnes" and Ctx(UnitInfo(unit="%"), "rate", "M").val(0.0) == "0.0%"
    assert Ctx(UnitInfo(unit="persons"), "amount", "M").val(0.0) == "0 people" and Ctx(UnitInfo(unit="index"), "index", "M").val(0.0) == "0.0"


# --- boundaries the first version of these tests left open ---
def test_eight_observations_are_the_least_for_a_trend_or_a_place_in_the_history():
    assert {"trend", "extreme"} <= set(facts_of(np.arange(1.0, 9)))
    assert not {"trend", "extreme"} & set(facts_of(np.arange(1.0, 8)))


def test_a_yearly_series_is_compared_with_the_previous_year_only_once():
    from instatkit.semantics.periods import make_year

    years = [make_year(2015 + k) for k in range(9)]
    ctx = Ctx(UnitInfo(unit="ALL", scale=1e6, scale_label="million"), "amount", "A")
    f = facts_of([100.0, 110, 120, 130, 140, 150, 160, 170, 187], ctx, periods=years)
    assert sentence(f, "change") == "Exports: up 10.0% on 2022."                                              # 187 / 170


def test_a_seasonal_gap_is_in_the_unit_of_an_amount_and_in_points_for_a_rate():
    around_zero = np.tile(SEASON - 80, 3)                                                                      # -30 ... +30: the average month is 0
    assert "a gap of about ALL 60 million." in sentence(facts_of(around_zero), "seasonality")
    assert "a gap of about 60.0 pp." in sentence(facts_of(around_zero, RATE, kind="rate"), "seasonality")


def test_a_weak_seasonal_pattern_is_not_reported():
    weak = np.tile(SEASON, 3) + np.array([0.0, 40, -35, 20, -45, 30, -10, 25, -30, 45, -20, 15] * 3) * np.repeat([1.0, -1.0, 1.0], 12)
    f = facts_of(weak)
    assert "seasonality" not in f


def test_the_importance_of_each_kind_of_finding_decides_what_is_shown_first():
    st = compute_series_stats(months(24), np.r_[5 + np.array([0.0, 0.2, -0.2] * 4), 9 + np.array([0.0, 0.2, -0.2] * 4)], kind="rate")
    main = {f.kind: f.importance for f in series_facts("Exports", st, RATE, headline=True)}
    assert main["shift"] == pytest.approx(0.6) and main["anomaly"] == pytest.approx(0.6) and main["trend"] == pytest.approx(0.7)
    seasonal = {f.kind: f.importance for f in series_facts("Exports", compute_series_stats(months(36), np.tile(SEASON, 3)), MILLION_ALL, headline=True)}
    assert seasonal["seasonality"] == pytest.approx(0.65) and seasonal["trend"] == pytest.approx(0.45)
    values = pd.Series({"Tirana": 900.0, "Durres": 400.0, "Vlore": 300.0, "Shkoder": 200.0, "Kukes": 100.0})
    women, men = pd.Series({"A": 80.0, "B": 90.0}), pd.Series({"A": 100.0, "B": 100.0})
    weights = {
        "movers": movers_fact("m", pd.Series({"A": 5.0, "B": 2.0, "C": -1.5, "D": 1.0}), RATE, "2024-05", "a year earlier").importance,
        "ranking": ranking_fact("r", values, PEOPLE, "2023", "region").importance,
        "gap": gap_fact("g", cs.gaps(women, men), PEOPLE, "2023", "activity").importance,
        "composition": composition_fact("c", values, "2023", "region").importance,
        "growth": growth_fact("w", pd.Series({"A": 10.0, "B": 5.0, "C": -2.0, "D": 20.0}), "2015", "2023", "region").importance,
    }
    assert weights == {"movers": 0.8, "ranking": 0.75, "gap": 0.72, "composition": 0.7, "growth": 0.7}


def test_a_title_of_exactly_the_limit_is_kept_whole():
    assert short_measure("A" * 70) == "A" * 70 and short_measure("A" * 71) == "A" * 69 + "…"
    assert short_measure("Wage level", limit=4) == "Wag…"


def test_a_small_rise_in_an_amount_that_can_be_negative_keeps_its_sign():
    zero = compute_series_stats(months(10), np.arange(-4.0, 6))
    assert _change_text(MILLION_ALL, zero, 0.5) == "+ALL 500,000" and _change_text(MILLION_ALL, zero, -0.5) == "−ALL 500,000"


def test_a_long_ranking_still_names_only_two_at_each_end():
    values = pd.Series({"A": 80.0, "B": 70.0, "C": 60.0, "D": 50.0, "E": 40.0, "F": 30.0, "G": 20.0, "H": 10.0})
    text = ranking_fact("Rate", values, RATE, "2023", "region").text
    assert text.startswith("Rate by region, 2023: highest in A (80.0%) and B (70.0%), lowest in H (10.0%) and G (20.0%).")
    for left_out in ("C (", "D (", "E (", "F ("):
        assert left_out not in text
    assert "ranking" not in text and ranking_fact("Rate", values.iloc[:6], RATE, "2023", "region").text.count("(") == 4        # six: 2 + 2 as well


def test_the_yearly_rise_of_a_plain_number_is_given_to_two_decimals():
    """Amounts of money choose their own precision; a number in no unit shows the two decimals the sentence asks for."""
    values = [-6.0, -5.2, -3.9, -3.1, -2.0, -0.8, 1.1, 2.3, 2.9, 4.2, 5.1, 6.3, 7.4]
    slope = np.polyfit(np.arange(13), values, 1)[0]
    assert f"{slope * 12:.4f}"[-2:] not in ("00", "50"), "the test needs a rise that needs a third decimal"
    plain = Ctx(UnitInfo(unit=""), "amount", "M")
    assert sentence(facts_of(values, plain), "trend") == f"From January 2020 to January 2021 the series has risen by about {slope * 12:.2f} a year."


def test_a_seasonal_pattern_is_reported_from_a_strength_of_exactly_four_tenths():
    import dataclasses

    st = compute_series_stats(months(36), np.tile(SEASON, 3).astype(float))
    assert st.seasonality is not None and st.seasonality.strength > 0.9

    def reported(strength):
        shown = dataclasses.replace(st, seasonality=dataclasses.replace(st.seasonality, strength=strength))
        return any(f.kind == "seasonality" for f in series_facts("Exports", shown, MILLION_ALL, headline=True))

    assert reported(0.4) and reported(0.5)
    assert not reported(0.39999)
